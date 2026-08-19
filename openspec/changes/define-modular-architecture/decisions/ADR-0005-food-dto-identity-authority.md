# ADR-0005: Food DTO And Restaurant Identity Authority

- Status: Accepted
- Date: 2026-08-19
- Owners: API, Domain, Data Platform, SDK, QA
- Characterization evidence: [`food_dto.json`](../../../../tests/fixtures/characterization/food_dto.json), [`python_public_contract.json`](../../../../tests/fixtures/characterization/python_public_contract.json)
- Normative contract: [`food_dto_v1.schema.json`](../../../../tests/fixtures/authority/food_dto_v1.schema.json), [`food_dto_v1.json`](../../../../tests/fixtures/authority/food_dto_v1.json)

## Decision

The existing Food compatibility surface is named `food-dto/v1`. It remains the
authority at legacy HTTP, SSE result, persistence JSON, and Python import boundaries
while the modular core uses domain-neutral contracts internally.

### Naming And Ownership

| Boundary | Authority | Rule |
|---|---|---|
| Python models and internal calls | Python attributes | Use `snake_case`; do not introduce camel-cased Python attributes. |
| `FoodSearchIntent.to_dict/from_dict` | Legacy wire | Keep `location`, `food_type`, `requirements`, `exclude_keywords`, `time_filter`, and `price_range` in snake case. |
| `RestaurantRecommendation.to_dict` | Legacy wire | Keep the characterized mixed form: most fields are snake case, while `mustTry` and `blackList` remain camel case. Nested indicator keys remain snake case. |
| `XHSFoodResponse.to_dict` | Legacy wire | Keep the characterized snake-case result envelope. |
| `EnrichedRestaurant.to_dict` | Legacy SSE restaurant view | Keep the characterized camel-case view fields such as `chnName`, `businessArea`, `openTime`, `trustScore`, `oneLiner`, `sourceNotes`, `mustTry`, and `blackList`; do not add `id` to this enriched view. |
| `Restaurant.to_dict` and the constructed `persistedRestaurant` fixture | Legacy restaurant entity/storage view | Keep the enriched camel-case fields and reuse the stored `id`. This fixture characterizes `Restaurant.to_dict`; it is not evidence of the live `search_results` writer input. |
| Live `search_results.restaurants` writer | Legacy task persistence/recovery view | Preserve `ConversationContext.last_recommendations`: the mixed `RestaurantRecommendation.to_dict` shape plus the generated or stored `id`. Do not silently replace it with `EnrichedRestaurant.to_dict` or `Restaurant.to_dict`. |
| New modular contracts | Versioned internal schema | Use `snake_case` and a mapper at every legacy boundary. A generic recursive case converter is forbidden because it would corrupt the mixed v1 contract. |

The authoritative key sets, null/default behavior, and representative Unicode values
for the modeled DTOs are defined by the normative schema and fixture. The live
`search_results` writer boundary was discovered after this ADR's initial acceptance;
ADR-0009 records its code evidence and requires S2 to add a writer-path
characterization. Existing persisted v1 restaurant JSON is read back without case
conversion regardless of which legacy writer shape produced it. The Pydantic API
`Restaurant` class is a transport view, not the owner of the domain entity or
persistence identity.

### Restaurant Compatibility Identity

For a valid non-blank restaurant name, define:

```text
N = trim(name)
T = trim(tel) when tel is present, otherwise ""

if T == "":
    id = lowercase_hex(sha256(utf8(N)))[:32]
else:
    id = lowercase_hex(sha256(utf8(N + ":" + T)))[:32]
```

`trim` is Python `str.strip()`. The compatibility algorithm performs no Unicode
normalization, case folding, punctuation folding, telephone normalization, or locale
conversion. The colon is present only in the non-empty telephone branch. The output is
exactly 32 lower-case hexadecimal characters.

Once stored, `Restaurant.id` is stable and authoritative. Read/update paths must reuse
the stored ID; they must not recalculate it when alias, address, coordinates, rating,
display text, tags, or other mutable fields change. A corrected name or telephone would
produce a different compatibility hash when creating a new record. Identity merges,
aliases, and canonical entity IDs therefore require explicit data migration and must
preserve the old v1 ID as an alias; they are not implemented by silently changing this
formula.

### Python Public Surface

The ordered `__all__` values captured under `publicExports` in the normative fixture are
the `food-dto/v1` public import contract for `xhs_food`, `xhs_food.schemas`,
`xhs_food.agents`, `xhs_food.services`, `xhs_food.events`, `xhs_food.protocols`, and
`xhs_food.di`. Moving implementations behind facades must preserve these import paths
and object names. Additions require review; removal, rename, reordered snapshot, or
semantic reassignment requires a compatibility version and migration note.

Constructor injection points, orchestrator methods, MCP names, and `ToolResult` shapes
remain governed by the broader Python characterization fixture. This ADR does not make
private attributes public.

### Result Equivalence

For migration differential tests, two `food-dto/v1` results are equivalent only when:

- object key sets, JSON types, nulls/defaults, enum strings, restaurant IDs, text, list
  lengths, and list order are exact;
- recommendation order is exact; it is not a Top-K set comparison;
- integers and booleans are exact and are never treated as floating-point values;
- finite unrounded floating-point values may differ by at most an absolute `1e-6`, with
  no relative tolerance;
- values serialized by v1 with an explicit rounding rule, including `trustScore`, are
  compared exactly after serialization;
- NaN and infinity are invalid.

Changes to ranking relevance, recommendation membership/order, default values, or text
are behavior changes and cannot be approved by widening the numeric tolerance or merely
regenerating a fixture.

### Version Compatibility

`food-dto/v1` is an untagged legacy payload on the wire, but its schema name is explicit
in tests and adapters. Within v1, producers must emit the exact characterized key set;
fields cannot be renamed, removed, retyped, or added opportunistically. Consumers should
ignore unknown fields for forward resilience, but producers may not use that expectation
to mutate v1.

A future normalized DTO must use a distinct schema/media/API version and an explicit
mapper. During migration, v1 and the new version receive the same internal result and are
tested independently. Existing persisted JSON in both observed legacy shapes and
restaurant IDs remain readable for the retention lifetime. A new version cannot become
the default until writer-path, server, and client consumer fixtures pass and rollback to
the v1 mapper has been rehearsed.

## Consequences

- Internal modular types can be consistently snake-cased without changing legacy clients.
- Compatibility adapters must be field-aware and version-aware.
- The task result mapper must distinguish the live recommendation-plus-`id` writer from
  the enriched SSE view and the `Restaurant.to_dict` entity view.
- Restaurant identity remains reproducible for existing favorites and stored results.
- The mixed v1 naming is deliberate technical debt, isolated at boundaries rather than
  propagated into the modular core.

## Rejected Alternatives

- Global camelCase or snake_case conversion: rejected because current v1 payloads mix both.
- Hashing name plus an empty colon when telephone is absent: rejected because it changes IDs.
- Recomputing IDs on every write: rejected because mutable POI enrichment would break
  favorites and historical results.
- Unordered or broad-score result comparison: rejected because it can hide ranking and
  serialization regressions.
