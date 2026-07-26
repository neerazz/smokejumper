"""The canonical fingerprint of SPEC §4 B2."""

from __future__ import annotations

import re

from smokejumper.contracts import event_fingerprint

GRAFANA_ALERT = "779f0b514e31fc4b83fa0d1dcad8c3498fe929e0c2a86b43d05bd4a41bda5e86"
SLACK_THREAD_NO_ENTITIES = "47d459543eae27d1a6c61f0dae2e44f42eed9c6be2663ba7ec281f0e5210604f"


def test_entity_order_does_not_change_the_fingerprint() -> None:
    one_way = event_fingerprint("grafana", "alert-42", [("service", "checkout"), ("host", "web-1")])
    other_way = event_fingerprint(
        "grafana", "alert-42", [("host", "web-1"), ("service", "checkout")]
    )
    assert one_way == other_way


def test_canonical_encoding_is_pinned() -> None:
    """These digests are a regression pin, not a restatement of the code.

    Every fingerprint ever stored was produced by one exact byte encoding; if a
    separator, the sort, or the escaping changes, every historical incident is
    re-identified and dedupe silently opens second tickets. That is the failure
    these two literals exist to catch.
    """
    assert (
        event_fingerprint("grafana", "alert-42", [("service", "checkout"), ("host", "web-1")])
        == GRAFANA_ALERT
    )
    assert event_fingerprint("slack", "1720000000.000100", []) == SLACK_THREAD_NO_ENTITIES


def test_entity_type_and_id_are_not_run_together() -> None:
    assert event_fingerprint("generic", "k", [("ab", "c")]) != event_fingerprint(
        "generic", "k", [("a", "bc")]
    )


def test_each_identity_input_changes_the_fingerprint() -> None:
    base = event_fingerprint("generic", "key-1", [("service", "checkout")])
    assert base != event_fingerprint("datadog", "key-1", [("service", "checkout")])
    assert base != event_fingerprint("generic", "key-2", [("service", "checkout")])
    assert base != event_fingerprint("generic", "key-1", [("service", "cart")])
    assert base != event_fingerprint("generic", "key-1", [])


def test_fingerprint_is_lowercase_sha256_hex() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", event_fingerprint("generic", "key-1", []))
