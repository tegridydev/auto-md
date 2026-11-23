from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__
from .config import DEFAULT_EXCLUDES, LIMITS, SUPPORTED_IMAGE_EXTENSIONS
from .jobs import BusyError, Job, JobManager
from .models import JobStatus, ProcessingOptions, SourceSpec
from .security import (
    SecurityError,
    path_key,
    resolve_inside,
    safe_relative_path,
    validate_source_id,
)

logger = logging.getLogger(__name__)
PACKAGE_ROOT = Path(__file__).parent
WEB_ROOT = PACKAGE_ROOT / "web"
TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.COMPLETED_WITH_WARNINGS,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class SecurityHeadersMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; "
                            b"img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                            b"base-uri 'none'; frame-ancestors 'none'",
                        ),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"cross-origin-opener-policy", b"same-origin"),
                        (b"cache-control", b"no-store"),
                        (b"cross-origin-resource-policy", b"same-origin"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(manager: JobManager | None = None) -> Starlette:
    job_manager = manager or JobManager()
    session_token = secrets.token_urlsafe(32)
    instance_id = secrets.token_urlsafe(12)
    cookie_token = secrets.token_urlsafe(32)
    cookie_name = f"automd_session_{instance_id}"
    receiving_upload = False
    index_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    index_html = index_html.replace("__AUTOMD_TOKEN__", session_token)
    index_html = index_html.replace("__AUTOMD_VERSION__", __version__)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await run_in_threadpool(job_manager.shutdown)

    async def index(request: Request) -> Response:
        response = HTMLResponse(index_html)
        response.set_cookie(
            cookie_name,
            cookie_token,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/",
        )
        return response

    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok", "version": __version__, "instance_id": instance_id})

    async def capabilities(request: Request) -> Response:
        _require_session(request, cookie_name, cookie_token)
        return JSONResponse(
            {
                "version": __version__,
                "source_kinds": ["upload", "github", "web"],
                "output_modes": ["markdown", "rag"],
                "ocr_modes": ["auto", "always", "never"],
                "image_extensions": sorted(SUPPORTED_IMAGE_EXTENSIONS),
                "default_excludes": list(DEFAULT_EXCLUDES),
                "limits": {
                    "max_job_bytes": LIMITS.max_job_bytes,
                    "max_file_bytes": LIMITS.max_file_bytes,
                    "max_github_bytes": LIMITS.max_github_bytes,
                    "max_web_bytes": LIMITS.max_web_bytes,
                    "max_archive_entries": LIMITS.max_archive_entries,
                    "max_pdf_pages": LIMITS.max_pdf_pages,
                },
            }
        )

    async def create_job(request: Request) -> Response:
        nonlocal receiving_upload
        _require_mutation(request, cookie_name, cookie_token, session_token)
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != "multipart/form-data":
            return _error("Expected a multipart job submission", 415)
        if receiving_upload:
            return _error("Another job submission is uploading", 429)
        receiving_upload = True
        form: FormData | None = None
        job: Job | None = None
        started = False
        try:
            job_manager.check_capacity()
            parser = BoundedMultipartParser(
                request.headers,
                request.stream(),
                max_files=LIMITS.max_archive_entries,
                max_fields=1,
                max_part_size=LIMITS.max_manifest_bytes,
            )
            async with asyncio.timeout(LIMITS.max_operation_seconds):
                form = await parser.parse()
            if not parser.finished:
                raise ValueError("Incomplete multipart submission")
            raw_spec = form.get("spec")
            if not isinstance(raw_spec, str):
                raise ValueError("Missing JSON job spec")
            payload = _object(json.loads(raw_spec), "Job spec")
            sources = _parse_sources(payload.get("sources"))
            options = ProcessingOptions.from_dict(_object(payload.get("options", {}), "Options"))
            manifest = _parse_file_manifest(payload.get("files", []), sources)
            uploads = [
                (name, value) for name, value in form.multi_items() if isinstance(value, UploadFile)
            ]
            if len(uploads) != len(manifest) or {part for part, _ in uploads} != manifest.keys():
                raise ValueError("Upload parts must match the manifest exactly")
            if any(item.size is None or item.size > LIMITS.max_file_bytes for _, item in uploads):
                raise UploadTooLarge("An uploaded file exceeds the size limit")
            if sum(item.size or 0 for _, item in uploads) > LIMITS.max_job_bytes:
                raise UploadTooLarge("Upload exceeds the job size limit")
            job = job_manager.create(sources, options)
            await run_in_threadpool(_stage_uploads, job, uploads, manifest)
            job_manager.start(job)
            started = True
            return JSONResponse(
                {"job": job.snapshot(), "events_url": f"/api/v1/jobs/{job.id}/events"},
                status_code=202,
            )
        except BusyError as exc:
            return _error(str(exc), 429)
        except UploadTooLarge as exc:
            return _error(str(exc), 413)
        except HTTPException:
            raise
        except TimeoutError:
            return _error("Upload timed out", 408)
        except ClientDisconnect:
            return _error("Upload disconnected", 400)
        except (ValueError, TypeError, KeyError, RecursionError, MultiPartException) as exc:
            return _error(str(exc), 400)
        except Exception:
            logger.exception("Job staging failed")
            return _error("Unable to stage the upload", 500)
        finally:
            receiving_upload = False
            if job is not None and not started:
                await run_in_threadpool(job_manager.delete, job.id)
            if form is not None:
                with suppress(OSError):
                    await form.close()

    async def get_job(request: Request) -> Response:
        _require_session(request, cookie_name, cookie_token)
        job = _job_or_none(job_manager, request.path_params["job_id"])
        return JSONResponse(job.snapshot()) if job else _error("Job not found", 404)

    async def job_events(request: Request) -> Response:
        _require_session(request, cookie_name, cookie_token)
        job = _job_or_none(job_manager, request.path_params["job_id"])
        if not job:
            return _error("Job not found", 404)
        try:
            sequence = int(
                request.headers.get("last-event-id", request.query_params.get("after", "0"))
            )
        except ValueError:
            sequence = 0

        async def stream() -> AsyncIterator[bytes]:
            nonlocal sequence
            idle_ticks = 0
            while True:
                current = job_manager.get(job.id)
                if not current:
                    return
                events = current.events_after(sequence)
                for event in events:
                    sequence = event.sequence
                    payload = json.dumps(event.public(), ensure_ascii=False, separators=(",", ":"))
                    message = f"id: {event.sequence}\nevent: {event.event}\ndata: {payload}\n\n"
                    yield message.encode()
                if current.status in TERMINAL_STATUSES and not current.events_after(sequence):
                    return
                idle_ticks += 1
                if idle_ticks % 60 == 0:
                    yield b": keepalive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def cancel_job(request: Request) -> Response:
        _require_mutation(request, cookie_name, cookie_token, session_token)
        job = job_manager.cancel(request.path_params["job_id"])
        return JSONResponse(job.snapshot()) if job else _error("Job not found", 404)

    async def delete_job(request: Request) -> Response:
        _require_mutation(request, cookie_name, cookie_token, session_token)
        deleted = job_manager.delete(request.path_params["job_id"])
        return Response(status_code=204) if deleted else _error("Job not found", 404)

    async def artifact(request: Request) -> Response:
        _require_session(request, cookie_name, cookie_token)
        job = _job_or_none(job_manager, request.path_params["job_id"])
        if not job:
            return _error("Job not found", 404)
        artifact_id = request.path_params["artifact_id"]
        match = next((item for item in job.artifacts if item.id == artifact_id), None)
        if (
            not match
            or match.path.is_symlink()
            or not match.path.is_file()
            or match.path.resolve().parent != (job.workspace / "output").resolve()
        ):
            return _error("Artifact not found", 404)
        if request.query_params.get("preview") == "1":
            if match.media_type != "text/markdown":
                return _error("Preview unavailable for this output", 400)
            text = await run_in_threadpool(_read_preview, match.path)
            return PlainTextResponse(text)
        return FileResponse(
            match.path,
            media_type=match.media_type,
            filename=match.name,
            content_disposition_type="attachment",
        )

    routes = [
        Route("/", index),
        Route("/health", health),
        Route("/api/v1/capabilities", capabilities),
        Route(
            "/api/v1/jobs",
            create_job,
            methods=["POST"],
            max_body_size=LIMITS.max_job_bytes + LIMITS.max_manifest_bytes + 16 * 1024**2,
        ),
        Route("/api/v1/jobs/{job_id}", get_job, methods=["GET"]),
        Route("/api/v1/jobs/{job_id}", delete_job, methods=["DELETE"]),
        Route("/api/v1/jobs/{job_id}/events", job_events, methods=["GET"]),
        Route("/api/v1/jobs/{job_id}/cancel", cancel_job, methods=["POST"]),
        Route("/api/v1/jobs/{job_id}/artifacts/{artifact_id}", artifact, methods=["GET"]),
        Mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static"),
    ]
    middleware = [
        Middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"]),
        Middleware(SecurityHeadersMiddleware),
    ]

    async def security_error(request: Request, exc: SecurityError) -> Response:
        return _error(str(exc), 403)

    async def http_error(request: Request, exc: HTTPException) -> Response:
        return _error(str(exc.detail), exc.status_code)

    app = Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
        exception_handlers={SecurityError: security_error, HTTPException: http_error},
    )
    app.state.job_manager = job_manager
    app.state.session_token = session_token
    app.state.instance_id = instance_id
    return app


