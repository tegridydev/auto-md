from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limits:
    max_job_bytes: int = 512 * 1024 * 1024
    max_sources: int = 64
    max_manifest_bytes: int = 8 * 1024**2
    max_file_bytes: int = 100 * 1024 * 1024
    max_github_bytes: int = 250 * 1024 * 1024
    max_web_bytes: int = 10 * 1024 * 1024
    max_expanded_bytes: int = 1024 * 1024 * 1024
    max_archive_entries: int = 20_000
    max_archive_depth: int = 2
    max_pdf_pages: int = 500
    max_document_chars: int = 8_000_000
    max_job_chars: int = 48_000_000
    max_chunk_count: int = 50_000
    max_chunk_bytes: int = 256 * 1024**2
    max_job_seconds: int = 900
    max_operation_seconds: int = 180
    max_image_pixels: int = 50_000_000
    max_redirects: int = 5
    remote_timeout_seconds: int = 60


LIMITS = Limits()
MAX_WORKER_MESSAGE = 65_536

DEFAULT_EXCLUDES = (
    ".git/",
    ".hg/",
    ".svn/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".cache/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".next/",
    ".nuxt/",
    "coverage/",
    "dist/",
    "build/",
    "target/",
    "*.min.js",
    "*.min.css",
    "*.map",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "uv.lock",
)

IMAGE_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}
SUPPORTED_IMAGE_EXTENSIONS = frozenset(IMAGE_FORMATS)
SUPPORTED_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz"}
