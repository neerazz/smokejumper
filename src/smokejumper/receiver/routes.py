"""Inbound webhook routes (SPEC 5.1).

One route per HTTP source. Datadog is implemented; the other sources named in
SPEC 5.1 arrive with their own normalizers rather than being stubbed here, because
a route that accepts a payload it cannot normalize would return 202 and drop it.

Status codes are deliberate and are part of the contract with the sender:

- **401** unverifiable. Datadog does not retry on 4xx, which is correct: a bad
  token is a configuration error, and retrying would only repeat it.
- **202** accepted, including for a duplicate and for a recovery. The sender's
  job is done in all three cases, and 202 rather than 200 because the
  investigation has not happened yet.
- **202** for an unparseable body too, with a quarantine row. A 400 would make
  Datadog surface a delivery failure the operator cannot fix from Datadog's side,
  while the quarantine row puts it somewhere they can actually see it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from ipaddress import IPv4Network, IPv6Network
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from smokejumper.contracts.events import AgentEvent
from smokejumper.queue import producer
from smokejumper.receiver import repository
from smokejumper.receiver.normalizers import datadog, sources
from smokejumper.receiver.verification import (
    verify_hmac_signature,
    verify_shared_token,
    verify_source_ip,
)

logger = logging.getLogger(__name__)


async def _admit_and_enqueue(
    *,
    engine: AsyncEngine,
    redis: Redis,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    """Persist and enqueue a batch, one incident at a time.

    Grafana and Alertmanager deliver several alerts per POST and each is its own
    incident, so dedupe and enqueue are per event rather than per request. One
    duplicate in a batch must not suppress its siblings.
    """
    results: list[dict[str, Any]] = []
    for event in events:
        async with engine.begin() as connection:
            admission = await repository.admit(connection, event)
        if admission.is_duplicate:
            results.append(
                {
                    "status": "duplicate",
                    "fingerprint": admission.fingerprint,
                    "dedupe_count": admission.dedupe_count,
                }
            )
            continue
        message_id = await producer.publish(redis, event)
        results.append(
            {
                "status": "accepted",
                "event_id": admission.event_id,
                "fingerprint": admission.fingerprint,
                "severity": event.severity.value,
                "queue_message_id": message_id,
            }
        )
    return results


def build_router(
    *,
    engine: AsyncEngine,
    redis: Redis,
    datadog_secret: str,
    source_secrets: dict[str, str] | None = None,
    alertmanager_allowlist: Sequence[IPv4Network | IPv6Network] = (),
) -> APIRouter:
    """Routes bound to their dependencies.

    Dependencies are injected rather than resolved from module state so a test can
    point the route at a throwaway database and a fake Redis.
    """
    router = APIRouter(prefix="/webhooks", tags=["webhooks"])

    @router.post("/datadog", status_code=status.HTTP_202_ACCEPTED)
    async def datadog_webhook(request: Request, response: Response) -> dict[str, Any]:
        # No raw-body read here: Datadog's scheme is a header token, not a body
        # signature (see verification.py). A source with a real HMAC must read
        # `await request.body()` and verify those exact bytes before parsing.
        received_at = datetime.now(tz=UTC)

        if not verify_shared_token(request.headers, secret=datadog_secret):
            logger.warning("rejected unverified datadog delivery")
            response.status_code = status.HTTP_401_UNAUTHORIZED
            return {"status": "unverified"}

        try:
            payload = await request.json()
            event = datadog.normalize(payload, received_at=received_at)
        except (ValueError, TypeError) as error:
            reason = str(error)[:500]
            logger.warning("quarantined datadog delivery: %s", reason)
            async with engine.begin() as connection:
                await repository.quarantine(
                    connection,
                    event_id=str(uuid4()),
                    source="datadog",
                    received_at=received_at,
                    reason=reason,
                )
            return {"status": "quarantined", "reason": reason}

        # A recovery ends the incident. It closes the dedupe window so a genuine
        # re-trigger inside 15 minutes is treated as new, and it is never enqueued
        # because there is nothing left to investigate.
        if datadog.is_recovery(payload):
            async with engine.begin() as connection:
                closed = await repository.close_window(
                    connection, fingerprint=event.fingerprint, closed_at=received_at
                )
            logger.info("datadog recovery closed %d window(s)", closed)
            return {
                "status": "recovered",
                "fingerprint": event.fingerprint,
                "windows_closed": closed,
            }

        async with engine.begin() as connection:
            admission = await repository.admit(connection, event)

        if admission.is_duplicate:
            logger.info(
                "datadog duplicate for %s, dedupe_count=%d",
                admission.fingerprint,
                admission.dedupe_count,
            )
            return {
                "status": "duplicate",
                "event_id": admission.event_id,
                "fingerprint": admission.fingerprint,
                "dedupe_count": admission.dedupe_count,
            }

        # Enqueued only after the row is committed. The reverse order would let a
        # consumer pick up an event whose row does not exist yet.
        message_id = await producer.publish(redis, event)
        logger.info("datadog accepted %s as %s", admission.fingerprint, message_id)
        return {
            "status": "accepted",
            "event_id": admission.event_id,
            "fingerprint": admission.fingerprint,
            "severity": event.severity.value,
            "entities": [f"{entity.type}:{entity.id}" for entity in event.entities],
            "queue_message_id": message_id,
        }

    secrets = source_secrets or {}

    def _register(name: str, normalize: Any, *, hmac_signed: bool) -> None:
        """Wire one source's route.

        Verification differs per source and is passed in rather than inferred:
        our own generic endpoint signs the body (HMAC), while the vendors that
        offer nothing better carry a shared token (§11.5.6). Alertmanager signs
        nothing at all, so it is checked by peer address instead.
        """

        @router.post(f"/{name}", status_code=status.HTTP_202_ACCEPTED, name=f"{name}_webhook")
        async def handler(  # pyright: ignore[reportUnusedFunction]
            request: Request,
            response: Response,
            _name: str = name,
            _normalize: Any = normalize,
            _hmac: bool = hmac_signed,
        ) -> dict[str, Any]:
            received_at = datetime.now(tz=UTC)
            secret = secrets.get(_name, "")
            body = await request.body()

            # Alertmanager carries no credential to check, so the peer address is
            # the credential. An unconfigured allowlist admits nothing, the same
            # way an unconfigured secret does.
            if _name == "alertmanager":
                ok = verify_source_ip(
                    request.client.host if request.client else None,
                    allowlist=alertmanager_allowlist,
                )
            else:
                ok = (
                    verify_hmac_signature(body, request.headers, secret=secret)
                    if _hmac
                    else verify_shared_token(request.headers, secret=secret)
                )
            if not ok:
                logger.warning("rejected unverified %s delivery", _name)
                response.status_code = status.HTTP_401_UNAUTHORIZED
                return {"status": "unverified"}

            try:
                events = _normalize(await request.json(), received_at=received_at)
            except (ValueError, TypeError) as error:
                reason = str(error)[:500]
                logger.warning("quarantined %s delivery: %s", _name, reason)
                async with engine.begin() as connection:
                    await repository.quarantine(
                        connection,
                        event_id=str(uuid4()),
                        source=_name,
                        received_at=received_at,
                        reason=reason,
                    )
                return {"status": "quarantined", "reason": reason}

            if not events:
                # A batch of only resolved alerts. Nothing to investigate, and
                # nothing malformed either.
                return {"status": "ignored", "reason": "no firing alerts in payload"}

            results = await _admit_and_enqueue(engine=engine, redis=redis, events=events)
            return {"status": "processed", "count": len(results), "results": results}

    _register("pagerduty", sources.normalize_pagerduty, hmac_signed=False)
    _register("grafana", sources.normalize_grafana, hmac_signed=False)
    _register("alertmanager", sources.normalize_alertmanager, hmac_signed=False)
    _register("generic", sources.normalize_generic, hmac_signed=True)

    return router
