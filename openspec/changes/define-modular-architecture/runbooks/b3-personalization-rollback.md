# B3 Personalization Rollback Runbook

## Purpose

Disable the independent personalization canary and return ranking to the
public/legacy path without deleting PostgreSQL memory facts, preference
snapshots, consent records, or existing evidence and Bundle versions.

## Rollback Invariants

1. `MODULAR_PERSONALIZATION_CANARY_MODE=off` and
   `MODULAR_PERSONALIZATION_CANARY_SAMPLE_RATE=0` are applied to every API
   instance before the canary binding is considered disabled.
2. The public candidate set, Evidence, Query Family identity, features, and
   public scores are not rewritten during rollback.
3. PostgreSQL remains the memory and business-fact authority. No Redis value is
   promoted to a replacement fact and no authority row is deleted.
4. Redis personalization projection warm-up is stopped. Existing hot state may
   expire naturally or be explicitly invalidated; cache failure does not change
   the committed authority state.
5. Public refresh priority remains unchanged. A rollback does not create a
   refresh task, alter a Family pointer, or apply private feedback to shared
   assets.

## Procedure

1. Drain new canary exposures and set the two canary variables above on every
   API instance. Keep the PostgreSQL memory schema and outbox consumer
   available for audit and later re-enable.
2. Resolve the `personalization_canary` binding and call its rollback command.
   Record the returned `PersonalizationRollbackReceipt`; it must report
   `public/legacy`, retained PostgreSQL authority, and disabled projection
   warm-up.
3. Rebuild the canary service with
   `PersonalizationCanarySettings(mode=off, sample_rate=0)` or restart the
   composition root. Do not change public Bundle pointers or evidence rows.
4. Verify a fixed candidate fixture is served in public/legacy order and that
   no personalized ranking, private value, or user identifier appears in the
   canary metric labels.
5. Retain all PostgreSQL memory records, snapshots, outbox events, and audit
   receipts. Re-enable only through a new approved canary configuration.

## Verification

```powershell
uv run --frozen pytest -q tests/test_unit_b3_canary.py tests/test_unit_b3_rollback.py
```
