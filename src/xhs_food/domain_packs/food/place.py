"""Pure Food place matching and public projection policy."""

from __future__ import annotations

import re
from collections.abc import Mapping

_KNOWN_CITIES = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "成都",
    "重庆",
    "杭州",
    "武汉",
    "西安",
    "南京",
    "天津",
    "苏州",
    "郑州",
    "长沙",
    "东莞",
    "沈阳",
    "达州",
    "自贡",
    "泸州",
    "绵阳",
    "德阳",
    "宜宾",
    "南充",
    "乐山",
    "蒙自",
    "昆明",
    "大理",
    "丽江",
)


class FoodPlacePolicy:
    """Own Food-specific POI matching without owning network access."""

    version = "food-place-projection/v1"

    def search_variants(self, name: str, city: str) -> list[tuple[str, str, str]]:
        variants = [(name, city, "exact_with_city")]
        name_no_city = self.remove_city_prefix(name, city)
        if name_no_city != name:
            variants.append((name_no_city, city, "no_city_prefix"))
        name_no_suffix = self.remove_branch_suffix(name)
        if name_no_suffix != name:
            variants.append((name_no_suffix, city, "no_branch_suffix"))
        clean_name = self.remove_branch_suffix(name_no_city)
        if clean_name != name and clean_name not in [variant[0] for variant in variants]:
            variants.append((clean_name, city, "clean_name"))
        if city:
            variants.append((name, "", "no_city_limit"))
        return variants

    def remove_city_prefix(self, name: str, city: str) -> str:
        if not city:
            return name
        for candidate in (city, *_KNOWN_CITIES):
            if name.startswith(candidate):
                return name[len(candidate) :]
        return name

    def remove_branch_suffix(self, name: str) -> str:
        clean = re.sub(r"[\(（][^)）]*[店分部号馆][\)）]$", "", name)
        clean = re.sub(r"[总分新老][店]$", "", clean)
        return clean.strip()

    def select_place(self, payload: object) -> dict[str, object] | None:
        if not isinstance(payload, Mapping) or "error" in payload:
            return None
        places = payload.get("pois", [])
        if not isinstance(places, list) or not places:
            return None
        first = places[0]
        return dict(first) if isinstance(first, Mapping) else None

    def build_address(self, place: Mapping[str, object]) -> str:
        parts: list[object] = []
        for key in ("pname", "cityname", "adname", "address"):
            value = place.get(key)
            if value and value not in parts:
                parts.append(value)
        return "".join(str(part) for part in parts)

    def cost_band(self, value: object) -> str | None:
        try:
            cost = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if cost < 30:
            return "$"
        if cost < 80:
            return "$$"
        return "$$$"

    def extract_city(self, location: str | None) -> str:
        if not location:
            return ""
        for city in _KNOWN_CITIES[:-4]:
            if city in location:
                return city
        return ""


__all__ = ["FoodPlacePolicy"]
