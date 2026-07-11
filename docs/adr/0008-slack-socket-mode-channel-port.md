# ADR-0008: Slack Socket Mode; ChannelAdapter port with Slack-only v1

**Status:** Accepted · 2026-07-10 · **Level:** L2

## Context
Slack is the primary human surface (mentions in, receipts + approval buttons out). Sponsor
also named Telegram and email as eventual channels. Research verified slack-bolt (MIT,
Socket Mode first-class), aiogram (MIT, async) and imap-tools/IMAPClient as the mature
libraries.

## Decision
Chat surfaces implement a `ChannelAdapter` port. v1 ships exactly one adapter: Slack via
slack-bolt **Socket Mode**. Telegram (aiogram) and email are documented, unbuilt adapters.

## Options considered
1. **Socket Mode (chosen)** — websocket out; no public HTTPS endpoint; easiest self-host.
2. Slack Events API over HTTP — stateless and multi-instance-friendly, but demands a public
   URL + signing on every deployment; hostile to laptops/homelabs.
3. Building Telegram/email in v1 — rejected by red-team as scope creep: examples ≠ requirements.

## Trade-offs accepted
- **We gave up** horizontal scaling of the Slack listener (Socket Mode is a stateful
  connection; one active listener per app) — irrelevant at v1's single-process scale.
- **We accepted** a per-workspace setup step (the sponsor creates the Slack app; scopes
  documented in SPEC §5.1) instead of an installable OAuth distribution flow.
- **We kept** ~zero networking prerequisites for adopters, and a port that makes channel #2
  an adapter PR, not a redesign.

## Revisit when
Multi-workspace distribution is wanted (→ OAuth + Events API), or the first real Telegram/
email user appears (→ build that adapter behind the existing port).
