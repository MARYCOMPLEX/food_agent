"""
POI 搜索 Mixin - 高德地图 POI 搜索相关功能.

从 poi_enricher.py 拆分，包含搜索策略、结果构建和地址处理。
"""

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from loguru import logger

from xhs_food.contracts import PlaceLookupPort
from xhs_food.domain_packs.food.place import FoodPlacePolicy
from xhs_food.schemas import RestaurantRecommendation

if TYPE_CHECKING:
    from .poi_enricher import EnrichedRestaurant


class POISearchMixin:
    """POI 搜索相关方法的 Mixin 类.

    依赖主类提供异步 ``PlaceLookupPort``，不感知具体地图客户端。
    """

    _place_lookup: PlaceLookupPort
    _food_place_policy = FoodPlacePolicy()

    async def _search_poi(self, name: str, city: str = "") -> dict[str, Any] | None:
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

    def _generate_search_variants(self, name: str, city: str) -> list[tuple]:
        """
        生成多种搜索变体.

        Returns:
            List of (keyword, city, strategy_name)
        """
        return self._food_place_policy.search_variants(name, city)

    def _remove_city_prefix(self, name: str, city: str) -> str:
        """去掉店名中的城市前缀."""
        return self._food_place_policy.remove_city_prefix(name, city)

    def _remove_branch_suffix(self, name: str) -> str:
        """去掉分店后缀，如 (泰丰店)、（总店）."""
        return self._food_place_policy.remove_branch_suffix(name)

    async def _do_poi_search(self, keywords: str, city: str) -> dict[str, Any] | None:
        """执行单次 POI 搜索."""
        try:
            result = await self._place_lookup.lookup(
                keywords=keywords,
                city=city,
                types="050000",  # 餐饮服务
            )

            return self._food_place_policy.select_place(result)

        except Exception as e:
            logger.debug(f"POI search failed: {e}")
            return None

    def _build_enriched(
        self,
        rec: RestaurantRecommendation,
        idx: int,
        poi: dict[str, Any] | None,
    ) -> "EnrichedRestaurant":
        """构建格式化结果."""
        from .poi_enricher import EnrichedRestaurant

        # 从 rec 获取新字段
        must_try = [item.to_dict() for item in rec.must_try] if rec.must_try else []
        black_list = [item.to_dict() for item in rec.black_list] if rec.black_list else []
        stats = (
            rec.stats.to_dict() if rec.stats else {"flavor": "", "cost": "", "wait": "", "env": ""}
        )

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
                with suppress(ValueError, TypeError):
                    enriched.rating = float(poi["rating"])

            # 图片
            if poi.get("photos"):
                enriched.photos = poi["photos"][:5]

            # 用高德 POI 数据补充 stats.cost（如果 LLM 没有提取到）
            if poi.get("cost") and not enriched.stats.get("cost"):
                try:
                    cost_band = self._food_place_policy.cost_band(poi["cost"])
                    if cost_band is not None:
                        enriched.stats["cost"] = cost_band
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
        stats = (
            rec.stats.to_dict() if rec.stats else {"flavor": "", "cost": "", "wait": "", "env": ""}
        )

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

    def _build_address(self, poi: dict[str, Any]) -> str:
        """构建完整地址."""
        return self._food_place_policy.build_address(poi)

    def _extract_city(self, location: str | None) -> str:
        """从位置描述提取城市."""
        return self._food_place_policy.extract_city(location)
