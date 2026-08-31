## Purpose

Expose the audited Dianping protocol implementation as a canonical, read-only
source connector for places, details, reviews, and media references while
keeping its browser, SQLite, and provider-specific payloads behind the gateway.

## ADDED Requirements

### Requirement: Dianping read operations map to canonical contracts

The connector MUST implement source search, place detail, review comments, and
media-reference listing using the project-owned SourceConnector contract. It
MUST emit stable source IDs, connector/version metadata, canonical URLs,
timestamps, cursors/watermarks, and JSON-compatible attributes without binary
content or credentials.

#### Scenario: Place search
- **WHEN** a valid source-ready request targets `dianping`
- **THEN** the connector returns canonical documents keyed by the provider shop ID and preserves pagination metadata

#### Scenario: Review collection
- **WHEN** a detail locator is fetched with an active account session
- **THEN** reviews become canonical comments linked to the shop external ID and review media becomes separate media references

### Requirement: Provider outcomes remain distinguishable

The connector MUST distinguish a valid empty result from authentication,
challenge, rate-limit, timeout, malformed, and dependency failures using the
existing ContractError taxonomy and source/provider scope.

#### Scenario: True empty search
- **WHEN** Dianping returns a valid result page with zero shops
- **THEN** the batch is `success_empty` with no fabricated error

#### Scenario: Verification challenge
- **WHEN** Dianping redirects to a verification host or returns a challenge response
- **THEN** the batch carries a stable retryable challenge/rate-limit code, the account health is degraded, and no empty-success evidence is published

### Requirement: Browser state is account-local

Each operation MUST construct and close a provider browser/client using only the
resolved account session for that activity. The upstream SQLite API, task
worker, risk lease, and storage-state path MUST NOT become project authority.

#### Scenario: Two Dianping accounts
- **WHEN** two activities collect concurrently for different accounts
- **THEN** their Playwright contexts and session snapshots remain disjoint and both outputs retain the correct account-scoped provenance

#### Scenario: Review without active account
- **WHEN** a review request has no active Dianping session
- **THEN** the connector returns a stable authentication error before launching a browser
