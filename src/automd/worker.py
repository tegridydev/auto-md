"""Conversion subprocess entry point. The parent owns the web session and deadlines."""

from __future__ import annotations

import json
import sys
import threading
from contextlib import redirect_stdout
from pathlib import Path

from .models import ProcessingOptions, SourceSpec
from .pipeline import Pipeline

MAX_WORKER_ADDRESS_SPACE = 4 * 1024**3


def main() -> int:
    workspace = Path(sys.argv[1])
    channel = sys.stdout

    def send(kind: str, **payload: object) -> None:
        print(json.dumps({"kind": kind, **payload}), file=channel, flush=True)

    def progress(
        event: str,
        phase: str,
        completed: int,
        total: int,
        message: str,
        source_id: str | None,
    ) -> None:
        send(
            "progress",
            event=event,
            phase=phase,
            completed=completed,
            total=total,
            message=message[:2_048],
            source_id=source_id,
        )

    try:
        _limit_memory()
        with redirect_stdout(sys.stderr):
            request = json.load(sys.stdin)
            sources = [SourceSpec(**item) for item in request["sources"]]
            options = ProcessingOptions.from_dict(request["options"])
            result = Pipeline(workspace, threading.Event(), progress).run(sources, options)
        send(
            "result",
            artifacts=[item.public() for item in result.artifacts],
            document_count=len(result.documents),
            skipped_count=len(result.skipped),
            warning_count=len(result.warnings),
        )
        return 0
    except Exception as exc:
        send("error", message=(str(exc) or type(exc).__name__)[:2_048])
        return 1


def _limit_memory() -> None:
    # A Linux address-space ceiling also covers allocations in native libraries.
    # Other platforms still enforce input budgets and parent-owned hard timeouts.
    if sys.platform != "linux":
        return
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    limits = [value for value in (soft, hard, MAX_WORKER_ADDRESS_SPACE) if value >= 0]
    limit = min(limits)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


if __name__ == "__main__":
    raise SystemExit(main())
