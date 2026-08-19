# ADR-0004: HTTP And SSE Compatibility Authority

Status: Accepted

Date: 2026-08-19

Owners: API + Frontend

Decides: OQ-16 and OQ-17; tasks 1.3, 1.4, and 1.5

## Context

The S0 fixtures prove that three consumers currently disagree:

- FastAPI exposes one `POST /v1/search/` command endpoint. It puts
  `sessionId` under `data`, uses `limit/offset` and `data.items` for history,
  uses `data.items` for favorites, returns the FAQ array directly as `data`,
  and consumes the standard `Last-Event-ID` SSE header.
- The frontend calls the unified search endpoint but reads a top-level
  `sessionId`; it also calls unimplemented refine/recover routes, sends
  `page/pageSize`, reads `data.history/favorites/faqs`, sends
  `lastEventIndex`, and expects Food/platform-specific step IDs plus `detail`.
- README describes `/start`, `/refine`, and `/recover` endpoints that are not
  present in the OpenAPI document or server router.

Current code and documentation are evidence, not authority. This ADR chooses a
single public contract while keeping the S0-S5 structural milestones free of
production behavior changes.

Evidence:

- `tests/fixtures/http/openapi.json`
- `tests/fixtures/http/search_http_golden.json`
- `tests/fixtures/characterization/consumer_contracts.json`
- `tests/fixtures/sse_characterization/*.sse`
- `tests/fixtures/authority/http_v1_authority.schema.json`
- `tests/fixtures/authority/sse_v1_contract.json`
- `tests/fixtures/authority/sse_v1_window_replay.sse`
- `tests/fixtures/authority/sse_v1_replay_expired.sse`

## Decision 1: Unified Search Route

`POST /v1/search/` is the sole canonical v1 search command route. Its operation
is selected by the request body:

| Body | Operation |
|---|---|
| `query` without `sessionId` | new search |
| `sessionId` and `query` | refine the same session |
| `sessionId` without `query` | recover the same session |

`GET /v1/search/stream/{sessionId}`, `GET
/v1/search/status/{sessionId}`, and `GET /v1/search/results/{sessionId}` remain
the read/stream routes. Clients MUST use the canonical trailing-slash command
URL and MUST NOT depend on FastAPI's current `307` slash redirect.

The README `/start`, `/refine`, and `/recover` paths are stale documentation,
not deployed compatibility routes. They are documentation-deprecated
immediately and MUST be removed or labelled historical. Structural milestones
MUST NOT add aliases merely to make the stale README true. If telemetry later
proves a deployed external consumer needs an alias, that alias requires a
separate API compatibility change with an owner, usage telemetry, deprecation
headers, a sunset date, and a rollback plan.

## Decision 2: HTTP Envelope And Pagination

The observed FastAPI v1 wire is the compatibility authority. The frontend is
the consumer to adapt in a separately reviewed behavior/client change.

- Successful search command responses use `{ "success": true, "data": ... }`;
  `sessionId` is `data.sessionId`, never a top-level field.
- History uses query parameters `limit` and `offset`; its response list is
  `data.items` with `data.total`, `data.limit`, and `data.offset`.
- Favorites uses `data.items` with `data.total`.
- FAQ uses the array directly as `data`; there is no `data.faqs` wrapper.
- FastAPI transport/validation/not-found failures retain `detail` for v1.
  Existing business-negative outcomes may retain `success: false` plus their
  characterized `data`, `message`, or `error`. This ADR does not invent one
  universal error envelope inside v1.

The exact authority schemas and examples are in
`tests/fixtures/authority/http_v1_authority.schema.json`. Operation-specific
fields may be added only when optional for existing v1 consumers. Moving list
or identity fields, changing pagination coordinates, or changing a field's
type requires a new API contract version.

## Decision 3: Canonical SSE v1

The current numeric-step stream remains the `legacy` compatibility encoding
until an explicit behavior rollout enables canonical SSE `v1`. S0-S5 MUST
continue to pass the legacy byte fixtures. The Stable Event Mapper owns the
translation; internal task events, Domain Packs, and the EventBus do not own
the public wire vocabulary.

