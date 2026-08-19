# ADR-0006: Canonical Query, Freshness, And Evidence Authority

- Status: Accepted
- Date: 2026-08-19
- Owners: Domain, Evidence, Data Governance
- Decides: OQ-4, OQ-5, and OQ-8; contract portion of OQ-6 and OQ-7
- Normative fixtures:
  - [`canonical_query_v1.schema.json`](../../../../tests/fixtures/authority/canonical_query_v1.schema.json)
  - [`canonical_query_v1.json`](../../../../tests/fixtures/authority/canonical_query_v1.json)
  - [`freshness_policy_v1.schema.json`](../../../../tests/fixtures/authority/freshness_policy_v1.schema.json)
  - [`freshness_policy_v1.json`](../../../../tests/fixtures/authority/freshness_policy_v1.json)
  - [`evidence_bundle_v1.schema.json`](../../../../tests/fixtures/authority/evidence_bundle_v1.schema.json)
  - [`evidence_bundle_v1.json`](../../../../tests/fixtures/authority/evidence_bundle_v1.json)

## Context

The query-reuse requirements need reviewable contracts before the S1 SDK and B1
shadow schema can be implemented. They must preserve public evidence reuse without
letting user identity, session state, or preferences enter a shared Family. They
also need a governance model for source and media evidence without reopening the
accepted PostgreSQL, Temporal, Redis, or S3-compatible infrastructure choices.

This ADR fixes schema and lifecycle semantics. It deliberately does not invent the
domain relevance thresholds, freshness durations, coverage minima, popularity
windows, or scheduler weights that require B2/B4 qualification data.

## Decision 1: Canonical Query V1

The authority name is `canonical-query/v1`. A value has three versioned layers:

1. `schema_version` fixes the serialized contract.
2. `normalizer_version` fixes Unicode, whitespace, case, geo, time, ordering, and
   enum normalization.
3. `classifier_version` fixes the Domain Contract rules that project a constraint
   to public semantics or private personalization.

The `query` object contains exactly `domain`, `geo`, `intent`, `audience`,
`constraints`, `time_range`, and `freshness_policy`. All strings are UTF-8, Unicode
NFKC, trimmed, and have internal whitespace collapsed before field-specific rules
run. Registered slugs are lower-case ASCII; country/region codes are upper-case;
set-like arrays and public constraints use stable sort and duplicate elimination.
Timestamps use UTC RFC 3339. A normalizer must reject a value it cannot normalize;
it must not retain raw user prose in a shared identity.

`tenant_scope`, `language`, and `region` are mandatory isolation coordinates outside
the seven-field query object. A Family lookup, alias, merge, split, Bundle, or
derived index never crosses any of these coordinates. `tenant_scope = "public"`
means the explicitly governed shared-public partition, not an omitted tenant.
Changing a coordinate creates another partition. Cross-language translation can
reuse source assets only through an explicit provenance-preserving normalization
step; it is not a Family alias.

The deterministic Family identity preimage is the canonical JSON representation of
the isolation coordinates plus this projection:

```text
domain + geo + intent + constraints + time_range + freshness_policy
```

`audience` remains in Canonical Query so matching and reranking can explain whether
the request is for locals, visitors, families, or another registered segment. It is
not part of the deterministic Family key and audience-only differences do not split
a shared public Family. If an audience statement changes the facts that must be
collected, the versioned classifier must express that fact need as a public
constraint. Otherwise it remains a strategy/reranking input. This lets the two
approved Zigong examples share one Family and Bundle while retaining different
ranking explanations.

### Constraint classification

- **Public**: a normalized, non-personal predicate that changes the external fact
  set, evidence validity, source scope, entity category, or public time/geo scope.
  Only this projection enters `query.constraints`.
- **Personal**: taste, dietary restriction, personal budget, mobility need, trip
  style, or another preference/requirement attached to a user or session. It enters
  the isolated Personalization input and can become a hard filter or reranking
  policy, but never a Family identity or Evidence field.
- **Unknown**: no active classifier rule applies. The request must take the approved
  clarify or non-shared path; it cannot read or create a shared Family.

Classifier results record a stable rule ID and version. The canonical fixture lists
the initial classification categories; Domain Packs can add registered keys only by
versioning the classifier and supplying compatibility examples. Raw user ID, session
ID, device ID, cohort, preference, click, favorite, memory, or free-form private
value is forbidden anywhere in Canonical Query or the Family identity preimage.

## Decision 2: Explainable Three-Level Family Matching

Matching is restricted to the same isolation coordinates and domain, and runs in
this order:

1. deterministic identity key;
2. PostgreSQL `pg_trgm` over the versioned normalized lexical projection;
3. only when the first two levels have no approved match, normalized cosine search
   with BGE-M3 `profile_v1` (1024 dimensions).

Each result records the level, rule/profile version, candidate IDs, score,
threshold version, and reason codes. Exact identity has confidence `1`. The numeric
trigram/vector thresholds are not selected here: B2 must approve them from fixed
fixtures and store them in a versioned matching policy. Missing/stale derived
indexes, an incompatible embedding profile, a score below the active threshold, or
ambiguous top candidates all produce no automatic merge. The system creates a new
Family or a review candidate instead of guessing.

Merge and split corrections are append-only audited operations. An audit record
contains operation ID, before/after Family IDs, isolation coordinates, actor type,
rule/profile/threshold versions, observed scores, reason codes, evidence references,
and timestamp. Merge preserves old IDs as aliases and never mutates a published
Bundle. Split creates new Families and candidate Bundles; it does not move or edit
old Bundle contents in place. Any current-pointer change still requires candidate
validation and PostgreSQL CAS. A later correction appends a compensating operation;
history is not rewritten. Cross-partition merge and alias operations are invalid.

