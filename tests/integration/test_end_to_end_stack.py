"""Alert in, conclusion and ticket out (SPEC 6.1).

The tests that matter most, because they are the only ones that fail if the
system accepts an alert and then does nothing with it. Everything else verifies a
component; these verify the product.

Run against the booted stack: the worker lives in the app container, so an
in-process test would exercise a pipeline nobody deploys.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

APP = f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '8000')}"
SECRET_VAR = "SMOKEJUMPER__WEBHOOKS__DATADOG__SECRET"
ROOT = Path(__file__).resolve().parents[2]

# The worker polls with a 2s block, so a run appears within a few seconds. Poll
# rather than sleep a fixed interval: a fixed sleep is either flaky or slow.
SETTLE_TIMEOUT = 25.0


def _compose(service: str, *command: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", service, *command],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return result.stdout.strip()


def _scalar(sql: str) -> str:
    return _compose(
        "postgres", "psql", "-U", "smokejumper", "-d", "smokejumper", "-t", "-A", "-c", sql
    )


@pytest.fixture(scope="module")
def secret() -> str:
    value = os.environ.get(SECRET_VAR, "")
    if not value:
        pytest.skip(f"{SECRET_VAR} must match the value the app container was started with")
    return value


@pytest.fixture
def delivery() -> dict[str, Any]:
    payload = json.loads((ROOT / "fixtures" / "webhooks" / "datadog.json").read_text("utf-8"))
    payload["alert_id"] = f"e2e-{uuid.uuid4().hex[:12]}"
    return payload


def _post(payload: dict[str, Any], token: str) -> httpx.Response:
    return httpx.post(
        f"{APP}/webhooks/datadog",
        json=payload,
        headers={"X-Smokejumper-Token": token},
        timeout=30,
    )


def _await_run(fingerprint: str) -> dict[str, Any]:
    """Poll until the worker has concluded this incident, or fail with why."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    last = None
    while time.monotonic() < deadline:
        response = httpx.get(f"{APP}/runs/{fingerprint}", timeout=10)
        if response.status_code == 200:
            last = response.json()
            if last["status"] == "concluded":
                return last
        time.sleep(0.5)
    pytest.fail(f"no concluded run for {fingerprint} within {SETTLE_TIMEOUT}s; last={last}")


