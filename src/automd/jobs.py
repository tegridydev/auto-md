from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from .config import LIMITS, MAX_WORKER_MESSAGE
from .models import (
    Artifact,
    JobCancelled,
    JobStatus,
    ProcessingOptions,
    ProgressEvent,
    SourceSpec,
)
from .security import resolve_inside, safe_relative_path

logger = logging.getLogger(__name__)
_ACTIVE = {JobStatus.QUEUED, JobStatus.RUNNING}
_MAX_RETAINED_JOBS = 4
_WORKER_BOOTSTRAP = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from automd.worker import main; raise SystemExit(main())"
)
_WORKER_ENV_KEYS = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "SYSTEMDRIVE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LD_LIBRARY_PATH",
}


class BusyError(RuntimeError):
    pass


@dataclass(slots=True)
class Job:
    id: str
    workspace: Path
    sources: list[SourceSpec]
    options: ProcessingOptions
    status: JobStatus = JobStatus.QUEUED
    message: str = "Queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    events: list[ProgressEvent] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    document_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future[None] | None = None
    delete_requested: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def emit(
        self,
        event: str,
        phase: str,
        completed: int,
        total: int,
        message: str,
        source_id: str | None,
    ) -> None:
        with self._lock:
            sequence = self.events[-1].sequence + 1 if self.events else 1
            self.events.append(
                ProgressEvent(sequence, event, phase, completed, total, message, source_id)
            )
            if len(self.events) > 2_000:
                self.events = self.events[-1_000:]
            self.message = message
            self.updated_at = time.time()

    def events_after(self, sequence: int) -> list[ProgressEvent]:
        with self._lock:
            return [event for event in self.events if event.sequence > sequence]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "message": self.message,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "document_count": self.document_count,
                "skipped_count": self.skipped_count,
                "warning_count": self.warning_count,
                "error": self.error,
                "artifacts": [artifact.public() for artifact in self.artifacts],
            }


