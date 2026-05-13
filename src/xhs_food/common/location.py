# -*- coding: utf-8 -*-
"""Location/city extraction helpers."""
from __future__ import annotations

from typing import Iterable

KNOWN_CITIES: tuple[str, ...] = (
    # 直辖市
    "北京", "上海", "天津", "重庆",
    # 省会及主要城市（按地理区域）
    "成都", "杭州", "南京", "广州", "深圳", "武汉", "西安", "长沙", "郑州",
    "苏州", "厦门", "青岛", "大连", "沈阳", "哈尔滨", "济南", "合肥", "福州",
    "南昌", "长春", "石家庄", "太原", "兰州", "昆明", "贵阳", "南宁", "海口",
    # 川渝常见地级市
    "达州", "自贡", "泸州", "绵阳", "德阳", "南充", "宜宾", "乐山", "雅安",
    "内江", "广元", "遂宁", "眉山", "资阳", "巴中", "广安", "万州", "涪陵",
)


def extract_city_from_location(
    location: str | None,
    extra_cities: Iterable[str] = (),
) -> str:
    """Return the first known city substring found in ``location``.

    Args:
        location: Free-form location text (address, district, etc).
        extra_cities: Additional city names to match before the built-in list.
    """
    if not location:
        return ""
    candidates = (*extra_cities, *KNOWN_CITIES)
    for city in candidates:
        if city and city in location:
            return city
    return ""
