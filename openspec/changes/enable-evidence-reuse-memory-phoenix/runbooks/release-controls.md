# Rollout, rollback, and commit boundaries

This record is the release-control companion to the B1, B2, B3, and Phoenix
runbooks. It is intentionally explicit about the distinction between local
qualification and an owner-approved serving gate.

## Safe configuration snapshot

The following values are the only safe default before a milestone is approved:

    MODULAR_EVIDENCE_SHADOW_ENABLED=false
    MODULAR_EVIDENCE_SHADOW_SAMPLE_RATE=0
    MODULAR_EVIDENCE_SHADOW_WRITE_BUDGET=0
    MODULAR_QUERY_REUSE_READ_MODE=off
    MODULAR_QUERY_REUSE_READ_SAMPLE_RATE=0
    MODULAR_QUERY_REUSE_B1_GATE_APPROVED=false
    MODULAR_PERSONALIZATION_CANARY_MODE=off
    MODULAR_PERSONALIZATION_CANARY_SAMPLE_RATE=0
    MODULAR_OTEL_ENABLED=false
    MODULAR_PHOENIX_ENABLED=false

Every activation uses a separate configuration change. A non-zero sample rate
or canary mode is invalid without the corresponding owner approval record.
Phoenix may be enabled independently, but exporter health never gates a
business request.

## Schema revision notes

The additive business migration chain for this change is:

    20260904_0010_shop_profile
      -> 20260905_0011_b2_freshness_watermark
      -> 20260905_0012_b1_source_batches

Revision 0011 adds the Query Family freshness watermark. Revision 0012 adds
source-batch and provenance persistence. Clean, N-1, current, and divergent
fixtures are checked before deployment. Divergent state stops without DDL.
Downgrade is limited to the corresponding additive revision and never removes
legacy tables or immutable candidate history.

## Independent commit boundaries

Before serving traffic, release engineering should materialize these
independent commits from the change worktree and verify each commit in
isolation:

| Boundary | Contents | Required gate |
| --- | --- | --- |
| C0 | Contracts, config validation, schema probes, fixtures, and ADR | strict OpenSpec validation and locked install |
| C1 | B1 shadow writer, source validation, migration 0012, and B1 tests | B1 shadow window and owner approval |
| C2 | B2 Query Family read path, migration 0011, CAS/fallback, and B2 tests | B2 shadow plus approved canary |
| C3 | B3 authority/outbox/Redis projection and personalization tests | B2 rollback rehearsal plus B3 gate |
| C4 | OTel/Phoenix adapters, evaluation plane, Compose profile, and smoke matrix | Phoenix infrastructure evidence or explicit optional status |
| C5 | Runbooks, verification records, and release review | explicit release approval for every serving switch |

The current working tree is an aggregate implementation and is not itself a
serving approval. A release branch must either split these boundaries into
separate commits or record an equivalent reviewed commit map before enabling a
non-off mode.

## Rollout order

1. Apply additive migrations and run schema-state probes.
2. Deploy with all B1/B2/B3/Phoenix serving modes off.
3. Run the B1 shadow window; retain legacy reads.
4. After the B1 gate, run B2 shadow, then the separately approved B2 canary.
5. Rehearse B2 rollback, then run B3 shadow and the separately approved B3 canary.
6. Enable Phoenix export independently only when its isolated profile and
   redaction/retention checks are available.

## Rollback switches

Set the affected switch to its safe value and leave immutable history in place:

    MODULAR_PERSONALIZATION_CANARY_MODE=off
    MODULAR_QUERY_REUSE_READ_MODE=off
    MODULAR_EVIDENCE_SHADOW_ENABLED=false
    MODULAR_OTEL_ENABLED=false

B1 rollback stops shadow writes. B2 rollback selects the legacy reader. B3
rollback selects public ranking and stops projection warm-up. Phoenix rollback
disables export/profile and retains repository-owned evaluation artifacts.
No rollback deletes Evidence, Bundle, Query Family, Memory, Temporal, or
evaluation records.
