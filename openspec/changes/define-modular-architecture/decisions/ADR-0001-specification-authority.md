# ADR-0001: Specification Authority And Versioned Architecture References

- Status: Accepted
- Date: 2026-08-19
- Owners: Architecture, API

## Context

The change was derived from a user objective, an interactive HTML architecture, a Draw.io source, current code, tests, README claims, and frontend assumptions. Those inputs disagree in naming and in several compatibility surfaces. The original diagram paths also lived outside the repository and could not serve as stable review evidence.

## Decision

Conflicts are resolved in this order:

1. Capability specs own required observable behavior.
2. Accepted ADRs and `design.md` own implementation choices and module boundaries.
3. `tasks.md` owns implementation sequencing and completion gates, but cannot weaken a spec or ADR.
4. Current code and executable tests own the characterization of legacy behavior until an authority decision versions that behavior.
5. README text, frontend types, and external diagrams are evidence and consumer claims; they are not normative when they conflict with the preceding sources.

Domain-neutral names in the specs and design therefore override Food-specific labels in a diagram. The Experience module is defined by the API/Task/Event contracts in the design; the Draw.io Experience view is an explanatory detail, not a second contract.

The two architecture sources are copied into this change and versioned with it:

| Reference | SHA-256 |
|---|---|
| [Interactive architecture](../references/food-agent-unified-architecture.html) | `0E122CF6D7F45344FAAF45AEC084E384463C94EBBAC36328DAE0D866A1E8C198` |
| [Draw.io source](../references/food-agent-extensible-evidence-architecture.drawio) | `70BA87D7EA63E55EC0AF22C47E4BC647751CF5DECE7CEBD22B81A63B3091CBC6` |

Future diagram changes must update the repository copy, its hash in this ADR, and any affected spec or design in the same review. External visualization paths are no longer review dependencies.

The copied references are historical approved inputs, not a representation of the current implementation baseline. They still contain superseded labels such as OpenAI Agents SDK, ARQ, Redis/Queue locks, and Redis job state. ADR-0002 overrides those labels. Task `14.16` owns synchronizing the visual content and adding an automated drift check before release.

## Consequences

- Current incompatibilities must be characterized rather than silently resolved during structural moves.
- A diagram cannot introduce a second Agent, queue, memory system, or data authority.
- Generated or manually maintained diagrams must be checked against the contract registry and dependency rules before a milestone closes.
- The repository now contains the exact visual inputs used to approve this baseline.
