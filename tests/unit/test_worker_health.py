"""A dead worker must be visible (SPEC 5.7).

The failure this guards is the quietest one the system has: the worker stops, the
API keeps returning 202, the queue keeps growing, and nothing investigates. If
`/healthz` does not report it, an orchestrator cannot restart the container and
an operator finds out from the backlog.
"""

from __future__ import annotations

import asyncio

import pytest

from smokejumper.worker import WorkerHandle


async def test_a_running_worker_is_ok() -> None:
    task = asyncio.create_task(asyncio.sleep(60))
    try:
        assert WorkerHandle(task).status() == "ok"
    finally:
        task.cancel()


async def test_a_crashed_worker_names_the_exception() -> None:
    """The reason matters: 'dead' alone does not tell an operator where to look."""

    async def boom() -> None:
        raise RuntimeError("redis went away")

    task = asyncio.create_task(boom())
    await asyncio.sleep(0)  # let it run and fail
    with pytest.raises(RuntimeError):
        await task

    assert WorkerHandle(task).status() == "dead: RuntimeError"


async def test_a_cancelled_worker_is_dead_not_ok() -> None:
    """Shutdown cancels the task; during shutdown the app must not claim health."""

    async def forever() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(forever())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert WorkerHandle(task).status() == "dead: cancelled"


async def test_a_worker_that_returns_is_still_dead() -> None:
    """The loop is supposed to run forever; returning cleanly is still a stop."""

    async def exits() -> None:
        return None

    task = asyncio.create_task(exits())
    await task

    assert WorkerHandle(task).status() == "dead: exited"
