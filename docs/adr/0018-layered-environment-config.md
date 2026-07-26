# ADR-0018: Layered per-environment config in one validated settings object; prod fails closed

**Status:** Accepted · 2026-07-25 · **Level:** L2 · **Strengthens** [ADR-0004](0004-hexagonal-ports.md) (closes its accepted stub risk) · **Amended** 2026-07-26 (the `fixtures` compose profile was removed — [ADR-0016](0016-local-observability-stack.md) — so gate 2 covers `lab` alone; the layering and the three gates are otherwise unchanged)

## Context
Every deployment target needs different values: local points at compose service names, dev at
dev endpoints with cheap models and a tiny spend ceiling, prod at real endpoints with real
credentials. The spec previously mentioned `config.yaml`/env in passing (§2, model roles) and
`SMOKEJUMPER_LOG_DIR` (§5.8), with no layering rule, no precedence order, and no statement of
what varies where.

Two hazards made this worth an ADR rather than a convention.

**The word "profile" was about to mean two things.** §2c and §2e introduce docker-compose
profiles (`lab`, `obs`) that select which *services* start. Deployment environments select which
*values* are used. Same word, orthogonal axes, guaranteed confusion in every future
conversation and config file.

**ADR-0004 left a hole.** It accepted the risk that "stubs normalize insecurity if deployed
carelessly" and mitigated it with boot-time log warnings. A log line is not a control: an
`AllowAll` auth port behaves identically to a real one from the perspective of everything
except a human reading startup output. Nothing prevented shipping stubs to production.

## Decision
One typed settings object (pydantic-settings), assembled lowest → highest: code defaults →
`config/base.yaml` → `config/<env>.yaml` → `SMOKEJUMPER__<SECTION>__<KEY>` env vars → CLI
flags. `SMOKEJUMPER_ENV` ∈ `{local, dev, prod}` selects the env file and defaults to `local`.
Boot validates the assembled object and fails fast.

Secrets are never stored in YAML — config holds references, values arrive as env vars (`.env`
locally, secret manager in dev/prod).

The term **"environment"** is reserved for local/dev/prod; **"compose profile"** for service
selection. The spec does not use "profile" for the former.

Three gates are enforced at boot, not documented:
1. `prod` refuses to start while any security-relevant port is a stub.
2. The `lab` compose profile is refused outside `local`.
3. `prod` requires an explicit spend ceiling; absent one, boot fails.

## Options considered
1. **Layered YAML + env overrides in one validated object (chosen).**
2. Env vars only, no config files — twelve-factor orthodoxy, and genuinely simpler for
   containers. Rejected because the surface is large (endpoints, budgets, model roles per
   role, dedupe windows, tier settings) and a flat env namespace makes diffing two
   environments impossible. Reviewing `dev.yaml` against `prod.yaml` is the operation that
   matters most and env vars cannot express it.
3. One `config.yaml` with an `env:` block selecting a sub-tree — fewer files, but every
   environment's values sit in the file you edit for any environment, and prod values end up
   in the same diff as local tweaks.
4. Separate config repo or a config service — appropriate at fleet scale; absurd overhead for
   a single-tenant tool whose stated value is that one person can operate it.
5. Reuse compose profiles for environments — the shortest path, and the trap this ADR exists
   to avoid: it would couple value selection to a Docker-specific mechanism, leaving prod
   (which may not use compose at all) with no way to select its own values.

## Trade-offs accepted
- **We gave up** twelve-factor purity. Config files in the image mean a value change can
  require a rebuild unless overridden by env var — which is exactly why layer 4 exists and
  outranks the files.
- **We accepted** four config files to keep in sync, and the drift risk that comes with them.
  Mitigated by `base.yaml` holding everything env-independent, so `<env>.yaml` files stay
  short enough to diff by eye, and by boot validation catching omissions immediately.
- **We accepted** that a fail-closed prod gate will, at some point, block a deploy someone
  believes should proceed. That is the intended behavior and the reason it is not a warning.
- **We kept** a single place to answer "what does this deployment actually use", the ability to
  review environment differences as a diff, and a prod that cannot silently run with
  `AllowAll` auth.

## Revisit when
A second tenant or fleet deployment appears (→ config service or per-tenant overlays), or the
env matrix grows past ~4 environments and `<env>.yaml` files start duplicating each other
(→ composition/inheritance between env files rather than more files).
