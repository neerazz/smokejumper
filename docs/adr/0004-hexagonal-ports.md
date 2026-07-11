# ADR-0004: Hexagonal ports with loud v1 stubs

**Status:** Accepted · 2026-07-10 · **Level:** L1

## Context
Smokejumper is open-source core that must later embed into host platforms (first: Curlix)
with real auth, tenancy, and governance — none of which v1 users need to run it.

## Decision
Auth, Governance, Tenancy, ModelProvider, PlatformPort, ChannelAdapter, TicketingPort, and
MemoryPort are interfaces in `ports/`. v1 ships stubs (`AllowAll`, `SingleTenant`,
`EnvCredentials`, `FixturePlatform`) that announce themselves loudly at boot.

## Options considered
1. **Ports + stubs (chosen).**
2. Build real multi-tenant auth now — months of work ahead of any second tenant.
3. Hard-code single-tenant assumptions — cheapest now, rewrite later when embedding.

## Trade-offs accepted
- **We gave up** simplicity — every seam is an interface + injection point, which is more
  code and indirection than a hard-coded v1 strictly needs.
- **We accepted** the risk that stubs normalize insecurity if deployed carelessly —
  mitigated by boot-time warnings and privileged tier shipping empty (ADR-0005).
- **We kept** the property that the OSS core never needs a fork to gain real auth/tenancy:
  hosts implement ports.

## Revisit when
A port accumulates >2 implementations with awkward shape — that's the signal the
interface was cut wrong; redesign the port, don't patch adapters.
