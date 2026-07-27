"""Provider-neutral ticketing models (SPEC §5.6)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from smokejumper.contracts import TicketDraft, TicketProvider, TicketRef, TicketUpdate

RUN_ID = "0192f0a1-0000-7000-8000-000000000001"
FINGERPRINT = "779f0b514e31fc4b83fa0d1dcad8c3498fe929e0c2a86b43d05bd4a41bda5e86"


def test_ref_round_trips_json() -> None:
    ref = TicketRef.model_validate(
        {
            "schema_version": 1,
            "provider": "linear",
            "external_id": "SMOKE-123",
            "url": "https://linear.app/x/SMOKE-123",
        }
    )
    assert TicketRef.model_validate_json(ref.model_dump_json()) == ref
    assert ref.provider is TicketProvider.LINEAR


def test_provider_enum_is_closed() -> None:
    with pytest.raises(ValidationError):
        TicketRef.model_validate({"schema_version": 1, "provider": "trello", "external_id": "1"})


def test_a_draft_carries_the_idempotency_key() -> None:
    """`(fingerprint, run_id)` is what makes a redelivered webhook update the open
    ticket instead of opening a second one."""
    draft = TicketDraft.model_validate(
        {
            "schema_version": 1,
            "fingerprint": FINGERPRINT,
            "run_id": RUN_ID,
            "title": "checkout 5xx above 5%",
            "body_md": "See run receipts.",
        }
    )
    assert (draft.fingerprint, str(draft.run_id)) == (FINGERPRINT, RUN_ID)


def test_an_update_may_carry_a_conclusion_status_or_none() -> None:
    comment_only = TicketUpdate.model_validate(
        {"schema_version": 1, "run_id": RUN_ID, "comment_md": "still firing"}
    )
    assert comment_only.status is None
    with_status = TicketUpdate.model_validate(
        {
            "schema_version": 1,
            "run_id": RUN_ID,
            "comment_md": "root caused",
            "status": "root_caused",
        }
    )
    assert TicketUpdate.model_validate_json(with_status.model_dump_json()) == with_status


def test_a_provider_workflow_state_is_not_accepted() -> None:
    """Adapters map B6 status to provider states; provider vocabulary must not
    leak back into a contract, or every adapter inherits every other's states."""
    with pytest.raises(ValidationError):
        TicketUpdate.model_validate(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "comment_md": "x",
                "status": "In Progress",
            }
        )
