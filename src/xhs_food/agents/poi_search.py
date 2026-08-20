# -*- coding: utf-8 -*-
"""
POI 搜索 Mixin - 高德地图 POI 搜索相关功能.

从 poi_enricher.py 拆分，包含搜索策略、结果构建和地址处理。
"""

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger

from xhs_food.contracts import PlaceLookupPort
from xhs_food.schemas import RestaurantRecommendation

if TYPE_CHECKING:
    from .poi_enricher import EnrichedRestaurant


class POISearchMixin:
    """POI 搜索相关方法的 Mixin 类.

    依赖主类提供异步 ``PlaceLookupPort``，不感知具体地图客户端。
    """

    _place_lookup: PlaceLookupPort

    async def _search_poi(self, name: str, city: str = "") -> Optional[Dict[str, Any]]:
        """
        搜索店铺 POI 信息（多策略广撒网模式）.

        尝试多种搜索策略，直到找到结果：
        1. 精确店名 + 城市限制
        2. 去掉城市前缀后的店名
        3. 去掉常见后缀（分店名）
        4. 不限城市广搜
        """
        # 生成多种搜索关键词
        search_variants = self._generate_search_variants(name, city)

        for variant_name, variant_city, strategy in search_variants:
            poi = await self._do_poi_search(variant_name, variant_city)
            if poi:
                logger.debug(f"[POI] 策略 '{strategy}' 成功: {variant_name}")
                return poi

        logger.debug(f"[POI] 所有策略都未找到: {name}")
        return None

    def _generate_search_variants(self, name: str, city: str) -> List[tuple]:
        """
        生成多种搜索变体.

        Returns:
            List of (keyword, city, strategy_name)
        """
        variants = []

        # 策略1: 原始店名 + 指定城市
        variants.append((name, city, "exact_with_city"))

        # 策略2: 去掉城市前缀（如 "成都贡井清香园" → "贡井清香园"）
        name_no_city = self._remove_city_prefix(name, city)
        if name_no_city != name:
            variants.append((name_no_city, city, "no_city_prefix"))

        # 策略3: 去掉分店后缀（如 "清香园(泰丰店)" → "清香园"）
        name_no_suffix = self._remove_branch_suffix(name)
        if name_no_suffix != name:
            variants.append((name_no_suffix, city, "no_branch_suffix"))

        # 策略4: 去掉城市前缀和分店后缀
        clean_name = self._remove_branch_suffix(name_no_city)
        if clean_name != name and clean_name not in [v[0] for v in variants]:
            variants.append((clean_name, city, "clean_name"))

        # 策略5: 不限城市广搜（最后的兜底）
        if city:
            variants.append((name, "", "no_city_limit"))

        return variants

    def _remove_city_prefix(self, name: str, city: str) -> str:
        """去掉店名中的城市前缀."""
        if not city:
            return name

        # 常见城市名
        cities = [
            city,
            "北京", "上海", "广州", "深圳", "成都", "重庆", "杭州", "武汉",
            "西安", "南京", "天津", "苏州", "郑州", "长沙", "东莞", "沈阳",
            "达州", "自贡", "泸州", "绵阳", "德阳", "宜宾", "南充", "乐山",
            "蒙自", "昆明", "大理", "丽江",
        ]

        for c in cities:
            if name.startswith(c):
                return name[len(c):]

        return name

    def _remove_branch_suffix(self, name: str) -> str:
        """去掉分店后缀，如 (泰丰店)、（总店）."""
        # 匹配括号内的分店名
        clean = re.sub(r'[\(（][^)）]*[店分部号馆][\)）]$', '', name)
        # 也处理不带括号的情况，如 "xx总店"
        clean = re.sub(r'[总分新老][店]$', '', clean)
        return clean.strip()

    async def _do_poi_search(self, keywords: str, city: str) -> Optional[Dict[str, Any]]:
        """执行单次 POI 搜索."""
        try:
            result = await self._place_lookup.lookup(
                keywords=keywords,
                city=city,
                types="050000",  # 餐饮服务
            )

            if not isinstance(result, Mapping) or "error" in result:
                return None

            pois = result.get("pois", [])
            if not isinstance(pois, list) or not pois:
                return None

            # 只取第一个（最匹配的）
            first = pois[0]
            return dict(first) if isinstance(first, Mapping) else None

        except Exception as e:
            logger.debug(f"POI search failed: {e}")
            return None

    def _build_enriched(
        self,
        rec: RestaurantRecommendation,
        idx: int,
        poi: Optional[Dict[str, Any]],
    ) -> "EnrichedRestaurant":
        """构建格式化结果."""
        from .poi_enricher import EnrichedRestaurant

        # 从 rec 获取新字段
        must_try = [item.to_dict() for item in rec.must_try] if rec.must_try else []
        black_list = [item.to_dict() for item in rec.black_list] if rec.black_list else []
        stats = rec.stats.to_dict() if rec.stats else {"flavor": "", "cost": "", "wait": "", "env": ""}

        # 使用 LLM 提取的 pros/cons/tags，如果为空则 fallback 到 features
        pros = rec.pros if rec.pros else rec.features[:5] if rec.features else []
        cons = rec.cons if rec.cons else []
        tags = rec.tags if rec.tags else rec.features[:5] if rec.features else []

        # 基础信息
        enriched = EnrichedRestaurant(
            index=idx,
            name=rec.name,
            trust_score=rec.confidence * 10,
            one_liner=", ".join(rec.features[:2]) if rec.features else "",
            tags=tags,
            pros=pros,
            cons=cons,
            warning=rec.filter_reason,
            source_notes=rec.source_notes,
            # 新字段
            must_try=must_try,
            black_list=black_list,
            stats=stats,
        )

        # 如果有 POI 信息，补充详情
        if poi:
            enriched.alias = poi.get("alias")
            enriched.address = self._build_address(poi)
            enriched.location = poi.get("location")
            enriched.city = poi.get("cityname", "")
            enriched.district = poi.get("adname", "")
            enriched.business_area = poi.get("business_area", "")
            enriched.tel = poi.get("tel")
            enriched.open_time = poi.get("open_time")
            enriched.cost = poi.get("cost")

            # 评分
            if poi.get("rating"):
                try:
                    enriched.rating = float(poi["rating"])
                except (ValueError, TypeError):
                    pass

            # 图片
            if poi.get("photos"):
                enriched.photos = poi["photos"][:5]

            # 用高德 POI 数据补充 stats.cost（如果 LLM 没有提取到）
            if poi.get("cost") and not enriched.stats.get("cost"):
                try:
                    cost_num = float(poi["cost"])
                    if cost_num < 30:
                        enriched.stats["cost"] = "$"
                    elif cost_num < 80:
                        enriched.stats["cost"] = "$$"
                    else:
                        enriched.stats["cost"] = "$$$"
                except (ValueError, TypeError):
                    pass
        else:
            # 没有 POI，使用原始位置
            enriched.address = rec.location or ""

        return enriched

    def _format_basic(self, rec: RestaurantRecommendation, idx: int) -> "EnrichedRestaurant":
        """基础格式化（无 POI 信息）."""
        from .poi_enricher import EnrichedRestaurant

        # 从 rec 获取新字段
        must_try = [item.to_dict() for item in rec.must_try] if rec.must_try else []
        black_list = [item.to_dict() for item in rec.black_list] if rec.black_list else []
        stats = rec.stats.to_dict() if rec.stats else {"flavor": "", "cost": "", "wait": "", "env": ""}

        # 使用 LLM 提取的 pros/cons/tags
        pros = rec.pros if rec.pros else rec.features[:5] if rec.features else []
        cons = rec.cons if rec.cons else []
        tags = rec.tags if rec.tags else rec.features[:5] if rec.features else []

        return EnrichedRestaurant(
            index=idx,
            name=rec.name,
            address=rec.location or "",
            trust_score=rec.confidence * 10,
            one_liner=", ".join(rec.features[:2]) if rec.features else "",
            tags=tags,
            pros=pros,
            cons=cons,
            warning=rec.filter_reason,
            source_notes=rec.source_notes,
            # 新字段
            must_try=must_try,
            black_list=black_list,
            stats=stats,
        )

    def _build_address(self, poi: Dict[str, Any]) -> str:
        """构建完整地址."""
        parts = []
        for key in ["pname", "cityname", "adname", "address"]:
            val = poi.get(key)
            if val and val not in parts:
                parts.append(val)
        return "".join(parts)

    def _extract_city(self, location: Optional[str]) -> str:
        """从位置描述提取城市."""
        if not location:
            return ""

        cities = [
            "北京", "上海", "广州", "深圳", "成都", "重庆", "杭州", "武汉",
            "西安", "南京", "天津", "苏州", "郑州", "长沙", "东莞", "沈阳",
            "达州", "自贡", "泸州", "绵阳", "德阳", "宜宾", "南充", "乐山",
        ]

        for city in cities:
            if city in location:
                return city

        return ""