def _await_queue_idle() -> None:
    """Wait until the consumer group has neither lag nor pending work."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        groups = json.loads(
            _compose("redis", "redis-cli", "--json", "XINFO", "GROUPS", "agentevents")
        )
        latest = next(group for group in groups if group["name"] == "intelligence")
        if int(latest.get("lag", 0)) == 0 and int(latest.get("pending", 0)) == 0:
            return
        time.sleep(0.25)
    pytest.fail(f"queue did not become idle; last group state={latest}")


def test_an_alert_becomes_a_conclusion_and_a_ticket(delivery: dict[str, Any], secret: str) -> None:
    """The whole product in one test."""
    accepted = _post(delivery, secret).json()
    assert accepted["status"] == "accepted"

    run = _await_run(accepted["fingerprint"])

    # A real conclusion, not a placeholder.
    assert run["conclusion_status"] == "needs_human", "P2 severity must escalate"
    assert run["confidence"] == 0.9
    assert run["ticket"], "an incident must produce a ticket"
    assert run["ticket_updates"] == 0, "first delivery opens, it does not update"

    # Grounded: every finding cites the alert, and the summary carries the detail
    # an on-call person needs before opening anything else.
    agents = {f["agent"] for f in run["findings"]}
    assert agents == {"receiver", "triage"}
    assert "merchant_features" in run["summary_md"]
    assert "feature_store.online_table.hours_since_update" in run["summary_md"]
    # It says what it could NOT determine, rather than implying a root cause.
    assert any("no root cause determined" in f["hypothesis"] for f in run["findings"])
    assert run["proposed_actions"]

    # Replayable: the audit range is real and non-empty.
    assert run["audit"]["file"].endswith(".jsonl")
    assert run["audit"]["end_offset"] > run["audit"]["start_offset"]


def test_the_audit_trail_records_the_whole_run(delivery: dict[str, Any], secret: str) -> None:
    """Every stage leaves a record, in order, under one run id."""
    accepted = _post(delivery, secret).json()
    run = _await_run(accepted["fingerprint"])

    lines = _compose("app", "sh", "-c", f"cat /app/logs/{run['audit']['file']}")
    records = [
        json.loads(line)
        for line in lines.splitlines()
        if line.strip() and json.loads(line)["run_id"] == run["run_id"]
    ]

    assert [r["kind"] for r in records] == ["event", "transition", "action"]
    assert [r["seq"] for r in records] == [1, 2, 3], "seq is monotonic per run"
    recorded_event = records[0]["payload"]["event"]
    assert recorded_event["schema_version"] == 1
    assert recorded_event["fingerprint"] == accepted["fingerprint"]
    assert recorded_event["raw"]["alert_id"] == delivery["alert_id"]
    assert records[-1]["payload"]["ticket"] == run["ticket"]


def test_queue_redelivery_reuses_the_run_and_suppresses_the_action(
    delivery: dict[str, Any], secret: str
) -> None:
    """A crash after the action commit but before XACK must not update twice."""
    accepted = _post(delivery, secret).json()
    first_run = _await_run(accepted["fingerprint"])
    event_id = accepted["event_id"]
    payload = _scalar(f"SELECT payload::text FROM events WHERE id = '{event_id}'")

    # Recreate the durable state left by a process death after Actions committed
    # but before the run/audit close. The ticket_actions receipt remains.
    _scalar(
        "UPDATE runs SET status = 'running', conclusion = NULL, finished_at = NULL, "
        f"audit_end_offset = NULL WHERE run_id = '{event_id}' RETURNING status"
    )

    _compose("redis", "redis-cli", "XADD", "agentevents", "*", "event", payload)
    _await_queue_idle()

    assert int(_scalar(f"SELECT count(*) FROM runs WHERE run_id = '{event_id}'")) == 1
    assert int(_scalar(f"SELECT count(*) FROM ticket_actions WHERE run_id = '{event_id}'")) == 1
    assert _scalar(f"SELECT status FROM runs WHERE run_id = '{event_id}'") == "concluded"
    assert (
        int(
            _scalar(
                "SELECT update_count FROM tickets "
                f"WHERE fingerprint = '{accepted['fingerprint']}' AND closed_at IS NULL"
            )
        )
        == 0
    )
    replayed_run = _await_run(accepted["fingerprint"])
    assert replayed_run["audit"]["start_offset"] > first_run["audit"]["start_offset"]
    lines = _compose("app", "sh", "-c", f"cat /app/logs/{replayed_run['audit']['file']}")
    actions = [
        json.loads(line)
        for line in lines.splitlines()
        if line.strip()
        and json.loads(line)["run_id"] == event_id
        and json.loads(line)["kind"] == "action"
    ]
    assert actions[-1]["payload"]["replayed"] is True


def test_one_ticket_per_incident_under_concurrency(delivery: dict[str, Any], secret: str) -> None:
    """20 simultaneous deliveries of one alert must file exactly one ticket.

    This is the product's headline promise. It has two independent guards: the
    Receiver's advisory lock collapses the deliveries into one event, and the
    partial unique index on open tickets collapses any surviving concurrency at
    the action stage.
    """
    fingerprint_before = int(_scalar("SELECT count(*) FROM tickets"))

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = [
            f.result().status_code
            for f in [pool.submit(_post, delivery, secret) for _ in range(20)]
        ]
    assert codes == [202] * 20

    accepted_fp = _post(delivery, secret).json()["fingerprint"]
    run = _await_run(accepted_fp)

    assert int(_scalar("SELECT count(*) FROM tickets")) == fingerprint_before + 1
    assert int(_scalar(f"SELECT count(*) FROM runs WHERE fingerprint = '{accepted_fp}'")) == 1, (
        "one run per incident, not one per delivery"
    )
    assert run["ticket"]
