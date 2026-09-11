"""Common cross-cutting utilities (categories, JSON extraction, location)."""
from .categories import CATEGORY_MAPPING, normalize_category, expand_category_keywords
from .json_extract import extract_json
from .location import KNOWN_CITIES, extract_city_from_location

__all__ = [
    "CATEGORY_MAPPING",
    "normalize_category",
    "expand_category_keywords",
    "extract_json",
    "KNOWN_CITIES",
    "extract_city_from_location",
]
