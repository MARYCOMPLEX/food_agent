# ADR-0012: Task Queues And ObjectStore Operational Binding

- Status: Accepted
- Date: 2026-08-24
- Owners: Platform Runtime + Platform Storage + Security + SRE
- Decides: OpenSpec task 1.13; operational value qualification remains a B4 gate

## Decision

The foundation binding has one durable runtime and one object storage port:

| Capability | Binding | Boundary |
|---|---|---|
| Research execution | Temporal `research` Task Queue | Foreground Research Workflows and Activities only |
| Continuous refresh | Temporal `refresh` Task Queue | Refresh Workflows and Activities only |
| Media processing | Temporal `media` Task Queue | Media fetch/process/extract Workflows and Activities only |
| Object storage | Project-owned `ObjectStore` backed by boto3 | Production S3-compatible endpoint; local and CI MinIO |

The three queues MUST have distinct names and independently configurable worker
capacity. A worker may register more than one queue only when its capacity and
priority policy are explicit; the default deployment uses separate worker pools.
Refresh and Media work MUST NOT consume the Research queue's reserved capacity.
Redis is not a queue, lease, lock, retry authority, or dead-letter store.

The production ObjectStore adapter is boto3. The local adapter uses the same
S3-compatible API against MinIO through boto3's endpoint configuration; a
second MinIO SDK is not introduced. PostgreSQL stores object metadata,
provenance, visibility, retention class, and discoverability. Object bytes never
become a database column or a source of business truth.

## Object Security And Lifecycle Invariants

1. Production uploads MUST use configured server-side encryption. The adapter
   receives the encryption mode/key reference from deployment configuration and
   never logs credentials, signed URLs, or provider responses. Local/CI may use
   an explicitly declared test mode; an omitted production encryption setting is
   a configuration error, not an implicit plaintext fallback.
2. Every object and derived artifact MUST carry a versioned retention class.
   Retention duration, signed-URL TTL, and legal-hold behavior are policy data;
   a missing policy value means retain and deny deletion/publication rather than
   guessing a duration.
3. A successful object upload is not discoverable until the PostgreSQL metadata
   transaction commits. Uploads left without committed metadata are orphan
   candidates and are cleaned idempotently after the configured grace period.
   Cleanup MUST re-check references, retention, and legal holds before deletion.
4. Media and object cleanup is scheduled on the `media` queue. Cleanup retries
   use stable object/content identities and are safe to repeat. Cleanup failure
   cannot move a Bundle current pointer or create Evidence.

Concrete encryption algorithms, retention durations, signed-URL TTLs, orphan
grace intervals, and legal-hold controls remain the B4 operational qualification
inputs in OQ-12. This ADR fixes their ownership and fail-closed behavior without
inventing deployment-specific secrets or policy values.

## Retry Exhaustion And Manual Recovery

Temporal Activity retry, timeout, heartbeat, and cancellation policy is the only
retry mechanism for durable jobs. Connector/provider internal retries MUST be
bounded so they do not multiply the Temporal budget. When retries are exhausted:

- the Workflow remains a queryable failed execution with its Workflow ID, run ID,
  failure category, and last successful checkpoint;
- no broker-style dead-letter queue is created;
- no candidate Evidence, Bundle pointer, or object metadata is published by a
  failed operation; and
- an operator may inspect, retry, or terminate the failed Workflow using the
  Temporal API and the runbook for its queue.

Manual recovery MUST use the same Workflow ID/idempotency key and PostgreSQL
conditional activation/CAS. It MUST NOT edit a published Bundle in place, write
task state to Redis, or use an unconditional pointer update. A recovery that
needs an older Bundle/profile uses the B2 pointer rollback procedure; a recovery
that needs object cleanup uses the Media cleanup procedure.

## Rejected Alternatives

- A shared priority-blind queue: rejected because background refresh/media work
  can starve foreground research.
- ARQ, Celery, a Redis job facade, or a broker dead-letter queue: rejected
  because they create a second durable runtime and a second retry authority.
- A MinIO-specific production SDK: rejected because boto3's S3-compatible port
  keeps local and production behavior replaceable.
- Deleting orphan bytes synchronously inside the metadata transaction: rejected
  because object storage and PostgreSQL cannot share one atomic transaction.

## Evidence

- [`ADR-0002`](./ADR-0002-infrastructure-baseline.md) records the accepted
  Temporal, S3-compatible, boto3, MinIO, Redis, and PostgreSQL baseline.
- [`TemporalTaskQueues`](../../../../src/xhs_food/foundation/temporal.py) enforces
  distinct queue names.
- [`Boto3ObjectStore`](../../../../src/xhs_food/foundation/object_store.py)
  provides the production and MinIO endpoint adapter.
- [`b2-query-family-rollback.md`](../runbooks/b2-query-family-rollback.md)
  demonstrates conditional pointer recovery without deletion.

## Qualification And Rollback

The independent decision gate is:

```powershell
uv run --frozen pytest -q tests/test_unit_infrastructure_binding_decision.py tests/test_unit_s3_foundation_adapters.py tests/test_unit_s3_composition_adapters.py tests/test_unit_s3_redis_contract.py
openspec validate define-modular-architecture --strict
```

This milestone adds no migration, object, queue, or runtime binding. Reverting
its implementation commit removes only this ADR, its decision-index/task entry,
and its characterization test; the accepted ADR-0002 baseline and all existing
production adapters remain usable. A deployment rollback therefore requires no
data restore and does not stop or rewrite existing Temporal histories.
