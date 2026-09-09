# Research Experience Contract v1

This file is the field-level freeze for the public experience boundary. The
Python models in `src/xhs_food/contracts/research_experience.py` are the
server authority and `frontend/src/shared/contracts/research.ts` is the
client mirror. JSON names below are wire names (camel case).

## 1. ResearchEvent v1

Every public delta is an object with the following required fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `schemaVersion` | literal `research-event/v1` | Public contract version, independent of SSE/WebSocket. |
| `eventId` | stable string | Logical idempotency identity. It is not a transport cursor. |
| `sessionId` | string | User conversation/session identity. |
| `taskId` | string | One admitted research task. |
| `turnId` | positive integer | Conversation turn within the session. |
| `sequence` | positive integer | Contiguous public sequence within the task/turn. |
| `occurredAt` | timezone-aware timestamp | Source/projection time, not client receipt time. |
| `kind` | core kind or `x.<namespace>.<name>` | Semantic event name. |
| `payload` | bounded JSON | Kind-specific public data. |

Optional envelope fields are `runId`, `phase`, `status`, `mutation`, `entity`,
and `extensions`. `mutation` is one of `append`, `upsert`, `patch`,
`replace`, or `remove`. `extensions` is a namespace map; a domain must not
add unnamespaced top-level event kinds.

The core kind registry is:

```text
run_started, plan_updated,
action_started, action_progress, action_completed,
evidence_added, controversy_upserted, profile_upserted,
recommendation_upserted, gap_upserted, run_progress,
run_completed, run_failed, run_cancelled
```

The generic entity identity is:

```json
{"entityType":"shop","entityId":"shop-1","version":2}
```

`version` is optional and only meaningful to a domain adapter. Transport
metadata (`id`, `Last-Event-ID`, WebSocket offsets) is outside this envelope.

## 2. Public entity payloads

The following payload shapes are stable. Collection events may use either the
singular form (`{"profile": {...}}`) or a bounded plural form
(`{"profiles": [...]}`); the reducer uses the event mutation for merge rules.

### Evidence

`evidence_added` carries `items`. Each item has `evidenceId`, `source`, a
bounded `excerpt`, optional `noteRef` and `commentRef`, `stance`, provenance,
claim/entity references, capture time, and confidence. Evidence is append-only
and remains separate from recommendations.

```json
{
  "items": [{
    "evidenceId": "ev-comment-42",
    "source": "xhs",
    "noteRef": "note-8",
    "commentRef": "comment-42",
    "excerpt": "本地人说鱼香味足，但晚高峰要排队。",
    "stance": "mixed",
    "entityRefs": [{"entityType":"shop","entityId":"shop-1"}],
    "claimRefs": ["claim-flavor-1"]
  }]
}
```

### Controversy

`controversy_upserted` carries `controversyId`, topic, summary, status,
opposing `sides`, evidence/claim references, and either a resolution or a
remaining question. A later upsert can resolve the same identity without
deleting either side's evidence.

### Shop profile

`profile_upserted` carries `profileId` and any known structured fields:
`providerRefs`, `name`/alias/URLs, address/location/coordinates, phone,
rating/review count, average price/price band, category, opening hours, images,
recommended dishes, promotions, tags, completeness, source/gap references, and
namespaced `domainData`. Image, dish, and promotion values may be structured
JSON so provider metadata is not discarded. Fields may arrive in separate waves. A sparse
upsert/patch cannot clear a known non-empty field.

### Gap / partial failure

`gap_upserted` carries `gapId`, `source`, `operation`, stable `code`, safe
`message`, `retryable`, `severity`, affected entity references, and optional
continuation. A profile challenge such as Dianping interactive verification is
therefore a normal public fact, not a thrown transport exception.

### Recommendation

`recommendation_upserted` carries a stable `recommendationId`, title/summary,
status, optional rank/confidence, evidence and controversy references, an
optional profile reference, highlights/warnings, and namespaced domain data.
It may be `candidate` or `partial` before the run is terminal.

## 3. UserResearchProjection v1

The snapshot has:

```text
schemaVersion = user-research-projection/v1
sessionId, taskId, turnId, optional runId
revision, lastSequence
status, phase, summary, intent
plan[], evidence[], controversies[], profiles[], recommendations[], gaps[]
coverage, metrics, termination, updatedAt
extensions, appliedEventIds (bounded reducer ledger)
```

`status` distinguishes `queued`, `running`, `succeeded`, `partial`,
`failed`, `cancelled`, and `blocked`. `termination` is present only after a
terminal event. `partial` explicitly means usable work exists but one or more
gaps remain; it is not an empty successful result.

The projection is a complete public snapshot, not a page of raw comments. The
retained event list and the evidence authority remain the audit sources. A
client can render the bounded excerpts immediately and fetch full evidence by
reference under the existing authorization boundary.

## 4. Reducer rules

1. Verify `sessionId`, `taskId`, `turnId`, and (when present) `runId`.
2. If `eventId` is already in the bounded ledger, return the same snapshot.
3. Require `sequence == lastSequence + 1`; otherwise raise a resync signal.
4. Apply the kind mutation, increment `revision`, set `lastSequence`, and add
   the event id to the ledger.
5. After a terminal projection, reject new user-visible mutations. A duplicate
   terminal event remains a no-op.

The reducer does not infer missing data, fabricate default prices/ratings, or
turn a provider exception into a successful empty result. A replay-expired
transport must replace the local state with an authoritative snapshot and then
continue from that snapshot's `lastSequence`.

## 5. Representative partial run

```json
{
  "schemaVersion": "user-research-projection/v1",
  "sessionId": "session-1",
  "taskId": "task-1",
  "turnId": 1,
  "revision": 7,
  "lastSequence": 7,
  "status": "partial",
  "evidence": [{"evidenceId":"ev-1","source":"xhs","commentRef":"c-1","excerpt":"汤底鲜"}],
  "controversies": [{"controversyId":"cv-1","topic":"排队","status":"unresolved"}],
  "profiles": [{"profileId":"p-1","name":"老店","status":"partial","address":"人民路 1 号"}],
  "gaps": [{"gapId":"g-1","source":"dianping","operation":"places.detail","code":"verification_required","retryable":true}],
  "termination": {"status":"partial","reason":"run_completed","message":"评论证据已完成"}
}
```

This is the contract the future page layout should consume. Components must
not reconstruct controversy, profile completeness, or failure semantics from
legacy step labels or regular expressions.
