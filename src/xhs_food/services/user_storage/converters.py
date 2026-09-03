# -*- coding: utf-8 -*-
"""Row-to-model converters for user storage."""

from __future__ import annotations

import json
from typing import Any

from .models import Favorite, Restaurant, SearchHistory, User


def _parse_jsonb(value: Any, default: Any = None):
    """Parse a JSONB field that might be a string or already parsed."""
    if default is None:
        default = []
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


class ConverterMixin:
    """Mixin providing row-to-model conversion methods.

    Expects the host class to define:
        ANONYMOUS_USER_ID: str
        ANONYMOUS_DEVICE_ID: str
    """

    def _anonymous_user(self) -> User:
        """Create static anonymous user for fallback."""
        return User(
            id=self.ANONYMOUS_USER_ID,
            device_id=self.ANONYMOUS_DEVICE_ID,
            name="Anonymous",
        )

    async def get_anonymous_user(self) -> User:
        """Get anonymous user from database (or create if missing)."""
        # Try to get from DB first to get persisted settings
        user = await self.get_user(self.ANONYMOUS_USER_ID)
        if user:
            return user

        # Fallback if DB fails or empty (should be initialized though)
        return self._anonymous_user()

    def _row_to_user(self, row) -> User:
        """Convert database row to User."""
        settings = _parse_jsonb(row["settings"], {})

        return User(
            id=str(row["id"]),
            device_id=row["device_id"],
            name=row["name"] or "Guest",
            username=row.get("username"),
            email=row["email"],
            avatar=row["avatar"],
            location=row["location"],
            settings=settings,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_favorite(self, row) -> Favorite:
        """Convert database row to Favorite (basic, no join)."""
        return Favorite(
            id=row["id"],
            user_id=str(row["user_id"]),
            restaurant_id=row["restaurant_id"],
            restaurant=None,
            created_at=row["created_at"],
        )

    def _row_to_favorite_with_restaurant(self, row) -> Favorite:
        """Convert joined database row to Favorite with restaurant data."""
        # Build restaurant dict from joined columns
        restaurant_data = None
        if row.get("name"):
            tags = _parse_jsonb(row.get("tags", []))
            pros = _parse_jsonb(row.get("pros", []))
            cons = _parse_jsonb(row.get("cons", []))
            must_try = _parse_jsonb(row.get("must_try", []))
            black_list = _parse_jsonb(row.get("black_list", []))
            stats = _parse_jsonb(row.get("stats", {}), {})
            photos = _parse_jsonb(row.get("photos", []))
            source_notes = _parse_jsonb(row.get("source_notes", []))
            provider_refs = _parse_jsonb(row.get("provider_refs", {}), {})
            recommended_dishes = _parse_jsonb(row.get("recommended_dishes", []))
            promotions = _parse_jsonb(row.get("promotions", []))
            profile_metadata = _parse_jsonb(row.get("profile_metadata", {}), {})
            review_completeness = _parse_jsonb(row.get("review_completeness", {}), {})
            profile_gaps = _parse_jsonb(row.get("profile_gaps", []))

            trust_score = row.get("trust_score")
            restaurant_data = {
                "id": row["restaurant_id"],
                "name": row["name"],
                "chnName": row.get("alias") or row["name"],
                "address": row.get("address"),
                "location": row.get("location"),
                "city": row.get("city"),
                "district": row.get("district"),
                "region": row.get("region"),
                "businessArea": row.get("business_area"),
                "tel": row.get("tel"),
                "rating": row.get("rating"),
                "cost": row.get("cost"),
                "openTime": row.get("open_time"),
                "trustScore": round(trust_score, 1) if trust_score else None,
                "oneLiner": row.get("one_liner"),
                "tags": tags,
                "pros": pros,
                "cons": cons,
                "warning": row.get("warning"),
                "photos": photos,
                "sourceNotes": source_notes,
                "mustTry": must_try,
                "blackList": black_list,
                "stats": stats,
                "providerRefs": provider_refs,
                "profileUrl": row.get("profile_url"),
                "sourceUrl": row.get("source_url"),
                "imageUrl": row.get("image_url"),
                "category": row.get("category"),
                "reviewCount": row.get("review_count"),
                "averagePrice": row.get("average_price"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "coordinateSystem": row.get("coordinate_system"),
                "geo": _parse_jsonb(row.get("geo", {}), {}),
                "recommendedDishes": recommended_dishes,
                "promotions": promotions,
                "profileMetadata": profile_metadata,
                "reviewCompleteness": review_completeness,
                "profileGaps": profile_gaps,
                "sourcePayload": _parse_jsonb(row.get("source_payload"), None),
                "sourceUpdatedAt": row.get("source_updated_at"),
                "profileFetchedAt": row.get("profile_fetched_at"),
                "profileRefreshStatus": row.get("profile_refresh_status"),
            }

        return Favorite(
            id=row["id"],
            user_id=str(row["user_id"]),
            restaurant_id=row["restaurant_id"],
            restaurant=restaurant_data,
            created_at=row["created_at"],
        )

    def _row_to_restaurant(self, row) -> Restaurant:
        """Convert database row to Restaurant."""
        tags = _parse_jsonb(row.get("tags", []))
        pros = _parse_jsonb(row.get("pros", []))
        cons = _parse_jsonb(row.get("cons", []))
        must_try = _parse_jsonb(row.get("must_try", []))
        black_list = _parse_jsonb(row.get("black_list", []))
        stats = _parse_jsonb(row.get("stats", {}), {})
        photos = _parse_jsonb(row.get("photos", []))
        source_notes = _parse_jsonb(row.get("source_notes", []))
        provider_refs = _parse_jsonb(row.get("provider_refs", {}), {})
        recommended_dishes = _parse_jsonb(row.get("recommended_dishes", []))
        promotions = _parse_jsonb(row.get("promotions", []))
        profile_metadata = _parse_jsonb(row.get("profile_metadata", {}), {})
        review_completeness = _parse_jsonb(row.get("review_completeness", {}), {})
        profile_gaps = _parse_jsonb(row.get("profile_gaps", []))

        return Restaurant(
            id=row["id"],
            name=row["name"],
            alias=row.get("alias"),
            tel=row.get("tel"),
            address=row.get("address"),
            city=row.get("city"),
            district=row.get("district"),
            region=row.get("region"),
            business_area=row.get("business_area"),
            location=row.get("location"),
            rating=row.get("rating"),
            cost=row.get("cost"),
            open_time=row.get("open_time"),
            trust_score=row.get("trust_score"),
            one_liner=row.get("one_liner"),
            tags=tags,
            pros=pros,
            cons=cons,
            warning=row.get("warning"),
            must_try=must_try,
            black_list=black_list,
            stats=stats,
            photos=photos,
            source_notes=source_notes,
            provider_refs=provider_refs,
            profile_url=row.get("profile_url"),
            source_url=row.get("source_url"),
            image_url=row.get("image_url"),
            category=row.get("category"),
            review_count=row.get("review_count"),
            average_price=row.get("average_price"),
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
            coordinate_system=row.get("coordinate_system"),
            geo=_parse_jsonb(row.get("geo", {}), {}),
            recommended_dishes=recommended_dishes,
            promotions=promotions,
            profile_metadata=profile_metadata,
            review_completeness=review_completeness,
            profile_gaps=profile_gaps,
            source_payload=_parse_jsonb(row.get("source_payload"), None),
            source_updated_at=row.get("source_updated_at"),
            profile_fetched_at=row.get("profile_fetched_at"),
            profile_refresh_status=row.get("profile_refresh_status"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_history(self, row) -> SearchHistory:
        """Convert database row to SearchHistory."""
        return SearchHistory(
            id=row["id"],
            user_id=str(row["user_id"]),
            query=row["query"],
            session_id=str(row["session_id"]) if row.get("session_id") else None,
            status=row.get("status", "loading"),
            results_count=row["results_count"] or 0,
            location=row.get("location"),
            created_at=row["created_at"],
            updated_at=row.get("updated_at"),
        )