class JobManager:
    def __init__(self) -> None:
        self.session_root = Path(tempfile.mkdtemp(prefix="automd-"))
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="automd-worker")

    def check_capacity(self) -> None:
        with self._lock:
            if sum(job.status in _ACTIVE for job in self._jobs.values()) >= 2:
                raise BusyError("Auto-MD already has two active or queued jobs")
            if len(self._jobs) >= _MAX_RETAINED_JOBS:
                raise BusyError("Delete a previous job before starting another conversion")

    def create(self, sources: list[SourceSpec], options: ProcessingOptions) -> Job:
        with self._lock:
            self.check_capacity()
            job_id = secrets.token_urlsafe(18)
            workspace = self.session_root / job_id
            workspace.mkdir(mode=0o700)
            job = Job(job_id, workspace, sources, options)
            self._jobs[job_id] = job
            return job

    def start(self, job: Job) -> None:
        with self._lock:
            job.future = self._executor.submit(self._run, job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job:
            with job._lock:
                if job.status in _ACTIVE and not job.cancel_event.is_set():
                    job.cancel_event.set()
                    job.emit("progress", "cancelling", 0, 1, "Cancelling…", None)
        return job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in _ACTIVE and job.future is not None:
                job.delete_requested = True
                job.cancel_event.set()
                return True
            self._jobs.pop(job_id, None)
        shutil.rmtree(job.workspace, ignore_errors=True)
        return True

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        shutil.rmtree(self.session_root, ignore_errors=True)

    def _run(self, job: Job) -> None:
        try:
            with job._lock:
                if job.cancel_event.is_set():
                    raise JobCancelled
                job.status = JobStatus.RUNNING
                job.emit("progress", "starting", 0, 1, "Starting conversion", None)
            result = _run_worker(job)
            with job._lock:
                if job.cancel_event.is_set():
                    raise JobCancelled
                self._apply_result(job, result)
        except JobCancelled:
            with job._lock:
                job.status = JobStatus.CANCELLED
                job.emit("cancelled", "cancelled", 1, 1, "Conversion cancelled", None)
        except (ValueError, OSError, RuntimeError) as exc:
            with job._lock:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                job.emit("failed", "failed", 1, 1, f"Conversion failed: {exc}", None)
        except Exception:
            logger.exception("Unexpected conversion failure")
            with job._lock:
                job.status = JobStatus.FAILED
                job.error = "Unexpected conversion failure"
                job.emit("failed", "failed", 1, 1, job.error, None)
        finally:
            for directory in ("uploads", "remote", "expanded"):
                shutil.rmtree(job.workspace / directory, ignore_errors=True)
            if not job.artifacts:
                shutil.rmtree(job.workspace / "output", ignore_errors=True)
            if job.delete_requested:
                with self._lock:
                    self._jobs.pop(job.id, None)
                shutil.rmtree(job.workspace, ignore_errors=True)

    def _apply_result(self, job: Job, result: dict[str, Any]) -> None:
        job.document_count = _result_count(result, "document_count")
        job.skipped_count = _result_count(result, "skipped_count")
        job.warning_count = _result_count(result, "warning_count")
        job.artifacts = _result_artifacts(job.workspace / "output", result)
        job.status = (
            JobStatus.COMPLETED_WITH_WARNINGS
            if job.skipped_count or job.warning_count
            else JobStatus.COMPLETED
        )
        job.emit(
            "complete", "complete", 1, 1, f"Ready — {job.document_count} documents processed", None
        )


def _run_worker(job: Job) -> dict[str, Any]:
    request = json.dumps(
        {
            "sources": [asdict(source) for source in job.sources],
            "options": asdict(job.options),
        }
    ).encode()
    env = {key: value for key, value in os.environ.items() if key.upper() in _WORKER_ENV_KEYS}
    env.update(
        {
            "OPENBLAS_NUM_THREADS": "2",
            "OMP_NUM_THREADS": "2",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    command = [
        sys.executable,
        "-P",
        "-c",
        _WORKER_BOOTSTRAP,
        str(Path(__file__).resolve().parents[1]),
        str(job.workspace),
    ]
    started = last_progress = time.monotonic()
    result: dict[str, Any] = {}
    error: str | None = None

    def receive(message: dict[str, Any]) -> None:
        nonlocal last_progress, result, error
        if message.get("kind") == "progress":
            last_progress = time.monotonic()
            with job._lock:
                if not job.cancel_event.is_set():
                    job.emit(
                        message["event"],
                        message["phase"],
                        message["completed"],
                        message["total"],
                        message["message"],
                        message["source_id"],
                    )
        elif message.get("kind") == "result":
            result = message
        elif message.get("kind") == "error":
            error = str(message.get("message") or "Conversion worker failed")[:2_048]
        else:
            raise ValueError("Unexpected worker message")

    # File-backed stdin avoids blocking on a pipe if worker startup fails before reading.
    with tempfile.TemporaryFile(dir=job.workspace) as config:
        config.write(request)
        config.seek(0)
        with subprocess.Popen(
            command,
            stdin=config,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=job.workspace,
            env=env,
        ) as process:
            assert process.stdout is not None
            protocol_error = threading.Event()
            reader = threading.Thread(
                target=_read_worker,
                args=(process.stdout, receive, protocol_error),
                daemon=True,
            )
            reader.start()
            try:
                while process.poll() is None:
                    if job.cancel_event.wait(0.05):
                        raise JobCancelled
                    if protocol_error.is_set():
                        raise ValueError("Invalid conversion worker response")
                    now = time.monotonic()
                    if (
                        now - started > LIMITS.max_job_seconds
                        or now - last_progress > LIMITS.max_operation_seconds
                    ):
                        raise ValueError("Conversion exceeded its time limit")
            finally:
                if process.poll() is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                process.wait()
                reader.join()
            if job.cancel_event.is_set():
                raise JobCancelled
            if protocol_error.is_set():
                raise ValueError("Invalid conversion worker response")
            if process.returncode != 0 or not result:
                raise ValueError(
                    error or "Conversion worker stopped. Try a smaller input or disable OCR."
                )
    return result


def _read_worker(
    stream: BinaryIO,
    receive: Callable[[dict[str, Any]], None],
    failed: threading.Event,
) -> None:
    try:
        while line := stream.readline(MAX_WORKER_MESSAGE + 1):
            if len(line) > MAX_WORKER_MESSAGE:
                raise ValueError("Worker message exceeded its size limit")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Invalid worker message")
            receive(message)
    except (ValueError, KeyError, TypeError, OSError, RecursionError):
        failed.set()


def _result_count(result: dict[str, Any], key: str) -> int:
    count = result.get(key)
    if not isinstance(count, int) or count < 0:
        raise ValueError("Invalid worker result count")
    return count


def _result_artifacts(output: Path, result: dict[str, Any]) -> list[Artifact]:
    items = result.get("artifacts")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise ValueError("Invalid worker artifact list")
    item = items[0]
    name, artifact_id, checksum, media_type = (
        item.get(key) for key in ("name", "id", "sha256", "media_type")
    )
    if (
        not isinstance(name, str)
        or not isinstance(artifact_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", artifact_id)
        or not isinstance(checksum, str)
        or not re.fullmatch(r"[0-9a-f]{64}", checksum)
        or media_type not in ("text/markdown", "application/zip")
    ):
        raise ValueError("Invalid worker artifact")
    relative = safe_relative_path(name)
    if len(relative.parts) != 1:
        raise ValueError("Invalid worker artifact name")
    path = resolve_inside(output, relative)
    if output.is_symlink() or (output / name).is_symlink() or not path.is_file():
        raise ValueError("Conversion did not produce an artifact")
    return [Artifact(artifact_id, name, media_type, path, path.stat().st_size, checksum)]
