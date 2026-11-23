from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .config import LIMITS, SUPPORTED_ARCHIVE_EXTENSIONS
from .extraction import Extractor
from .filtering import SourceFilter
from .models import (
    Artifact,
    Document,
    JobCancelled,
    ProcessingOptions,
    SkipRecord,
    SourceSpec,
    StagedFile,
)
from .rendering import build_artifacts
from .security import (
    ArchiveBudget,
    SecurityError,
    download_url,
    ensure_regular_file,
    extract_archive,
    github_archive_url,
    safe_filename,
    validate_source_id,
)

ProgressCallback = Callable[[str, str, int, int, str, str | None], None]


@dataclass(slots=True)
class PipelineResult:
    artifacts: list[Artifact]
    documents: list[Document]
    skipped: list[SkipRecord]
    warnings: list[str]


class Pipeline:
    def __init__(
        self,
        workspace: Path,
        cancel_event: threading.Event,
        progress: ProgressCallback,
    ) -> None:
        self.workspace = workspace
        self.cancel_event = cancel_event
        self.progress = progress
        self.extractor = Extractor()
        self.skipped: list[SkipRecord] = []
        self.warnings: list[str] = []
        self._archive_budget = ArchiveBudget(LIMITS.max_archive_entries, LIMITS.max_expanded_bytes)
        self._remote_bytes = 0
        self._expanded_count = 0

    def run(self, sources: list[SourceSpec], options: ProcessingOptions) -> PipelineResult:
        staged: list[StagedFile] = []
        for index, source in enumerate(sources, start=1):
            self._check_cancelled()
            self.progress(
                "progress",
                "acquiring",
                index - 1,
                len(sources),
                f"Preparing {source.label}",
                source.id,
            )
            try:
                staged.extend(self._acquire_source(source, options))
            except JobCancelled:
                raise
            except Exception as exc:
                self.skipped.append(SkipRecord(source.id, source.label, str(exc)))
                self.warnings.append(f"{source.label}: {exc}")
            self.progress(
                "progress", "acquiring", index, len(sources), f"Prepared {source.label}", source.id
            )

        staged.sort(
            key=lambda item: (
                item.source_label.casefold(),
                item.relative_path.casefold(),
                item.relative_path,
                item.source_id,
            )
        )
        documents: list[Document] = []
        remaining_chars = LIMITS.max_job_chars
        total = len(staged)
        for index, item in enumerate(staged, start=1):
            self._check_cancelled()
            self.progress(
                "progress",
                "extracting",
                index - 1,
                total,
                f"Extracting {item.relative_path}",
                item.source_id,
            )
            try:
                if remaining_chars <= 0:
                    raise SecurityError("Job text budget exhausted")
                document = self.extractor.extract(item, options)
                if not document.content.strip():
                    raise ValueError("No readable content")
                if len(document.content) > remaining_chars:
                    raise SecurityError("Document exceeds the remaining job text budget")
                remaining_chars -= len(document.content)
                documents.append(document)
                self.warnings.extend(
                    f"{item.relative_path}: {warning}" for warning in document.warnings
                )
            except JobCancelled:
                raise
            except (ValueError, OSError) as exc:
                self.skipped.append(SkipRecord(item.source_id, item.relative_path, str(exc)))
            except Exception as exc:
                self.skipped.append(
                    SkipRecord(
                        item.source_id,
                        item.relative_path,
                        f"Extractor error: {type(exc).__name__}: {exc}",
                    )
                )
            self.progress(
                "progress",
                "extracting",
                index,
                total,
                f"Processed {item.relative_path}",
                item.source_id,
            )

        if not documents:
            reasons = "; ".join(record.reason for record in self.skipped[:5])
            raise ValueError(f"No supported readable documents were found. {reasons}".strip())

        self._check_cancelled()
        self.progress("progress", "packaging", 0, 1, "Building output", None)
        artifacts = build_artifacts(
            self.workspace / "output",
            requested_name=options.output_name,
            documents=documents,
            skipped=self.skipped,
            warnings=self.warnings,
            sources=sources,
            options=options,
        )
        self.progress("progress", "packaging", 1, 1, "Output ready", None)
        return PipelineResult(artifacts, documents, self.skipped, self.warnings)

    def _acquire_source(self, source: SourceSpec, options: ProcessingOptions) -> list[StagedFile]:
        validate_source_id(source.id)
        if source.kind == "upload":
            root = self.workspace / "uploads" / source.id
            if not root.is_dir():
                raise ValueError("Uploaded source has no files")
            return self._scan(root, source, options, prefix="", depth=0)
        if source.kind == "github":
            if not source.url:
                raise ValueError("GitHub source is missing its URL")
            remote_dir = self.workspace / "remote" / source.id
            archive = remote_dir / "repository.zip"
            url = github_archive_url(source.url, source.ref)
            result = download_url(
                url,
                archive,
                github=True,
                check_cancelled=self._check_cancelled,
                max_bytes=min(LIMITS.max_github_bytes, LIMITS.max_job_bytes - self._remote_bytes),
            )
            self._remote_bytes += result.size
            extracted = self.workspace / "expanded" / source.id / "github"
            try:
                self._expand(archive, extracted)
            finally:
                archive.unlink(missing_ok=True)
            root = _collapse_single_root(extracted)
            return self._scan(root, source, options, prefix="", depth=1)
        if source.kind == "web":
            if not source.url:
                raise ValueError("Web source is missing its URL")
            parsed = urlsplit(source.url)
            candidate = safe_filename(unquote(Path(parsed.path).name), "web-page")
            destination = self.workspace / "remote" / source.id / "download"
            result = download_url(
                source.url,
                destination,
                check_cancelled=self._check_cancelled,
                max_bytes=min(LIMITS.max_web_bytes, LIMITS.max_job_bytes - self._remote_bytes),
            )
            self._remote_bytes += result.size
            detected_extension = {
                "text/html": ".html",
                "application/xhtml+xml": ".html",
                "text/markdown": ".md",
                "text/css": ".css",
                "text/csv": ".csv",
                "application/xml": ".xml",
                "text/xml": ".xml",
            }.get(result.content_type, ".txt")
            # Remote filenames cannot choose a native decoder. Preserve common text extensions.
            extension = Path(candidate).suffix.lower()
            if extension != detected_extension and not (
                result.content_type == "text/plain" and extension in {".txt", ".md"}
            ):
                candidate = str(Path(candidate).with_suffix(detected_extension))
            renamed = destination.with_name(candidate)
            destination.rename(renamed)
            destination = renamed
            return [
                StagedFile(
                    source.id,
                    source.label,
                    destination,
                    destination.name,
                    source_url=result.final_url,
                )
            ]
        raise ValueError(f"Unsupported source kind: {source.kind}")

    def _scan(
        self,
        root: Path,
        source: SourceSpec,
        options: ProcessingOptions,
        *,
        prefix: str,
        depth: int,
    ) -> list[StagedFile]:
        filter_root = (
            _collapse_single_root(root) if source.kind == "upload" and depth == 0 else root
        )
        source_filter = SourceFilter(
            filter_root,
            mode=options.filter_mode,
            includes=options.include_patterns,
            excludes=options.exclude_patterns,
        )
        files: list[StagedFile] = []
        for path in root.rglob("*"):
            self._check_cancelled()
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            display_path = f"{prefix}/{relative}".strip("/")
            if not path.is_relative_to(filter_root):
                continue
            if not source_filter.allows(path.relative_to(filter_root).as_posix()):
                continue
            try:
                ensure_regular_file(path)
            except SecurityError as exc:
                self.skipped.append(SkipRecord(source.id, display_path, str(exc)))
                continue
            size = path.stat().st_size
            if size > LIMITS.max_file_bytes:
                self.skipped.append(
                    SkipRecord(source.id, display_path, "File exceeds the size limit")
                )
                continue
            if _is_archive(path):
                if depth >= LIMITS.max_archive_depth:
                    self.skipped.append(
                        SkipRecord(source.id, display_path, "Archive nesting limit reached")
                    )
                    continue
                self._expanded_count += 1
                extracted = (
                    self.workspace / "expanded" / source.id / f"archive-{self._expanded_count}"
                )
                try:
                    self._expand(path, extracted)
                    archive_prefix = f"{display_path}"
                    files.extend(
                        self._scan(
                            _collapse_single_root(extracted),
                            source,
                            options,
                            prefix=archive_prefix,
                            depth=depth + 1,
                        )
                    )
                except (ValueError, OSError) as exc:
                    self.skipped.append(SkipRecord(source.id, display_path, str(exc)))
                continue
            files.append(
                StagedFile(
                    source.id,
                    source.label,
                    path,
                    display_path,
                    source_url=source.url if source.kind in {"github", "web"} else None,
                    archive_depth=depth,
                )
            )
        return files

    def _expand(self, path: Path, destination: Path) -> None:
        extract_archive(
            path,
            destination,
            budget=self._archive_budget,
            check_cancelled=self._check_cancelled,
        )

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled("Job cancelled")


def _is_archive(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return False
    if suffix in SUPPORTED_ARCHIVE_EXTENSIONS or suffix in {".tbz", ".tbz2", ".txz"}:
        return True
    # Avoid opening ZIP and TAR parsers for every ordinary file in a repository.
    with path.open("rb") as stream:
        header = stream.read(512)
    return (
        header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00"))
        or header[257:262] == b"ustar"
    )


def _collapse_single_root(root: Path) -> Path:
    children = [child for child in root.iterdir() if child.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir() and not children[0].is_symlink():
        return children[0]
    return root