### Negotiation

A browser selects canonical v1 with:

```text
GET /v1/search/stream/{sessionId}?sseVersion=v1
Accept: text/event-stream
Last-Event-ID: EVENT_ID  # optional
```

Native `EventSource` cannot set arbitrary request headers, so version selection
is a query parameter. A v1 stream responds with `X-SSE-Version: v1`.
Unsupported explicit versions return HTTP 406 before opening a stream, with
`unsupported_sse_version` and the supported versions. Omitting `sseVersion`
continues to select `legacy` until a separately approved default-switch and
sunset gate. `lastEventIndex` is not a cursor or compatibility alias.

### Step IDs And Payload Fields

Canonical v1 exposes six stable, domain-neutral presentation stages:

1. `intent_parsing`
2. `evidence_collection`
3. `evidence_analysis`
4. `evidence_validation`
5. `entity_enrichment`
6. `result_generation`

Food/platform labels such as `xhs_search`, `comment_analysis`, and
`poi_enrichment` are mapper inputs, not public canonical IDs. Domain Packs may
change labels or detail text but MUST NOT add source/platform names to this
stable six-stage vocabulary.

Every canonical event carries `schemaVersion`, `sessionId`, `taskId`, and
`turnId`. Field ownership is fixed:

- `detail` is optional human-readable step detail on `step_start`, `step_done`,
  and `step_error`; clients MUST NOT branch on its text.
- `message` is the human-readable successful terminal text on `done`.
- `error` is an object with stable `code`, human-readable `message`, and
  boolean `retryable` on `step_error` and terminal `error`.
- `step_error` is not terminal by itself. Exactly one `done` or `error` is the
  task/turn terminal. `result` is not terminal.

Terminal publication is scoped to `taskId + turnId`, is idempotent, and occurs
only after the authoritative PostgreSQL task/result projection has committed.
An old turn's terminal MUST NOT terminate a newer turn in the same session.

## Decision 4: Replay And Resynchronization

`Last-Event-ID` is the only replay cursor. When the ID is retained, replay is
exclusive: the cursor event is omitted and the first returned event is the
next event in stream order. Reconnection MUST preserve the same task and turn
and MUST NOT start new research.

When the cursor is unknown, trimmed, expired, or lost after Redis recovery, the
server MUST NOT replay from the beginning or claim continuity. It emits one
connection-control event named `replay_expired`, without an SSE `id`, whose
payload contains:

- `reason: "cursor_not_retained"`;
- `action: "resync"`;
- the same session/task/turn identity;
- an authoritative PostgreSQL `snapshot` with a monotonic `snapshotVersion`;
- a terminal projection when the task is terminal, or `resumeFromEventId` when
  it is still running.

The server then closes that SSE response. The client atomically replaces its
local projection with the snapshot. A running client reconnects using
`resumeFromEventId`; a terminal client applies the included terminal and does
not reconnect. Neither path creates a new task. A missing authoritative
snapshot is a stable dependency/state error, not an empty successful replay.

The retained-window and expired-window byte authorities are the two `.sse`
fixtures named above. The Redis retention target remains one hour and
`MAXLEN 1000`; retention length does not weaken the expired-cursor behavior.

## Rollout And Consequences

1. S0-S5 keep legacy HTTP/SSE behavior while adding facades and mappers.
2. A client correction consumes the authoritative HTTP envelope and
   pagination fields; it does not change the server contract.
3. Canonical SSE v1 is introduced as explicit opt-in and validated against the
   authority fixtures. Legacy remains the default during compatibility soak.
4. The default may switch to v1 only after browser reconnect, multi-turn,
   terminal, and expired-window gates pass. Legacy removal requires telemetry
   and a separately approved sunset.

This decision intentionally requires future client/server behavior changes;
it does not perform them. Characterization fixtures remain immutable evidence
of the legacy encoding, while authority fixtures define the approved target.
