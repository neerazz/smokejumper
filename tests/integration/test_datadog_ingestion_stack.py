"""The Datadog path against the booted stack (SPEC 5.1, 5.2).

These run against the real deployment rather than an in-process app, because the
things most likely to be wrong are the things a unit test cannot see: whether the
secret reached the container, whether the row actually committed, whether exactly
one message reached Redis, and whether concurrent deliveries race.

Postgres and Redis are not host-published (SPEC 11.2), so assertions read them
through `docker compose exec` — the same route `test_schema_stack.py` uses.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

APP = f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '8000')}"
SECRET_VAR = "SMOKEJUMPER__WEBHOOKS__DATADOG__SECRET"

# The storm size only needs to exceed the connection pool to interleave
# transactions; 25 does, and keeps the test fast.
STORM_DELIVERIES = 25


def _compose(service: str, *command: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", service, *command],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    return result.stdout.strip()


def _scalar(sql: str) -> str:
    return _compose(
        "postgres", "psql", "-U", "smokejumper", "-d", "smokejumper", "-t", "-A", "-c", sql
    )


def _stream_length() -> int:
    return int(_compose("redis", "redis-cli", "XLEN", "agentevents") or 0)


@pytest.fixture(scope="module")
def secret() -> str:
    value = os.environ.get(SECRET_VAR, "")
    if not value:
        pytest.skip(
            f"{SECRET_VAR} must be set to the same value the app container was started with"
        )
    return value


@pytest.fixture
def delivery() -> dict[str, Any]:
    """The committed real fixture, re-keyed so each test owns its own incident.

    A fresh `alert_id` gives a fresh fingerprint, so tests do not collide with
    each other or with rows left by a previous run.
    """
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "fixtures" / "webhooks" / "datadog.json").read_text("utf-8"))
    payload["alert_id"] = f"test-{uuid.uuid4().hex[:12]}"
    return payload


def _post(payload: dict[str, Any], *, token: str | None) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Smokejumper-Token"] = token
    return httpx.post(f"{APP}/webhooks/datadog", json=payload, headers=headers, timeout=30)


def _rows_for(alert_id: str) -> tuple[int, int]:
    """`(row_count, total_deliveries)` for one monitor id."""
    raw = _scalar(
        "SELECT count(*) || ',' || coalesce(sum(dedupe_count), 0) FROM events "
        f"WHERE payload->>'source_event_key' = '{alert_id}'"
    )
    count, deliveries = raw.split(",")
    return int(count), int(deliveries)


def test_unverified_delivery_is_rejected(delivery: dict[str, Any], secret: str) -> None:
    """No token and a wrong token must both fail, and neither may persist anything."""
    assert _post(delivery, token=None).status_code == 401
    assert _post(delivery, token="wrong-token").status_code == 401

    assert _rows_for(delivery["alert_id"]) == (0, 0)


def test_a_real_alert_is_persisted_and_enqueued(delivery: dict[str, Any], secret: str) -> None:
    before = _stream_length()

    response = _post(delivery, token=secret)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["severity"] == "high", "fixture is P2"
    assert body["entities"] == [
        "env:prod",
        "region:us-east-1",
        "service:feature-store",
        "table:merchant_features",
    ]
    assert body["queue_message_id"]

    assert _rows_for(delivery["alert_id"]) == (1, 1)
    assert _stream_length() == before + 1


def test_redelivery_counts_against_the_same_incident(delivery: dict[str, Any], secret: str) -> None:
    """Exactly one ticket per fingerprint starts here: one row, one queue message."""
    assert _post(delivery, token=secret).json()["status"] == "accepted"
    after_first = _stream_length()

    second = _post(delivery, token=secret).json()

    assert second["status"] == "duplicate"
    assert second["dedupe_count"] == 2
    assert _rows_for(delivery["alert_id"]) == (1, 2)
    assert _stream_length() == after_first, "a duplicate must not enqueue"


def test_concurrent_deliveries_do_not_race(delivery: dict[str, Any], secret: str) -> None:
    """The storm case, which is the one an unsynchronized check gets wrong.

    Deliveries of the same alert genuinely arrive in parallel. Without the
    advisory lock in `repository.admit`, several transactions see no open event
    and each insert one, which is two tickets for one incident.
    """
    before = _stream_length()

    with ThreadPoolExecutor(max_workers=STORM_DELIVERIES) as pool:
        codes = [
            future.result().status_code
            for future in [
                pool.submit(_post, delivery, token=secret) for _ in range(STORM_DELIVERIES)
            ]
        ]

    assert codes == [202] * STORM_DELIVERIES
    assert _rows_for(delivery["alert_id"]) == (1, STORM_DELIVERIES)
    assert _stream_length() == before + 1, "exactly one investigation, not one per delivery"


def test_recovery_closes_the_window_so_a_retrigger_is_new(
    delivery: dict[str, Any], secret: str
) -> None:
    assert _post(delivery, token=secret).json()["status"] == "accepted"

    recovery = _post({**delivery, "alert_transition": "Recovered"}, token=secret).json()
    assert recovery["status"] == "recovered"
    assert recovery["windows_closed"] == 1

    retrigger = _post(delivery, token=secret).json()

    assert retrigger["status"] == "accepted", "a re-trigger after recovery is a new incident"
    rows, _ = _rows_for(delivery["alert_id"])
    assert rows == 2


def test_an_unnormalizable_body_is_quarantined_not_dropped(secret: str) -> None:
    """A payload with no monitor id has no stable identity, so it cannot be an event.

    It still leaves a row, because an operator needs to see that something arrived
    and was rejected.
    """
    before = int(_scalar("SELECT count(*) FROM events WHERE quarantined = true"))

    response = _post({"title": "no monitor id"}, token=secret)

    assert response.status_code == 202
    assert response.json()["status"] == "quarantined"
    assert "alert_id" in response.json()["reason"]
    assert int(_scalar("SELECT count(*) FROM events WHERE quarantined = true")) == before + 1
