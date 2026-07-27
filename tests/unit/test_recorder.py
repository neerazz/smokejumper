"""Flight-recorder file identity and complete B8 append behavior."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from smokejumper.recorder.writer import Recorder


def test_two_recorders_in_one_process_never_share_a_file(tmp_path: Path) -> None:
    first = Recorder(tmp_path)
    second = Recorder(tmp_path)

    assert first.path != second.path


def test_sequence_is_monotonic_for_one_run(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    run_id = uuid4()

    first, _ = recorder.record(run_id=run_id, actor="test", kind="event", payload={})
    second, _ = recorder.record(run_id=run_id, actor="test", kind="transition", payload={})

    assert (first, second) == (1, 2)
