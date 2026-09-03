## Why

The active food Agent still couples intent parsing, a four-phase search executor,
special follow-up handling, and a Gaode POI adapter. This makes the Agent's tool
use difficult to review and loses the central product signal: detailed
conversation evidence from Xiaohongshu comments. Dianping should enrich and
persist shop facts, while evidence remains owned by the existing evidence
pipeline.

## What Changes

- Make one comment-first research workflow the only food Agent route.
- Treat the full conversation as Agent context; remove the special
  `FollowUpHandler` branch and its regex classification.
- Discover and call Xiaohongshu and Dianping MCP tools through typed, injected
  source ports backed by the managed catalog and pinned snapshot.
- Collect complete comment/review payloads with explicit completeness and gap
  metadata; never discard raw provider data to optimize the outer message.
- Resolve shop candidates from comments, then enrich them from Dianping and
  persist the stable structured profile in the existing `restaurants` table.
- Keep comment evidence in the existing evidence/bundle lifecycle, separate from
  low-frequency shop-profile refresh.
- Remove the Gaode service, adapters, factories, compatibility registrations,
  and related dependencies from executable source.
- Add a provider/model configuration for the OpenAI-compatible test endpoint;
  credentials remain local and ignored.

## Goals

- A reviewer can follow `Agent -> workflow -> source ports -> MCP catalog ->
  evidence/profile repositories` without provider-specific imports in the Agent.
- XHS comments are the primary discovery and ranking signal.
- Dianping contributes canonical shop identity, address/geo, images, dishes,
  pricing, hours, promotions, tags, and any additional structured fields it
  returns, preserving the raw payload for future fields.
- Partial or challenged calls are represented as gaps rather than silently
  turning into empty results.

## Non-Goals

- No new platform scraper or browser automation is introduced.
- No reduction of comment payloads for the sake of response size.
- No parallel legacy implementation or Gaode fallback is retained.
- Existing public HTTP response shape is changed only additively where profile
  and evidence metadata are useful.

## Impact

The cutover affects the food orchestration entry point, MCP source adapters,
restaurant persistence, observability allow-lists, configuration, and focused
tests. Existing evidence bundle identity and refresh authorities remain the
source of truth for comment evidence.
