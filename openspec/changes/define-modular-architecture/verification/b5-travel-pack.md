# B5 Travel Pack Qualification

Status: PASS for the local Travel contract and isolation gate.

## Shared Core Reuse

Travel registers through the existing `DomainPackRegistry` and pins the same
Domain Contract API, method set, schema validation, SourceGateway boundary,
Query Family/Evidence Bundle, Personalization and Refresh ports. The Pack adds
only travel semantics: attractions, routes, seasons, tickets, crowding,
duration and suitable audiences. It does not add a runtime, queue, memory
store, evidence database, or domain-specific infrastructure.

## Tool and Output Boundaries

`travel.poi.lookup` reuses the shared `PlaceLookupPort` and is validated by the
same schema-first `SchemaToolGateway`. Malformed input/output, unauthorized
tool names, connector failure and throwing Pack implementations are isolated
without publishing a candidate Pack. `TravelOutputAdapter` validates a
versioned itinerary shape and never projects an itinerary as a Restaurant DTO.

The output schema is pinned to `travel-agent-final-output/v1`; recovery and
future reads use the task's immutable Domain Contract pin rather than the
currently registered version.

## Rollback

Unregistering `travel@1.0.0` removes only future Travel selection. Existing
task pins remain valid, Food and the shared registry remain available, and no
shared schema, Bundle pointer, queue, or memory data is deleted. Restore uses
the registry's atomic validation path before republishing the exact Pack pin.

Focused qualification:

```powershell
uv run --frozen pytest -q tests/test_unit_b5_travel_pack.py tests/test_unit_s4_domain_pack_registry.py tests/test_unit_s4_food_pack_compatibility.py tests/test_unit_architecture_boundaries.py
uv run --frozen ruff check src/xhs_food/domain_packs/travel tests/test_unit_b5_travel_pack.py src/xhs_food/composition/adapters/travel_output.py src/xhs_food/composition/adapters/travel_tools.py
```
