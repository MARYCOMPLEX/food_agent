# B4 Operational Qualification

Status: PASS for the local contract gate covering tasks 12.8-12.13.

## Runtime and Configuration

- `MODULAR_REFRESH_ENABLED` and `MODULAR_MEDIA_ENABLED` are explicit opt-in
  switches and default to `false`.
- Refresh and Media use separate Temporal queues and quotas. A disabled quota
  rejects worker construction; Research capacity is unchanged.
- The target object store is lazy and uses the existing boto3 adapter. Local
  and CI use the same API against MinIO; no provider SDK enters contracts.

## Object Lifecycle Invariants

- Content type and byte-size limits are checked before dispatch and while the
  async source is consumed, providing bounded streaming backpressure.
- Production mode fails closed without `AES256` or `aws:kms` server-side
  encryption. KMS key references are required only for `aws:kms`.
- Signed URLs require an explicit TTL and are bounded to seven days. URL values
  are never recorded as metric labels or correlation attributes.
- Uploads are not business-visible before metadata authority commits. A
  metadata construction/transaction failure yields an idempotent orphan
  candidate; cleanup re-checks references and legal holds before deletion.
- Missing or corrupt objects fail the asset-scoped operation and do not publish
  Evidence or move a Bundle pointer.

## Failure and Observability Gate

The focused suite covers worker defaults, encryption fail-closed behavior,
allow-list/size rejection, multipart configuration, signed URL policy, orphan
cleanup, processor input/output quotas, extractor schema/provenance failures,
and deterministic Media Workflow registration. `RefreshMediaTelemetry` emits
only allow-listed queue/status/outcome labels and bounded object I/O and
extractor counters. Traces use the existing hashed correlation attribute gate.

The suite intentionally does not claim a deployed Temporal service restart,
multi-worker process crash, or production S3/MinIO availability. Those remain
release qualification probes; failure of those probes stops the affected
Refresh/Media worker and leaves the last committed Bundle serving.
