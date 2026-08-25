## Why

The modular architecture keeps legacy routes, DTOs, adapters, and fallback
bindings available during the migration window. They must only be removed
after a complete release cycle proves that no supported consumer depends on
them and that restore procedures work from the retained authoritative data.

## What Changes

- Inventory and approve every legacy consumer before removing a compatibility
  path.
- Remove only paths whose replacement contract has been stable for a complete
  release cycle.
- Preserve PostgreSQL facts, Temporal history, immutable Evidence/Bundle
  versions, and restore tooling throughout the contraction.
- Keep each removal in an independently testable, reversible milestone.

## Non-Goals

- This change does not remove any legacy path during the initial planning
  phase.
- It does not change the accepted PostgreSQL, Temporal, Redis, object-store,
  or Agent runtime authorities.
