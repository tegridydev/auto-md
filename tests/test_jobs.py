import time
from dataclasses import replace

import pytest

from automd import jobs
from automd.jobs import JobManager
from automd.models import JobStatus, ProcessingOptions


@pytest.mark.parametrize("cancel", [False, True])
def test_worker_stops_and_removes_input_on_timeout_or_cancel(monkeypatch, cancel: bool) -> None:
    monkeypatch.setattr(jobs, "_WORKER_BOOTSTRAP", "import time; time.sleep(30)")
    if not cancel:
        monkeypatch.setattr(jobs, "LIMITS", replace(jobs.LIMITS, max_operation_seconds=1))
    manager = JobManager()
    try:
        job = manager.create([], ProcessingOptions())
        uploads = job.workspace / "uploads"
        uploads.mkdir()
        (uploads / "note.txt").write_text("test data", encoding="utf-8")
        manager.start(job)
        assert job.future is not None
        if cancel:
            deadline = time.monotonic() + 2
            while job.status == JobStatus.QUEUED and time.monotonic() < deadline:
                time.sleep(0.01)
            assert job.status == JobStatus.RUNNING
            manager.cancel(job.id)
        job.future.result(timeout=5)
        assert job.status == (JobStatus.CANCELLED if cancel else JobStatus.FAILED)
        if not cancel:
            assert job.error == "Conversion exceeded its time limit"
        assert not uploads.exists()
    finally:
        manager.shutdown()
