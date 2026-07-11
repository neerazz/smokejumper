# ADR-0007: Provider-agnostic LLM via init_chat_model config

**Status:** Accepted · 2026-07-10 · **Level:** L2 · Sponsor requirement

## Context
Hard requirement from the sponsor: swap Anthropic / OpenAI-Codex / Gemini / local models at
any time, per deployment, without code changes.

## Decision
A `ModelProvider` port wraps LangChain `init_chat_model` provider strings, configured per
role (`worker`, `synthesis`) in config/env. No provider SDK import outside
`ports/model.py`. Anthropic is only the default config value.

## Options considered
1. **init_chat_model port (chosen)** — provider strings verified current (anthropic,
   openai, google_genai, ollama, bedrock, …).
2. Direct Anthropic SDK — best access to provider-native features; violates the requirement.
3. LiteLLM proxy — widest provider matrix but adds a proxy service and its own compat layer.

## Trade-offs accepted
- **We gave up** provider-native differentiators at the call site: prompt caching controls,
  provider-specific tool modes, fine-grained streaming — the port speaks
  lowest-common-denominator chat-completions. Provider-specific optimizations, if ever
  needed, must live inside the port as capability flags, not leak into callers.
- **We accepted** that prompts are tuned against one default provider and merely *run* on
  the others — swapping providers changes behavior; eval golden cases (§8) are the guard.
- **We kept** the sponsor's swap-anytime property and testability (a FakeModel provider in
  tests).

## Revisit when
A provider-native feature (e.g. server-side caching) demonstrably cuts cost >30% — extend
the port's capability surface; still no leaks.
