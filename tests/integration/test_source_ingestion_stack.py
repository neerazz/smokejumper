"""The four non-Datadog sources against the booted stack (SPEC 5.1, 5.2).

`test_datadog_ingestion_stack.py` proves the receiver's storage and dedupe
behaviour in detail and is not repeated here. What these tests cover is what
only appears once there is more than one source: per-source verification
schemes, batch deliveries where one POST carries several independent incidents,
and the fact that each source actually reaches a ticket rather than stopping at
an accepted row.

They assert through the HTTP surface — `POST /webhooks/...` then
`GET /runs/{fingerprint}` — because that is the path an operator has, and a test
that read the database directly could pass while the read path was broken.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration

APP = f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '8000')}"

# How long the worker gets to pick an event off the stream and conclude it. The
# work is deterministic triage with no model call, so this is generous.
CONCLUSION_TIMEOUT_SECONDS = 30.0


def _secret(source: str) -> str:
    variable = f"SMOKEJUMPER__WEBHOOKS__{source.upper()}__SECRET"
    value = os.environ.get(variable, "")
    if not value:
        pytest.skip(f"{variable} must match the value the app container was started with")
    return value


@pytest.fixture(scope="module")
def pagerduty_secret() -> str:
    return _secret("pagerduty")


@pytest.fixture(scope="module")
def grafana_secret() -> str:
    return _secret("grafana")


@pytest.fixture(scope="module")
def generic_secret() -> str:
    return _secret("generic")


@pytest.fixture
def unique() -> str:
    """A per-test suffix, so incidents never collide across tests or reruns."""
    return uuid.uuid4().hex[:12]


def _post(path: str, payload: dict[str, Any], **headers: str) -> httpx.Response:
    return httpx.post(f"{APP}{path}", json=payload, headers=headers, timeout=30)


def _signed_post(path: str, payload: dict[str, Any], *, secret: str) -> httpx.Response:
    """Sign the exact bytes sent, which is what the server verifies."""
    body = json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return httpx.post(
        f"{APP}{path}",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Smokejumper-Signature": f"sha256={digest}",
        },
        timeout=30,
    )


def _await_conclusion(fingerprint: str) -> dict[str, Any]:
    """Poll the operator read path until the run concludes, or fail loudly."""
    deadline = time.monotonic() + CONCLUSION_TIMEOUT_SECONDS
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = httpx.get(f"{APP}/runs/{fingerprint}", timeout=15)
        if response.status_code == 200:
            latest = response.json()
            if latest.get("status") == "concluded" and latest.get("ticket"):
                return latest
        time.sleep(0.25)
    pytest.fail(
        f"no concluded run for {fingerprint} "
        f"within {CONCLUSION_TIMEOUT_SECONDS}s; last seen: {latest}"
    )


# --- PagerDuty -------------------------------------------------------------


def _pagerduty(unique: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": f"PD{unique.upper()}",
        "incident_key": f"it-pd-{unique}",
        "created_at": "2026-07-26T18:29:41Z",
        "title": "online table lag above 15m",
        "service": {"summary": "feature-store", "type": "service_reference"},
        "priority": {"summary": "P2"},
        "urgency": "high",
        "body": {"details": "lag is 22 minutes and climbing"},
    }
    data.update(overrides)
    return {"event": {"event_type": "incident.triggered", "data": data}}


def test_pagerduty_without_the_token_is_rejected(unique: str, pagerduty_secret: str) -> None:
    payload = _pagerduty(unique)

    assert _post("/webhooks/pagerduty", payload).status_code == 401
    assert (
        _post("/webhooks/pagerduty", payload, **{"X-Smokejumper-Token": "wrong"}).status_code == 401
    )
    # Rejected before persistence, so there is nothing to find afterwards.
    assert httpx.get(f"{APP}/runs/{unique}", timeout=15).status_code == 404


def test_a_pagerduty_incident_reaches_a_ticket(unique: str, pagerduty_secret: str) -> None:
    response = _post(
        "/webhooks/pagerduty", _pagerduty(unique), **{"X-Smokejumper-Token": pagerduty_secret}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processed"
    (result,) = body["results"]
    assert result["status"] == "accepted"
    assert result["severity"] == "high", "P2"

    run = _await_conclusion(result["fingerprint"])

    assert run["ticket"]
    assert run["conclusion_status"]
    assert run["audit"]["end_offset"] > run["audit"]["start_offset"], "the run left evidence"


def test_a_pagerduty_redelivery_does_not_open_a_second_ticket(
    unique: str, pagerduty_secret: str
) -> None:
    """PagerDuty retries, and `incident_key` is what makes a retry the same incident."""
    token = {"X-Smokejumper-Token": pagerduty_secret}
    first = _post("/webhooks/pagerduty", _pagerduty(unique), **token).json()["results"][0]
    _await_conclusion(first["fingerprint"])

    # A different incident object for the same condition, which is what the
    # second delivery of a re-triggered incident looks like.
    second = _post("/webhooks/pagerduty", _pagerduty(unique, id="PDOTHER"), **token).json()[
        "results"
    ][0]

    assert second["status"] == "duplicate"
    assert second["fingerprint"] == first["fingerprint"]


# --- Grafana / Alertmanager ------------------------------------------------


def _alert(fingerprint: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "firing",
        "fingerprint": fingerprint,
        "startsAt": "2026-07-26T18:25:03Z",
        "labels": {
            "alertname": "OnlineTableLag",
            "severity": "critical",
            "service": "feature-store",
            "table": "merchant_features",
        },
        "annotations": {"description": "lag is 22 minutes"},
    }
    payload.update(overrides)
    return payload


def test_grafana_without_the_token_is_rejected(unique: str, grafana_secret: str) -> None:
    assert _post("/webhooks/grafana", {"alerts": [_alert(unique)]}).status_code == 401


def test_a_grafana_batch_becomes_one_ticket_per_alert(unique: str, grafana_secret: str) -> None:
    """One POST, several unrelated failures, and a resolved one mixed in.

    This is the case a single-event receiver gets wrong: it either files one
    ticket for the whole batch, or investigates the resolved alert.
    """
    payload = {
        "receiver": "smokejumper",
        "status": "firing",
        "alerts": [
            _alert(
                f"it-graf-a-{unique}",
                labels={"alertname": "OnlineTableLag", "severity": "critical", "table": "t1"},
            ),
            _alert(
                f"it-graf-b-{unique}",
                labels={"alertname": "OnlineTableLag", "severity": "warning", "table": "t2"},
            ),
            _alert(f"it-graf-c-{unique}", status="resolved"),
        ],
    }

    body = _post("/webhooks/grafana", payload, **{"X-Smokejumper-Token": grafana_secret}).json()

    assert body["count"] == 2, "the resolved alert must not be investigated"
    assert [result["severity"] for result in body["results"]] == ["critical", "medium"]

    tickets = {_await_conclusion(result["fingerprint"])["ticket"] for result in body["results"]}

    assert len(tickets) == 2, "two independent failures must not share a ticket"


def test_a_fully_resolved_grafana_batch_is_ignored(unique: str, grafana_secret: str) -> None:
    payload = {"alerts": [_alert(f"it-graf-r-{unique}", status="resolved")]}

    body = _post("/webhooks/grafana", payload, **{"X-Smokejumper-Token": grafana_secret}).json()

    assert body["status"] == "ignored"


def test_alertmanager_is_admitted_by_network_and_reaches_a_ticket(unique: str) -> None:
    """Alertmanager sends no credential, so the peer address is the credential.

    The stack must be started with an allowlist covering the compose bridge; if
    it is not, this fails rather than skipping, because a silently absent
    allowlist is the failure mode worth catching.
    """
    payload = {
        "receiver": "smokejumper",
        "status": "firing",
        "alerts": [
            _alert(
                f"it-am-{unique}",
                labels={
                    "alertname": "HighErrorRate",
                    "severity": "critical",
                    "service": "checkout",
                    "env": "prod",
                },
            )
        ],
    }

    response = _post("/webhooks/alertmanager", payload)

    assert response.status_code == 202, (
        "set SMOKEJUMPER__WEBHOOKS__ALERTMANAGER_ALLOWLIST to the compose bridge network"
    )
    (result,) = response.json()["results"]
    run = _await_conclusion(result["fingerprint"])

    assert run["ticket"]


# --- generic ---------------------------------------------------------------


def test_the_generic_endpoint_requires_a_valid_signature(unique: str, generic_secret: str) -> None:
    payload = {"event_id": f"it-generic-{unique}", "title": "canary failed"}

    assert _post("/webhooks/generic", payload).status_code == 401
    assert (
        httpx.post(
            f"{APP}/webhooks/generic",
            json=payload,
            headers={"X-Smokejumper-Signature": "sha256=" + "0" * 64},
            timeout=30,
        ).status_code
        == 401
    )


def test_a_signed_generic_event_reaches_a_ticket(unique: str, generic_secret: str) -> None:
    payload = {
        "event_id": f"it-generic-{unique}",
        "severity": "critical",
        "title": "canary failed",
        "body": "error rate 12% over 5m",
        "entities": [{"type": "service", "id": "checkout"}, {"type": "env", "id": "prod"}],
    }

    response = _signed_post("/webhooks/generic", payload, secret=generic_secret)

    assert response.status_code == 202
    (result,) = response.json()["results"]
    assert result["severity"] == "critical"

    run = _await_conclusion(result["fingerprint"])

    assert run["ticket"]
    assert run["conclusion_status"] in {"needs_human", "inconclusive"}, (
        "triage must never claim a root cause it did not find"
    )


def test_an_unnormalizable_body_is_quarantined_not_a_server_error(
    unique: str, generic_secret: str
) -> None:
    """A malformed delivery must not surface as a 500 the sender will retry forever."""
    response = _signed_post("/webhooks/generic", {"title": "no id"}, secret=generic_secret)

    assert response.status_code == 202
    assert response.json()["status"] == "quarantined"


def test_the_stack_is_still_healthy_afterwards() -> None:
    """Whatever the sources did, the worker must still be alive and the queue drained."""
    body = httpx.get(f"{APP}/healthz", timeout=15).json()

    assert body["status"] == "ok"
    assert body["worker"] == "ok"
    assert body["recorder_write_failures"] == 0