## Decision 3: Freshness Policy V1 Contract

The authority name is `freshness-policy/v1`. Each Domain Contract selects a
versioned policy containing:

- per evidence/source partition fresh window, maximum stale time, and required flag;
- named coverage dimensions, weights, minimum ratios, and an overall minimum;
- source watermark mode and connector-owned monotonic comparison contract;
- aggregate popularity window/signals with no raw user identity;
- normalized priority factors for expiry urgency, coverage deficit, popularity,
  watermark advance, new source/time window, and public change rate;
- deterministic tie-break order and active-refresh handling.

Coverage ratios and priority factors are in `[0, 1]`; coverage weights sum to `1`;
maximum stale time is at least the fresh window. A watermark is opaque outside the
owning Connector and must be compared using the recorded comparator version, never
lexically guessed. Popularity consumes only privacy-approved aggregate counters and
cannot use a user ID, private preference, or raw feedback value as a Family key. The
accepted `memory-privacy/v1` policy currently denies all feedback-derived public
refresh influence; the review fixture therefore uses only a non-feedback Family
request count. Enabling feedback-derived change rate requires the separate privacy
ADR/version required by ADR-0008.

The gate returns exactly `fresh`, `incremental`, or `new`. `fresh` requires all
required partitions inside their fresh windows and minimum coverage. `incremental`
requires a reusable Bundle inside maximum stale/coverage bounds and emits only the
missing, expired, or advanced-watermark partitions. `new` applies when no eligible
Family/Bundle exists or stale/coverage bounds fail. A compatible active refresh is
returned as the single-flight task reference, not scheduled again.

The fixture values are explicitly marked `review_example`; they prove the contract
shape and invariants but are not production defaults. OQ-7 remains open only for
Food/Travel policy values and B4 scheduler weights. OQ-6 likewise remains open only
for qualified trigram/vector thresholds and ambiguity margins.

## Decision 4: Evidence And Bundle V1

The authority name is `evidence-bundle/v1`. It defines `SourceLocator`, `MediaRef`,
`DerivedArtifact`, `EvidenceItem`, `EvidenceBundle`, and governance policy in one
schema so provenance and visibility cannot be detached from content.

- `SourceLocator` identifies source, connector/version, external item, canonical
  URL, capture time, optional source-update time, and opaque watermark.
- `MediaRef` is an unfetched source reference. It contains metadata and locator
  references, never bytes, credentials, cookies, or a signed URL.
- `DerivedArtifact` references an opaque S3-compatible object key plus SHA-256,
  size, content type, processor/version, input lineage, and governance metadata.
- `EvidenceItem` contains a typed claim/value, confidence, content hash, locator,
  optional media/artifact references, extractor/schema versions, and governance.
- `EvidenceBundle` is immutable, scoped to one Family/isolation partition, records
  version/parent, evidence references, coverage, watermarks, verification time,
  freshness policy, provenance/content hashes, and candidate/published/rejected
  state. Only validated accepted Evidence can enter a published Bundle.

PostgreSQL is authoritative for all metadata, provenance, visibility, governance,
Bundle state, and current pointers. The S3-compatible ObjectStore holds only bytes.
Redis may cache a rebuildable lookup but owns none of these facts; Temporal may run
the jobs but owns no business record.

### Visibility and license

`public` means eligible for shared evidence inside the governed isolation partition;
it does not mean Internet redistribution. `tenant` requires the exact tenant scope.
`entitlement` also requires the listed entitlement set. User-private evidence is not
a valid public Evidence type and belongs to Personalization. A Bundle cannot be more
permissive than any included item, and restricted evidence must use a correspondingly
restricted Family/Bundle partition.

License metadata records a stable license ID, allowed use (`extract_only`,
`internal_reuse`, or `redistributable`), attribution requirement, optional expiry,
and policy version. Unknown or expired license state is quarantined and cannot enter
a published reusable Bundle. A derived artifact inherits the most restrictive use,
visibility, and expiry of all inputs; processing cannot broaden rights.

### Retention and deletion

Every locator, asset, artifact, Evidence item, and Bundle carries a versioned
retention-class reference. Durations, encryption settings, signed-URL TTLs, and
orphan-cleanup intervals remain OQ-12/B4 operational values; absence of those values
means retain and deny publication/deletion rather than choosing an implicit period.

Deletion is an auditable state transition, not an in-place edit of a published
Bundle:

1. PostgreSQL records an idempotent deletion/takedown request and tombstone, then
   removes the affected object from discovery and future candidate eligibility.
2. If a current Bundle references it, a replacement candidate excluding the object
   must validate and activate through normal CAS. The old Bundle hash is unchanged.
3. Object bytes are deleted asynchronously only after reference, retention, and
   legal-hold checks. Cleanup retries are idempotent.
4. Audit identity, hashes, policy/version, and deletion reason may remain as a
   tombstone, while payload and bytes are inaccessible. Governance deletion takes
   precedence over historical read availability.

An object uploaded without committed PostgreSQL metadata is never discoverable and
is eligible for idempotent orphan cleanup. A metadata transaction failure never
creates Evidence or advances a Bundle pointer.

## Consequences

- S1 can define domain-neutral types without settling B2 relevance numbers.
- B1 can shadow-write provenance and immutable candidate Bundles without exposing
  personal fields or changing the legacy response.
- Audience differences remain explainable without multiplying public evidence.
- License, visibility, retention, and deletion are enforced by authority metadata;
  changing object-store products or adding another business authority is unnecessary.
- Production matching/freshness values still require their scheduled qualification
  and cannot be copied from the review examples.
