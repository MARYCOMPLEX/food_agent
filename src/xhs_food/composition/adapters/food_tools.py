"""Providers for the Food Pack's approved typed tools."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any, cast

from xhs_food.contracts import AllowedToolContract, PlaceLookupPort, SearchToolPort
from xhs_food.domain_packs.food.resources import load_food_manifest
from xhs_food.gateways import ProviderResult, SchemaToolGateway, ToolRegistration


class FoodPlaceLookupProvider:
    """Translate the approved `place.lookup` schema to the Place owner port."""

    name = "place.lookup"
    tool_version = "1.0.0"
    source_capability = "place.lookup"
    source_version = "1.0.0"

    def __init__(self, lookup: PlaceLookupPort) -> None:
        self._lookup = lookup

    async def execute(self, **arguments: Any) -> ProviderResult:
        raw = await self._lookup.lookup(
            keywords=cast(str, arguments["query"]),
            city=cast(str, arguments["geo"]),
            types="050000",
        )
        if raw is None:
            return ProviderResult(False, error_code="DEPENDENCY_UNAVAILABLE")
        places = raw.get("pois")
        if not isinstance(places, list):
            return ProviderResult(False, error_code="MALFORMED_RESPONSE")
        projected: list[dict[str, str]] = []
        for place in places:
            if not isinstance(place, Mapping):
                return ProviderResult(False, error_code="MALFORMED_RESPONSE")
            source_id = place.get("poi_id") or place.get("id")
            name = place.get("name")
            if not isinstance(source_id, (str, int)) or not isinstance(name, str) or not name:
                return ProviderResult(False, error_code="MALFORMED_RESPONSE")
            address = place.get("address")
            projected.append(
                {
                    "sourceId": str(source_id),
                    "name": name,
                    "address": address if isinstance(address, str) else "",
                }
            )
        return ProviderResult(
            True,
            data={"schemaVersion": "place.lookup/output/v1", "places": projected},
        )

    async def health_check(self) -> bool:
        check = getattr(self._lookup, "health_check", None)
        if check is None:
            return True
        return bool(await check())


class FoodReviewSearchProvider:
    """Create a process-local batch reference from managed MCP search output."""

    name = "evidence.search_reviews"
    tool_version = "1.0.0"
    source_capability = "reviews.search"
    source_version = "1.0.0"

    def __init__(self, search: SearchToolPort, *, retained_batches: int = 128) -> None:
        if retained_batches < 1:
            raise ValueError("retained_batches must be positive")
        self._search = search
        self._retained_batches = retained_batches
        self._batches: OrderedDict[str, tuple[dict[str, Any], ...]] = OrderedDict()

    async def execute(self, **arguments: Any) -> ProviderResult:
        keywords = cast(Sequence[str], arguments["keywords"])
        limit = cast(int, arguments["limit"])
        raw = await self._search.execute(
            keyword=" ".join(keywords),
            count=limit,
            sort_type="most_comments",
            include_details=True,
            include_comments=True,
        )
        try:
            success = bool(cast(Any, raw).success)
            data = cast(Any, raw).data
            error_code = cast(Any, raw).error_code
            error_message = cast(Any, raw).error_message
        except AttributeError:
            return ProviderResult(False, error_code="MALFORMED_RESPONSE")
        if not success:
            return ProviderResult(
                False,
                error_code=error_code or "DEPENDENCY_UNAVAILABLE",
                error_message=error_message,
            )
        if not isinstance(data, Mapping) or not isinstance(data.get("notes"), list):
            return ProviderResult(False, error_code="MALFORMED_RESPONSE")
        notes = data["notes"][:limit]
        if any(not isinstance(note, Mapping) for note in notes):
            return ProviderResult(False, error_code="MALFORMED_RESPONSE")
        try:
            detached = tuple(cast(dict[str, Any], dict(note)) for note in notes)
            encoded = json.dumps(
                detached,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return ProviderResult(False, error_code="MALFORMED_RESPONSE")
        batch_ref = f"canonical-source-batch/{hashlib.sha256(encoded).hexdigest()}"
        self._batches[batch_ref] = detached
        self._batches.move_to_end(batch_ref)
        while len(self._batches) > self._retained_batches:
            self._batches.popitem(last=False)
        return ProviderResult(
            True,
            data={
                "schemaVersion": "evidence.search-reviews/output/v1",
                "batchRef": batch_ref,
                "itemCount": len(detached),
            },
        )

    def get_batch(self, batch_ref: str) -> tuple[dict[str, Any], ...] | None:
        """Resolve only snapshots actually produced by this provider instance."""

        return self._batches.get(batch_ref)

    async def health_check(self) -> bool:
        return bool(await self._search.health())


def build_food_tool_gateway(
    place_lookup: PlaceLookupPort,
    review_search: SearchToolPort,
) -> tuple[
    SchemaToolGateway,
    tuple[FoodPlaceLookupProvider | FoodReviewSearchProvider, ...],
]:
    manifest = load_food_manifest()
    contracts: dict[str, AllowedToolContract] = {
        contract.tool_id: contract for contract in manifest.allowed_tools
    }
    providers: tuple[FoodPlaceLookupProvider | FoodReviewSearchProvider, ...] = (
        FoodPlaceLookupProvider(place_lookup),
        FoodReviewSearchProvider(review_search),
    )
    registrations = tuple(
        ToolRegistration(contract=contracts[provider.name], provider=provider)
        for provider in providers
    )
    return (
        SchemaToolGateway(registrations, allowed_tools=frozenset(contracts)),
        providers,
    )


__all__ = [
    "FoodPlaceLookupProvider",
    "FoodReviewSearchProvider",
    "build_food_tool_gateway",
]
