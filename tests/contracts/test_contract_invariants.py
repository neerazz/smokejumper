"""Invariants that must hold for *every* contract, not one at a time.

A per-model test only protects the models someone remembered to write a test
for. These walk everything `smokejumper.contracts` exports, so a contract added
next year inherits the same rules or fails here.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import get_args

import pytest
from pydantic import ValidationError

import smokejumper.contracts as contracts
from smokejumper.contracts.base import Contract

EXPORTED_MODELS = sorted(
    (
        exported
        for exported in (getattr(contracts, name) for name in contracts.__all__)
        if isinstance(exported, type) and issubclass(exported, Contract)
    ),
    key=lambda model: model.__name__,
)


def model_ids() -> list[str]:
    return [model.__name__ for model in EXPORTED_MODELS]


def test_the_boundary_models_are_all_exported() -> None:
    assert len(EXPORTED_MODELS) >= 15, model_ids()


@pytest.mark.parametrize("model", EXPORTED_MODELS, ids=model_ids())
def test_every_contract_carries_schema_version(model: type[Contract]) -> None:
    assert model.model_fields["schema_version"].default == 1


@pytest.mark.parametrize("model", EXPORTED_MODELS, ids=model_ids())
def test_every_contract_rejects_an_unreadable_schema_version(model: type[Contract]) -> None:
    """A payload from a future, breaking version must fail rather than be read
    with today's field meanings."""
    with pytest.raises(ValidationError) as caught:
        model.model_validate({"schema_version": 2})
    assert any(
        error["loc"] == ("schema_version",) and error["type"] == "literal_error"
        for error in caught.value.errors()
    )


@pytest.mark.parametrize("model", EXPORTED_MODELS, ids=model_ids())
def test_no_contract_field_accepts_a_naive_datetime(model: type[Contract]) -> None:
    """A naive timestamp in an audit record is a timestamp in an unknown timezone,
    which makes ordering and "as believed at T" retrieval guesswork."""
    naive = [
        name
        for name, field in model.model_fields.items()
        if any(inner is datetime for inner in _flatten(field.annotation))
    ]
    assert naive == [], f"{model.__name__} accepts naive datetimes on {naive}"


@pytest.mark.parametrize("model", EXPORTED_MODELS, ids=model_ids())
def test_every_contract_is_frozen(model: type[Contract]) -> None:
    assert model.model_config.get("frozen") is True


def test_only_the_recorded_llm_payload_tolerates_unknown_fields() -> None:
    relaxed = [
        model.__name__ for model in EXPORTED_MODELS if model.model_config.get("extra") != "forbid"
    ]
    assert relaxed == ["LlmCallPayload"]


def test_b7_is_visibly_unassigned() -> None:
    """B7 has no contract on purpose. This asserts the gap is documented, so a
    future reader finds an explanation instead of assuming something was lost."""
    docstring = contracts.__doc__ or ""
    assert "**B7**" in docstring
    assert "intentionally unassigned" in docstring
    assert [name for name in contracts.__all__ if "B7" in name or "b7" in name] == []


def _flatten(annotation: object) -> Iterator[object]:
    yield annotation
    for argument in get_args(annotation):
        yield from _flatten(argument)
