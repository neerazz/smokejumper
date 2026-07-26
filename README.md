# Smokejumper 🪂🔥

**An agentic SRE that parachutes into incidents.**

An alert lands, Smokejumper dispatches budgeted specialist investigators in parallel, and it
reports a grounded conclusion with receipts—creating or updating exactly one ticket per
incident fingerprint.

> **Status: the M0 foundation is implemented; M1–M6 are design only.** The three-service Compose
> stack boots and the contracts, configuration, and ports exist. The incident-triage behaviour —
> intake, investigation, and actions — does not. Commands are published as runnable only after
> their milestone has been implemented and verified.

## One source of truth

[`SPEC.md`](SPEC.md) is the single normative source for v1. It owns the current requirements,
configuration, prerequisites, operator inputs, ports, build order, commands, and acceptance
evidence. Start here:

- [Purpose and v1 scope](SPEC.md#1-purpose--scope)
- [Build prerequisites and operator inputs](SPEC.md#11-build-prerequisites-and-operator-inputs)
- [Executable M0–M6 implementation plan](SPEC.md#12-executable-implementation-plan)
- [Testing and acceptance](SPEC.md#8-testing--acceptance)

The [architecture decision records](docs/adr/README.md) explain why choices were made and what
would reopen them; they are not a second setup guide. The diagrams visualize the specification.
If either disagrees with `SPEC.md`, it is stale and must be fixed in the same change.

## Architecture

### Component view

![Smokejumper component view](architecture/smokejumper-components.svg)

### Event flow and boundary contracts

![Smokejumper flow](architecture/smokejumper-architecture.svg)

The flow diagram's editable Mermaid source is
[`architecture/smokejumper-architecture.mmd`](architecture/smokejumper-architecture.mmd).
The component view is hand-maintained SVG. Diagram maintenance instructions live in the source
files so README does not become a parallel runbook.

## License

[MIT](LICENSE)
