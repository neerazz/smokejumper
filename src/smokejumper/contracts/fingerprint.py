"""Canonical incident fingerprint (SPEC §4, B2).

The fingerprint is incident *identity*, so it is derived only from identity
inputs: the source, that source's own event key, and the entity set. Title and
body are excluded on purpose — a reworded alert is the same incident, and a
fingerprint that moved with the wording would open a second ticket for it.

The byte encoding below is itself part of the contract. Every fingerprint ever
stored was produced by it, so changing the separators, the ordering, or the
escaping silently re-identifies every historical incident.

Imports stdlib only, so the rule "fingerprints are computed one way" cannot be
weakened by a dependency.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable


def event_fingerprint(
    source: str,
    source_event_key: str,
    entities: Iterable[tuple[str, str]],
) -> str:
    """SHA-256 hex over canonical JSON `[source, source_event_key, sorted(entities)]`.

    `entities` are `(type, id)` pairs; they are sorted here, so the caller's
    ordering cannot change the identity of an incident.
    """
    sorted_entities = sorted([entity_type, entity_id] for entity_type, entity_id in entities)
    canonical = json.dumps(
        [source, source_event_key, sorted_entities],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
