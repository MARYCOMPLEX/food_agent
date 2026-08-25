## Preconditions

Contraction is blocked until the release-gate record for
`define-modular-architecture` is qualified, the consumer inventory has no
unresolved supported callers, and a restore rehearsal has passed from a clean
database plus retained Temporal/Evidence history.

## Method

1. Freeze a compatibility ledger entry for the path, replacement contract,
   consumer set, feature binding, and rollback command.
2. Add a deprecation observation period covering one complete release cycle.
3. Remove one path at a time behind a configuration binding; run the full
   contract, failure, browser, and restore suites.
4. Revert the single removal if any consumer, restore, or authority gate
   regresses. Never delete authoritative data as part of a code rollback.

## Authority Boundaries

PostgreSQL remains the business-fact authority, Temporal history remains the
executable checkpoint, Redis remains rebuildable hot state, and S3-compatible
object storage remains the binary authority. Contraction cannot introduce a
new migration chain, queue, lock, or memory authority.
