from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class OutputMode(StrEnum):
    MARKDOWN = "markdown"
    RAG = "rag"


class OcrMode(StrEnum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class JobCancelled(RuntimeError):
    """Conversion was stopped by the user or by shutdown."""


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class ProcessingOptions:
    output_name: str = ""
    output_mode: OutputMode = OutputMode.MARKDOWN
    filter_mode: str = "smart"
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    ocr_mode: OcrMode = OcrMode.AUTO
    include_notebook_outputs: bool = False
    include_toc: bool = True
    chunk_target: int = 800
    chunk_overlap: int = 100

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProcessingOptions:
        target = int(value.get("chunk_target", 800))
        overlap = int(value.get("chunk_overlap", 100))
        if not 200 <= target <= 4_000:
            raise ValueError("chunk_target must be between 200 and 4000")
        if not 0 <= overlap < target:
            raise ValueError("chunk_overlap must be non-negative and smaller than chunk_target")
        filter_mode = str(value.get("filter_mode", "smart"))
        if filter_mode not in {"smart", "project", "all"}:
            raise ValueError("filter_mode must be smart, project, or all")
        return cls(
            output_name=str(value.get("output_name", "")).strip()[:120],
            output_mode=OutputMode(value.get("output_mode", OutputMode.MARKDOWN)),
            filter_mode=filter_mode,
            include_patterns=_string_list(value.get("include_patterns", [])),
            exclude_patterns=_string_list(value.get("exclude_patterns", [])),
            ocr_mode=OcrMode(value.get("ocr_mode", OcrMode.AUTO)),
            include_notebook_outputs=bool(value.get("include_notebook_outputs", False)),
            include_toc=bool(value.get("include_toc", True)),
            chunk_target=target,
            chunk_overlap=overlap,
        )


@dataclass(frozen=True, slots=True)
class SourceSpec:
    id: str
    kind: str
    label: str
    url: str | None = None
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class StagedFile:
    source_id: str
    source_label: str
    path: Path
    relative_path: str
    source_url: str | None = None
    archive_depth: int = 0


@dataclass(slots=True)
class Document:
    source_id: str
    source_label: str
    path: str
    title: str
    media_type: str
    content: str
    content_kind: str = "raw"
    language: str | None = None
    source_url: str | None = None
    page: int | None = None
    cell: int | None = None
    warnings: list[str] = field(default_factory=list)
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class SkipRecord:
    source_id: str
    path: str
    reason: str


@dataclass(slots=True)
class Artifact:
    id: str
    name: str
    media_type: str
    path: Path
    size: int
    sha256: str

    def public(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("path")
        return value


@dataclass(slots=True)
class ProgressEvent:
    sequence: int
    event: str
    phase: str
    completed: int
    total: int
    message: str
    source_id: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("patterns must be arrays of strings")
    if len(value) > 256 or any(len(item) > 512 for item in value):
        raise ValueError("Too many patterns or an individual pattern is too long")
    return [item.strip() for item in value if item.strip()]
