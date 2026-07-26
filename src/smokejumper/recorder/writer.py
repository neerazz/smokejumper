"""Append-only JSONL flight recorder (SPEC 5.8, ADR-0012).

The audit record is the source of truth, so this writes files, not rows. Postgres
holds only the byte offsets that let replay find a run without scanning every
file.

One file per process start, named `audit-<date>T<time>.jsonl`, because two
processes appending to one file interleave partial lines under concurrent writes
and a torn line is an unparseable audit record.

Writes are synchronous and flushed. Buffering would make the recorder lose
exactly the events an operator needs most: the ones written immediately before a
crash.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from smokejumper.contracts.audit import AuditEvent


class Recorder:
    """Owns one JSONL file and the per-run sequence counters."""

    def __init__(self, log_dir: Path) -> None:
        self._dir = log_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H%M%S")
        self.path = self._dir / f"audit-{stamp}-{os.getpid()}.jsonl"
        # A lock rather than an async primitive: the write itself is blocking, and
        # the critical section is one append. Holding a threading lock across it
        # keeps `seq` and the byte offset consistent with what actually landed.
        self._lock = threading.Lock()
        self._seq: dict[str, int] = {}
        self.failures = 0
        self.path.touch()

    def append(self, event: AuditEvent) -> tuple[int, int]:
        """Write one event. Returns `(seq, end_offset)`.

        A failure is counted and re-raised rather than swallowed: SPEC 5.8 makes
        this the source of truth, so a silent write failure would leave the system
        claiming an audit trail it does not have.
        """
        with self._lock:
            run = str(event.run_id)
            seq = self._seq.get(run, 0) + 1
            self._seq[run] = seq
            line = event.model_copy(update={"seq": seq}).model_dump_json() + "\n"
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
                    os.fsync(handle.fileno())
                    return seq, handle.tell()
            except OSError:
                self.failures += 1
                raise

    def start_offset(self) -> int:
        """Current end of file, i.e. where the next run's events will begin."""
        return self.path.stat().st_size

    def record(
        self,
        *,
        run_id: UUID,
        actor: str,
        kind: str,
        payload: dict[str, Any],
    ) -> tuple[int, int]:
        """Convenience wrapper that builds the AuditEvent."""
        return self.append(
            AuditEvent(
                run_id=run_id,
                seq=1,  # replaced by append(); the counter is the recorder's job
                ts=datetime.now(tz=UTC),
                actor=actor,
                kind=kind,  # type: ignore[arg-type]
                payload=payload,
            )
        )

    def read_run(self, run_id: UUID) -> list[dict[str, Any]]:
        """Every recorded line for one run, in order. Used by tests and replay."""
        wanted = str(run_id)
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("run_id") == wanted:
                    out.append(record)
        return out
