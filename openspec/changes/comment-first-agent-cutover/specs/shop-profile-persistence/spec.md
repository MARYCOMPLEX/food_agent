## Purpose

Define durable, low-frequency shop profile persistence separate from mutable
comment evidence.

## ADDED Requirements

### Requirement: Restaurant rows retain canonical structured profile data

The `restaurants` table SHALL persist provider identifiers and normalized
structured fields available from Dianping, including address/geo, images,
dishes, category/region, price, rating/review count, hours, promotions, source
timestamps, and the complete provider payload for forward compatibility.

#### Scenario: Dianping returns a rich search item

- **WHEN** an enrichment response contains identity, location, media, dishes,
  price, rating, and promotion fields
- **THEN** those fields and the raw provider payload are written to the
  restaurant row

### Requirement: Profile upsert is lossless and idempotent

An upsert SHALL merge newly available profile fields without clearing existing
non-empty fields when a later provider response is partial. Repeating the same
provider payload SHALL produce the same row identity and no duplicate shop.

#### Scenario: A later detail response is partial

- **WHEN** a later refresh omits an address and image already persisted
- **THEN** the existing values remain and only newly available fields are
  merged

### Requirement: Profile refresh does not mutate evidence

Updating a restaurant profile SHALL NOT replace, delete, or rewrite comment
evidence bundles. Evidence refresh remains governed by its existing lifecycle.

#### Scenario: Profile retry succeeds after a challenge

- **WHEN** a detail retry fills missing shop metadata
- **THEN** only profile columns and profile refresh metadata change; comment
  evidence references and content are unchanged

### Requirement: Profile refresh is low frequency and cache-aware

The Agent SHALL consult the durable profile repository before calling Dianping.
Complete profiles SHALL be reusable for the configured freshness window;
partial or failed profiles MAY use a shorter retry window. A failed refresh
MUST leave the last durable profile available to the response.

#### Scenario: A fresh profile is already stored

- **WHEN** a candidate has a complete profile fetched within the freshness
  window
- **THEN** the Agent reuses that profile and does not issue a Dianping request

#### Scenario: A stale refresh fails

- **WHEN** a stale profile is selected for refresh and Dianping is challenged
  or unavailable
- **THEN** the prior profile remains readable, and a typed refresh gap is
  surfaced without deleting its fields

### Requirement: Unknown and unavailable fields are explicit

Missing fields MUST remain null/empty according to the profile contract, while
provider challenges and unsupported shapes are stored as refresh gaps rather
than represented as successful empty profile data.

#### Scenario: Provider response has an unknown field

- **WHEN** a provider adds a field not yet in the normalized model
- **THEN** the field is retained in the raw payload and the normalized row
  remains valid
