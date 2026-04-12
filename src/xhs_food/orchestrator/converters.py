"""
数据转换工具函数.
"""

from __future__ import annotations

from typing import Any, Dict

from xhs_food.schemas import (
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
)


def dict_to_recommendation(d: Dict[str, Any]) -> RestaurantRecommendation:
    """将字典转换为 RestaurantRecommendation."""
    from xhs_food.schemas import MustTryItem, BlackListItem, ShopStats

    wa_dict = d.get("wanghong_analysis")
    wanghong = None
    if wa_dict:
        try:
            score = WanghongScore(wa_dict.get("score", "unknown"))
        except ValueError:
            score = WanghongScore.UNKNOWN
        wanghong = WanghongAnalysis(
            score=score,
            confidence=wa_dict.get("confidence", 0.5),
            reasons=wa_dict.get("reasons", []),
        )

    # 转换 must_try 列表
    must_try_list = []
    for item in d.get("mustTry", []) or d.get("must_try", []) or []:
        if isinstance(item, dict):
            must_try_list.append(MustTryItem(
                name=item.get("name", ""),
                reason=item.get("reason", ""),
                img=item.get("img", ""),
            ))

    # 转换 black_list 列表
    black_list = []
    for item in d.get("blackList", []) or d.get("black_list", []) or []:
        if isinstance(item, dict):
            black_list.append(BlackListItem(
                name=item.get("name", ""),
                reason=item.get("reason", ""),
            ))

    # 转换 stats
    stats_dict = d.get("stats") or {}
    stats = None
    if stats_dict:
        stats = ShopStats(
            flavor=stats_dict.get("flavor", ""),
            cost=stats_dict.get("cost", ""),
            wait=stats_dict.get("wait", ""),
            env=stats_dict.get("env", ""),
        )

    return RestaurantRecommendation(
        name=d.get("name", "未知"),
        location=d.get("location"),
        features=d.get("features", []),
        source_notes=d.get("source_notes", []) or d.get("sourceNotes", []) or [],
        confidence=d.get("confidence", 0.5),
        wanghong_analysis=wanghong,
        is_recommended=d.get("is_recommended", True),
        filter_reason=d.get("filter_reason"),
        pros=d.get("pros", []),
        cons=d.get("cons", []),
        tags=d.get("tags", []),
        must_try=must_try_list,
        black_list=black_list,
        stats=stats,
    )
