"""Per-source inbound verification (SPEC 5.1).

Each source gets the strongest scheme it actually offers, which is not the same
scheme for all of them:

- **Datadog has no request-signing scheme.** Its webhooks are user-defined
  payloads with optional custom headers, and Datadog never computes an HMAC over
  the body. Implementing "Datadog HMAC" would therefore be fiction: we would be
  verifying a signature the sender cannot produce. What Datadog *can* do is send
  a fixed custom header, so verification is a constant-time comparison of a
  shared token. That is weaker than HMAC — it is a bearer secret, replayable if
  TLS is terminated by something untrusted — and the weakness belongs to the
  vendor, not to this code.
- **Generic HTTP callers** are ours to specify, so they use HMAC-SHA256 over the
  raw body (SPEC 11.5.6), which is replay-resistant per-payload.

Both comparisons use `hmac.compare_digest`. A `==` on a secret leaks its prefix
through timing, and the whole point of this module is to be the one place that
cannot be got wrong quietly.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

# Datadog sends this as a custom header configured on the webhook. This is the
# header *name*, not a credential; the secret it carries comes from config.
DATADOG_TOKEN_HEADER = "X-Smokejumper-Token"  # noqa: S105

# Ours to define, so it is a real signature (SPEC 11.5.6).
GENERIC_SIGNATURE_HEADER = "X-Smokejumper-Signature"
_SIGNATURE_PREFIX = "sha256="


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup.

    HTTP header names are case-insensitive and different senders disagree about
    casing, so a case-sensitive read would reject a valid request from one client
    and accept it from another.
    """
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def verify_shared_token(headers: Mapping[str, str], *, secret: str) -> bool:
    """True when the request carries the configured shared token (Datadog).

    An empty configured secret is never a pass. A source whose secret was
    forgotten must fail closed, or the check silently becomes a no-op exactly
    where it matters.
    """
    if not secret:
        return False
    presented = _header(headers, DATADOG_TOKEN_HEADER)
    if presented is None:
        return False
    return hmac.compare_digest(presented, secret)


def verify_hmac_signature(body: bytes, headers: Mapping[str, str], *, secret: str) -> bool:
    """True when `X-Smokejumper-Signature: sha256=<hex>` matches an HMAC of `body`.

    Computed over the raw bytes, never over a re-serialized object: `json.dumps`
    of a parsed body reorders keys and changes whitespace, so a signature checked
    against it would fail for honest senders and could be forged by dishonest
    ones.
    """
    if not secret:
        return False
    presented = _header(headers, GENERIC_SIGNATURE_HEADER)
    if presented is None or not presented.startswith(_SIGNATURE_PREFIX):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(presented.removeprefix(_SIGNATURE_PREFIX), expected)