class UploadTooLarge(ValueError):
    pass


class BoundedMultipartParser(MultiPartParser):  # type: ignore[misc]
    # The framework's max_part_size only applies to fields without files.
    spool_max_size = 64 * 1024
    finished = False
    part_bytes = 0
    header_bytes = 0

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self.part_bytes = 0
        self.header_bytes = 0

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._count_header(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._count_header(end - start)
        super().on_header_value(data, start, end)

    def _count_header(self, size: int) -> None:
        self.header_bytes += size
        if self.header_bytes > 16_384:
            raise MultiPartException("Multipart headers exceed their size limit")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        self.part_bytes += end - start
        if self._current_part.file is not None and self.part_bytes > LIMITS.max_file_bytes:
            raise UploadTooLarge("An uploaded file exceeds the size limit")
        super().on_part_data(data, start, end)

    def on_end(self) -> None:
        self.finished = True


def _read_preview(path: Path) -> str:
    with path.open(encoding="utf-8") as stream:
        return stream.read(120_000)


def _stage_uploads(
    job: Job,
    uploads: list[tuple[str, UploadFile]],
    manifest: dict[str, tuple[str, str]],
) -> None:
    root = job.workspace / "uploads"
    total = 0
    for part, upload in uploads:
        source_id, path = manifest[part]
        destination = resolve_inside(root, f"{source_id}/{path}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with destination.open("xb") as output:
            while chunk := upload.file.read(1024 * 1024):
                written += len(chunk)
                total += len(chunk)
                if written > LIMITS.max_file_bytes or total > LIMITS.max_job_bytes:
                    raise UploadTooLarge("Upload exceeds the configured size limit")
                output.write(chunk)


def _parse_sources(value: Any) -> list[SourceSpec]:
    if not isinstance(value, list) or not 1 <= len(value) <= LIMITS.max_sources:
        raise ValueError(f"Provide between 1 and {LIMITS.max_sources} sources")
    sources: list[SourceSpec] = []
    ids: set[str] = set()
    for raw in value:
        item = _object(raw, "Source")
        source_id = validate_source_id(_string(item.get("id"), "Source ID", 64))
        kind = _string(item.get("kind"), "Source kind", 10)
        label = _string(item.get("label"), "Source label", 200).strip()
        if source_id.casefold() in ids:
            raise ValueError("Source IDs must be unique")
        if kind not in {"upload", "github", "web"}:
            raise ValueError("Unsupported source kind")
        if not label:
            raise ValueError("Every source needs a label")
        url = _string(item.get("url", ""), "Source URL", 4_096)
        ref = _string(item.get("ref", ""), "GitHub ref", 200)
        if (kind != "upload") != bool(url) or (kind != "github" and ref):
            raise ValueError("Invalid URL or ref for this source type")
        sources.append(SourceSpec(source_id, kind, label, url=url or None, ref=ref or None))
        ids.add(source_id.casefold())
    return sources


def _parse_file_manifest(value: Any, sources: list[SourceSpec]) -> dict[str, tuple[str, str]]:
    if not isinstance(value, list) or len(value) > LIMITS.max_archive_entries:
        raise ValueError("Invalid upload manifest")
    upload_ids = {source.id for source in sources if source.kind == "upload"}
    parsed: dict[str, tuple[str, str]] = {}
    files: set[str] = set()
    directories: set[str] = set()
    used_sources: set[str] = set()
    for raw in value:
        item = _object(raw, "File")
        part = _string(item.get("part"), "Upload part", 100)
        source_id = _string(item.get("source_id"), "Source ID", 64)
        relative = safe_relative_path(_string(item.get("relative_path"), "File path", 2_048))
        if not part or part == "spec" or part in parsed or source_id not in upload_ids:
            raise ValueError("Invalid or duplicate upload part")
        key = f"{source_id}/{path_key(relative)}"
        parents = {f"{source_id}/{path_key(parent)}" for parent in relative.parents}
        if key in files or key in directories or not parents.isdisjoint(files):
            raise ValueError("Upload contains conflicting file paths")
        files.add(key)
        directories.update(parents)
        used_sources.add(source_id)
        parsed[part] = (source_id, relative.as_posix())
    if upload_ids != used_sources:
        raise ValueError("Every upload source must include at least one file")
    return parsed


def _string(value: Any, label: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise ValueError(f"Invalid {label.lower()}")
    return value


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_session(request: Request, name: str, token: str) -> None:
    if not secrets.compare_digest(request.cookies.get(name, "").encode(), token.encode()):
        raise SecurityError("Invalid local session")


def _require_mutation(request: Request, name: str, cookie: str, token: str) -> None:
    _require_session(request, name, cookie)
    if not secrets.compare_digest(
        request.headers.get("x-automd-token", "").encode(), token.encode()
    ):
        raise SecurityError("Invalid request token")
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    if origin != f"http://{host}" or request.headers.get("sec-fetch-site") == "cross-site":
        raise SecurityError("Untrusted request origin")


def _job_or_none(manager: JobManager, job_id: str) -> Job | None:
    if len(job_id) > 100:
        return None
    return manager.get(job_id)


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)
