"""ModelProvider — the only module permitted to import a provider SDK.

No SDK is imported yet: no provider is chosen before M2 (SPEC 11.4), and naming
one here would be a guess. When one is chosen, its import belongs in this module
and nowhere else, so a provider swap stays configuration (SPEC decision 10.1) and
`tests/architecture` can keep proving no other module reaches a provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

ModelRole = Literal["worker", "synthesis"]


class ModelProvider(Protocol):
    """Every model call in the system, and the point where B8 records it.

    Callers pass the prompt text and its registry reference; the implementation
    hashes the text itself and records `prompt_ref` + `prompt_sha256` on the
    `llm_call` event (SPEC 2e). A caller cannot supply the hash, so it can be
    neither forged nor omitted, which is what makes a recorded run attributable
    to a prompt version.
    """

    async def complete(self, *, role: ModelRole, prompt: str, prompt_ref: str) -> str:
        """Call the model configured for `role` and return its text.

        `role` is indirection on purpose: `settings.model` maps it to a provider
        model name, so changing models never touches a call site.
        """
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed `texts`, one vector per input, in order.

        Vector width must equal `settings.embedding.dimension`; the pgvector
        column is fixed at that width and a mismatch is a migration, not a retry.
        """
        ...
