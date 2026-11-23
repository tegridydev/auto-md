from __future__ import annotations

from pathlib import Path

import pathspec

from .config import DEFAULT_EXCLUDES
from .security import SecurityError


class SourceFilter:
    def __init__(
        self,
        root: Path,
        *,
        mode: str,
        includes: list[str],
        excludes: list[str],
    ) -> None:
        patterns: list[str] = []
        if mode == "smart":
            patterns.extend(DEFAULT_EXCLUDES)
            patterns.extend([".*", "**/.*"])
        if mode in {"smart", "project"}:
            for name in (".gitignore", ".automdignore"):
                ignore_file = root / name
                if ignore_file.is_file() and not ignore_file.is_symlink():
                    with ignore_file.open(encoding="utf-8", errors="replace") as stream:
                        text = stream.read(256 * 1024 + 1)
                    lines = text.splitlines()
                    if len(text) > 256 * 1024 or len(lines) > 2_048:
                        raise SecurityError(f"{name} exceeds its size or pattern limit")
                    patterns.extend(lines)
        patterns.extend(excludes)
        self._excludes = pathspec.GitIgnoreSpec.from_lines(patterns)
        self._includes = pathspec.GitIgnoreSpec.from_lines(includes) if includes else None

    def allows(self, relative_path: str) -> bool:
        value = relative_path.replace("\\", "/")
        if self._includes and self._includes.match_file(value):
            return True
        return not self._excludes.match_file(value)
