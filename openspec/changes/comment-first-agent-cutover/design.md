## Architecture

```text
XHSFoodOrchestrator (conversation boundary)
  -> CommentFirstResearchAgent (one use-case object)
       -> IntentResolver (conversation-aware, no follow-up branch)
       -> XhsLeadCollector
            -> XHS MCP source port (notes.search/detail, comments.search)
       -> CommentInsightAnalyzer
            -> evidence normalizer/bundle lifecycle
       -> ShopCandidateResolver
       -> ShopProfileService (freshness policy/cache)
            -> DianpingShopEnricher
            -> Dianping MCP source port (places.search/detail)
       -> ShopProfileRepository -> restaurants table
       -> EvidenceService -> existing comment evidence tables/bundles
       -> FoodResponsePresenter

MCP source ports -> Managed Agent Tool Catalog -> pinned snapshot executor
                         (policy, schema, account context, error mapping)
```

### Responsibilities

`CommentFirstResearchAgent` owns sequencing and budgets only. It does not know
MCP JSON shapes, HTTP clients, SQL, or regular expressions. Every collaborator
is constructor-injected and implements a narrow protocol.

`XhsLeadCollector` always requests comment-bearing note data and then fetches
the complete comment pages required by the configured collection budget. It
returns normalized leads plus the untouched provider payload, completeness,
cursor, and failure gap for every note.

`CommentInsightAnalyzer` extracts shop mentions, dishes, sentiment, and
controversy claims from comments. Deterministic parsing is limited to typed
field mapping; semantic interpretation is delegated to the configured model or
domain policy. Evidence references are written through the existing evidence
boundary, never embedded as mutable shop facts.

`DianpingShopEnricher` searches only for names/entities found in XHS evidence,
deduplicates by provider shop ID, and fetches profile data when available. A
challenge, 403, or unsupported shape produces an explicit `EnrichmentGap` and
does not erase successful search fields or comments.

`ShopProfileService` owns the low-frequency refresh policy. A fresh durable
profile is reused without a Dianping call; a missing, stale, or recently
partial profile enters the bounded enrichment queue. The dedicated
`ShopProfileRepository` maps all known stable fields into the `restaurants`
row and stores the complete normalized/provider payload in a JSON field.
Upserts are idempotent and refresh timestamps are independent from evidence
refresh. If a refresh fails, the last durable profile remains available and the
failure is returned as a typed gap.

Conversation history is passed to the Agent on every turn. A follow-up is not a
different code path: it is another user message evaluated with the same
workflow, context, and tools.

### Failure and efficiency policy

- XHS comment collection is primary and may complete even when Dianping is
  challenged.
- One Dianping search call may satisfy multiple candidates; detail calls are
  bounded and deduplicated.
- Review/comment pages are deduplicated by stable provider IDs while retaining
  every source view in provenance metadata.
- No unsupported response is coerced to an empty list. The workflow reports
  `partial` plus machine-readable gaps and preserves raw data.
- Catalog snapshots are pinned for the entire run; a refresh affects only later
  runs.
