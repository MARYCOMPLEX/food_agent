## Purpose

Define the single modular food research Agent whose primary evidence comes from
Xiaohongshu comments and whose secondary source is Dianping shop metadata.

## ADDED Requirements

### Requirement: Every turn uses one conversation-aware workflow

The system SHALL pass the complete bounded conversation history to the same
research workflow on every turn. It MUST NOT branch on a stored
recommendation list or classify a request with a special follow-up handler.

#### Scenario: User refines a previous request

- **WHEN** a session contains prior user and assistant messages and the user
  asks a refinement
- **THEN** the Agent evaluates the new message with that history and the same
  workflow/tool contracts

#### Scenario: No prior recommendations exist

- **WHEN** the session has no prior result
- **THEN** the same workflow resolves intent and collects evidence without a
  separate first-search implementation

### Requirement: Xiaohongshu comments are primary evidence

The workflow SHALL collect comment-bearing XHS notes and preserve each returned
comment's text, author/interaction fields, provider identifiers, raw payload,
cursor, and completeness metadata. A note with comments MUST NOT be reduced to
title/summary-only data.

#### Scenario: Comment pages are complete

- **WHEN** XHS returns multiple comment pages
- **THEN** the collector follows the provider cursor/limit contract, deduplicates
  by stable comment ID, and retains provenance for every page

#### Scenario: Comment collection is partial

- **WHEN** a page is challenged, times out, or has an unsupported shape
- **THEN** the result is marked partial with a typed gap and all successful raw
  comments remain available to analysis

### Requirement: Dianping enriches candidates without replacing evidence

The workflow SHALL derive Dianping lookups from entities identified in XHS
comments and SHALL map all known structured shop fields, including identity,
location, media, dishes, pricing, hours, categories, promotions, ratings, and
provider payload metadata. Dianping failures MUST NOT delete XHS evidence.

#### Scenario: Profile detail is challenged

- **WHEN** `places.detail` requires interactive verification
- **THEN** the workflow persists successful `places.search` fields, records an
  enrichment gap, and continues with the comment evidence

#### Scenario: Provider adds an unknown field

- **WHEN** a Dianping payload contains a field not yet modeled
- **THEN** the raw payload is persisted and the normalized profile remains valid

### Requirement: Evidence and shop profile have separate authorities

Comment evidence SHALL be written through the existing evidence/bundle
lifecycle. Stable shop metadata SHALL be upserted into the `restaurants` table
through a dedicated profile repository/service. Refresh timestamps and failure
gaps MUST be independently observable.

#### Scenario: Profile refresh follows evidence collection

- **WHEN** a shop profile is refreshed after comments have been analyzed
- **THEN** the restaurant row is updated while the existing evidence bundle
  identity and comment records remain unchanged

### Requirement: Source execution is typed and policy-bound

All XHS and Dianping calls SHALL use narrow source ports backed by the managed
MCP catalog's pinned snapshot and request-scoped account context. Agent/domain
code MUST NOT import MCP clients, service URLs, provider credentials, or SQL
adapters directly.

#### Scenario: A source schema changes during a run

- **WHEN** MCP discovery refreshes after a run has started
- **THEN** that run continues with its pinned tool snapshot and later runs may
  receive the refreshed definitions
