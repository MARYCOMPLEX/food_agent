"""Unit tests for :mod:`xhs_food.common` helpers."""

from __future__ import annotations

import pytest

from xhs_food.common import (
    expand_category_keywords,
    extract_city_from_location,
    extract_json,
    normalize_category,
)


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_returns_none_for_empty_string(self) -> None:
        # Arrange / Act / Assert
        assert extract_json("") is None

    def test_parses_direct_json_object(self) -> None:
        # Arrange
        raw = '{"location": "成都", "food_type": "火锅"}'

        # Act
        parsed = extract_json(raw)

        # Assert
        assert parsed == {"location": "成都", "food_type": "火锅"}

    def test_parses_direct_json_array(self) -> None:
        # ``json.loads`` succeeds for arrays too — the helper just returns
        # whatever ``json.loads`` produced.
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_parses_json_inside_fenced_json_block(self) -> None:
        # Arrange
        raw = '前缀文本\n```json\n{"a": 1}\n```\n后缀'

        # Act
        parsed = extract_json(raw)

        # Assert
        assert parsed == {"a": 1}

    def test_parses_json_inside_plain_fenced_block(self) -> None:
        # Arrange
        raw = "Here:\n```\n{\"b\": 2}\n```"

        # Act
        parsed = extract_json(raw)

        # Assert
        assert parsed == {"b": 2}

    def test_falls_back_to_brace_search(self) -> None:
        # Arrange — JSON embedded in surrounding prose, no fences
        raw = '解析后的意图: {"location": "重庆"} 仅此而已。'

        # Act
        parsed = extract_json(raw)

        # Assert
        assert parsed == {"location": "重庆"}

    def test_returns_none_for_malformed_json(self) -> None:
        # Arrange — looks like JSON but is invalid
        raw = "{location: 成都"  # missing quotes + closing brace

        # Act
        parsed = extract_json(raw)

        # Assert
        assert parsed is None


# ---------------------------------------------------------------------------
# normalize_category
# ---------------------------------------------------------------------------


class TestNormalizeCategory:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("我想吃火锅", "火锅"),
            ("想吃点炒菜的", "炒菜"),
            ("来点烧烤", "烧烤"),
            ("换成川菜", "川菜"),
            ("只要面食", "面食"),
            ("只看甜品", "甜品"),
            ("有没有小吃类", "小吃"),
            ("火锅类", "火锅"),
            ("烧烤的", "烧烤"),
        ],
    )
    def test_strips_filler_and_suffix(self, raw: str, expected: str) -> None:
        # Arrange / Act
        result = normalize_category(raw)

        # Assert
        assert result == expected

    def test_handles_empty_input(self) -> None:
        # Arrange / Act / Assert
        assert normalize_category("") == ""

    def test_keeps_clean_category_unchanged(self) -> None:
        # Arrange / Act / Assert
        assert normalize_category("火锅") == "火锅"


# ---------------------------------------------------------------------------
# expand_category_keywords
# ---------------------------------------------------------------------------


class TestExpandCategoryKeywords:
    def test_known_category_expands_with_synonyms(self) -> None:
        # Arrange / Act
        result = expand_category_keywords("火锅")

        # Assert
        assert "火锅" in result
        assert "串串" in result
        assert "冒菜" in result
        # No duplicates
        assert len(result) == len(set(result))

    def test_unknown_category_returns_just_input(self) -> None:
        # Arrange / Act
        result = expand_category_keywords("外星菜")

        # Assert
        assert result == ["外星菜"]

    def test_empty_input_returns_empty_list(self) -> None:
        # Arrange / Act / Assert
        assert expand_category_keywords("") == []

    def test_first_entry_is_original_input(self) -> None:
        # Arrange / Act
        result = expand_category_keywords("烧烤")

        # Assert
        assert result[0] == "烧烤"


# ---------------------------------------------------------------------------
# extract_city_from_location
# ---------------------------------------------------------------------------


class TestExtractCityFromLocation:
    @pytest.mark.parametrize(
        "location, expected",
        [
            ("成都市武侯区", "成都"),
            ("重庆渝中区解放碑", "重庆"),
            ("北京朝阳", "北京"),
            ("上海浦东新区", "上海"),
        ],
    )
    def test_known_cities(self, location: str, expected: str) -> None:
        # Arrange / Act
        result = extract_city_from_location(location)

        # Assert
        assert result == expected

    def test_returns_empty_for_none_or_empty(self) -> None:
        # Arrange / Act / Assert
        assert extract_city_from_location(None) == ""
        assert extract_city_from_location("") == ""

    def test_returns_empty_for_unknown_city(self) -> None:
        # Arrange / Act
        result = extract_city_from_location("某偏远小镇XX村")

        # Assert
        assert result == ""

    def test_extra_cities_take_precedence(self) -> None:
        # Arrange — extra_cities are checked before the built-in list
        location = "新城区成都路"

        # Act — pass "新城" as an extra city; it appears first in the text
        result = extract_city_from_location(location, extra_cities=["新城"])

        # Assert — extra_cities win when their substring appears
        assert result == "新城"

    def test_first_known_city_in_iteration_wins(self) -> None:
        # When multiple known cities appear, the iteration order of
        # KNOWN_CITIES determines precedence — verify behavior is stable
        # (first match in the tuple order).
        from xhs_food.common.location import KNOWN_CITIES

        # Arrange — pick two cities from KNOWN_CITIES and combine
        first = KNOWN_CITIES[0]
        later = KNOWN_CITIES[5]
        location = f"{later} 和 {first}"

        # Act
        result = extract_city_from_location(location)

        # Assert — whichever appears first in KNOWN_CITIES wins
        assert result == first
