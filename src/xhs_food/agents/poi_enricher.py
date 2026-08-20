# -*- coding: utf-8 -*-
"""POI 信息补充 Agent (流式输出版).

使用高德地图 API 补充店铺的详细 POI 信息，并格式化输出。
- 先查数据库缓存，避免重复调用高德 API
- 数据库未命中时调用高德 API，并发受 ``settings.poi_concurrency`` 限制
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, cast

from loguru import logger

from xhs_food.config import settings
from xhs_food.contracts import ContractPayload, PlaceCacheRepositoryPort, PlaceLookupPort
from xhs_food.schemas import RestaurantRecommendation

from .poi_search import POISearchMixin


class _LegacyAmapInjectionAdapter:
    """Keep the legacy constructor injection while exposing only the async port."""

    def __init__(self, client: object) -> None:
        search = getattr(client, "search_poi", None)
        if not callable(search):
            raise TypeError("amap_api must expose search_poi or implement PlaceLookupPort")
        self._search: Callable[..., object] = search

    async def lookup(
        self, *, keywords: str, city: str = "", types: str = "050000"
    ) -> ContractPayload | None:
        result = await asyncio.to_thread(
            self._search,
            keywords=keywords,
            city=city,
            types=types,
        )
        return cast(ContractPayload | None, result)


class _UnavailablePlaceLookup:
    async def lookup(
        self, *, keywords: str, city: str = "", types: str = "050000"
    ) -> ContractPayload | None:
        del keywords, city, types
        raise RuntimeError("default place lookup is not configured")


class _UnavailablePlaceCache:
    async def get_cached_place_by_name(self, name: str) -> ContractPayload | None:
        del name
        return None


_place_lookup_factory: Callable[[], PlaceLookupPort] | None = None
_place_cache_factory: Callable[[], PlaceCacheRepositoryPort] | None = None


@dataclass
class EnrichedRestaurant:
    """格式化后的店铺信息（用于前端展示）."""

    # 基本信息
    index: int  # 显示顺序（非数据库 ID）
    name: str
    alias: Optional[str] = None

    # 位置
    address: str = ""
    location: Optional[str] = None  # 经纬度
    city: str = ""
    district: str = ""
    business_area: str = ""

    # 联系
    tel: Optional[str] = None

    # 营业信息
    rating: Optional[float] = None
    cost: Optional[str] = None
    open_time: Optional[str] = None

    # 展示信息
    trust_score: float = 7.0
    one_liner: str = ""
    tags: List[str] = field(default_factory=list)
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    warning: Optional[str] = None

    # 图片
    photos: List[Dict[str, str]] = field(default_factory=list)

    # 来源
    source_notes: List[str] = field(default_factory=list)

    # 新增字段
    must_try: List[Dict[str, str]] = field(default_factory=list)  # 必点推荐
    black_list: List[Dict[str, str]] = field(default_factory=list)  # 避雷菜品
    stats: Dict[str, str] = field(
        default_factory=lambda: {"flavor": "", "cost": "", "wait": "", "env": ""}
    )  # 综合评级

    def __post_init__(self):
        self.tags = self.tags or []
        self.pros = self.pros or []
        self.cons = self.cons or []
        self.photos = self.photos or []
        self.source_notes = self.source_notes or []
        self.must_try = self.must_try or []
        self.black_list = self.black_list or []
        self.stats = self.stats or {"flavor": "", "cost": "", "wait": "", "env": ""}

    def to_dict(self) -> Dict[str, Any]:
        """转换为 API 响应格式.

        注意：不包含 id 字段，由数据库层根据 name+tel 生成 hash ID。
        """
        return {
            # 不输出 id，由 user_storage.upsert_restaurant 生成 hash ID
            "name": self.name,
            "chnName": self.alias or self.name,
            "address": self.address,
            "location": self.location,
            "city": self.city,
            "district": self.district,
            "businessArea": self.business_area,
            "tel": self.tel,
            "rating": self.rating,
            "cost": self.cost,
            "openTime": self.open_time,
            "trustScore": round(self.trust_score, 1),
            "oneLiner": self.one_liner,
            "tags": self.tags,
            "pros": self.pros,
            "cons": self.cons,
            "warning": self.warning,
            "photos": self.photos,
            "sourceNotes": self.source_notes,
            # 新增字段
            "mustTry": self.must_try,
            "blackList": self.black_list,
            "stats": self.stats,
        }

class POIEnricherAgent(POISearchMixin):
    """POI 信息补充 Agent（流式输出）."""

    def __init__(self, amap_api: object | None = None):
        """
        初始化 POI 补充 Agent.

        Args:
            amap_api: 旧高德客户端注入点；也接受实现 ``PlaceLookupPort`` 的对象。
        """
        default_cache: PlaceCacheRepositoryPort | None = None
        self._uses_default_place_lookup = amap_api is None
        if amap_api is None:
            if _place_lookup_factory is not None:
                self._place_lookup = _place_lookup_factory()
            else:
                from xhs_food.composition.legacy_poi import build_legacy_poi_ports

                self._place_lookup, default_cache = build_legacy_poi_ports()
        elif isinstance(amap_api, PlaceLookupPort):
            self._place_lookup = amap_api
        else:
            self._place_lookup = _LegacyAmapInjectionAdapter(amap_api)
        self._place_cache = (
            _place_cache_factory()
            if _place_cache_factory
            else default_cache or _UnavailablePlaceCache()
        )

    def configure_default_place_lookup(self, place_lookup: PlaceLookupPort) -> None:
        """Refresh only instances that were created from default composition wiring."""
        if self._uses_default_place_lookup:
            self._place_lookup = place_lookup

    def configure_place_cache(self, place_cache: PlaceCacheRepositoryPort) -> None:
        """Install the Composition Root-owned optional place-cache repository."""
        self._place_cache = place_cache

    async def enrich_stream(
        self,
        recommendations: List[RestaurantRecommendation],
        city: str = "",
    ) -> AsyncGenerator[EnrichedRestaurant, None]:
        """Concurrently enrich each recommendation and yield as they finish.

        Concurrency is capped by ``settings.poi_concurrency``; results are
        yielded in completion order, with original index preserved on the
        :class:`EnrichedRestaurant` payload.
        """
        total = len(recommendations)
        if total == 0:
            return

        semaphore = asyncio.Semaphore(max(1, settings.poi_concurrency))
        logger.info(
            f"[POIEnricher] processing {total} restaurants "
            f"(concurrency={settings.poi_concurrency})"
        )

        async def _one(idx: int, rec: RestaurantRecommendation) -> EnrichedRestaurant:
            async with semaphore:
                try:
                    return await self._enrich_and_format(rec, idx + 1, city)
                except Exception as exc:
                    logger.warning(f"[POIEnricher] {rec.name} failed: {exc}")
                    return self._format_basic(rec, idx + 1)

        tasks = [asyncio.create_task(_one(i, r)) for i, r in enumerate(recommendations)]
        try:
            for coro in asyncio.as_completed(tasks):
                yield await coro
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    async def enrich(
        self,
        recommendations: List[RestaurantRecommendation],
        city: str = "",
    ) -> List[EnrichedRestaurant]:
        """批量补充并格式化店铺信息（非流式）."""
        results: List[EnrichedRestaurant] = []
        async for enriched in self.enrich_stream(recommendations, city):
            results.append(enriched)
        results.sort(key=lambda r: r.index)
        return results

    async def _enrich_and_format(
        self,
        rec: RestaurantRecommendation,
        idx: int,
        city: str = "",
    ) -> EnrichedRestaurant:
        """补充并格式化单个店铺.

        优先检查数据库缓存，存在则直接使用，节省高德 API 调用。
        """
        # 1. 先查数据库缓存
        cached = await self._get_cached_poi(rec.name)
        if cached:
            logger.debug(f"[POIEnricher] 命中数据库缓存: {rec.name}")
            return self._build_from_cached(rec, idx, cached)

        # 2. 数据库无缓存，调用高德 API
        search_city = city or self._extract_city(rec.location)
        poi = await self._search_poi(rec.name, search_city)

        # 构建格式化结果
        return self._build_enriched(rec, idx, poi)

    async def _get_cached_poi(self, name: str) -> Optional[Dict[str, Any]]:
        """从数据库查询已缓存的餐厅 POI 信息.

        使用名称模糊匹配，不依赖地址字段（因为地址可能为空或无效值如"未明确"）。
        """
        try:
            return cast(
                Optional[Dict[str, Any]],
                await self._place_cache.get_cached_place_by_name(name),
            )
        except Exception as e:
            logger.debug(f"[POIEnricher] 查询缓存失败: {e}")
            return None

    def _build_from_cached(
        self,
        rec: RestaurantRecommendation,
        idx: int,
        cached: Dict[str, Any],
    ) -> EnrichedRestaurant:
        """从数据库缓存构建结果."""
        import json

        # 从 rec 获取新字段
        must_try = [item.to_dict() for item in rec.must_try] if rec.must_try else []
        black_list = [item.to_dict() for item in rec.black_list] if rec.black_list else []
        stats = rec.stats.to_dict() if rec.stats else {"flavor": "", "cost": "", "wait": "", "env": ""}

        # 使用 LLM 提取的 pros/cons/tags，如果为空则 fallback
        pros = rec.pros if rec.pros else rec.features[:5] if rec.features else []
        cons = rec.cons if rec.cons else []
        tags = rec.tags if rec.tags else rec.features[:5] if rec.features else []

        # 解析 JSONB 字段
        photos = cached.get("photos", [])
        if isinstance(photos, str):
            try:
                photos = json.loads(photos)
            except json.JSONDecodeError:
                photos = []

        return EnrichedRestaurant(
            index=idx,
            name=rec.name,
            alias=cached.get("alias"),
            address=cached.get("address", rec.location or ""),
            location=cached.get("location"),
            city=cached.get("city", ""),
            district=cached.get("district", ""),
            business_area=cached.get("business_area", ""),
            tel=cached.get("tel"),
            rating=cached.get("rating"),
            cost=cached.get("cost"),
            open_time=cached.get("open_time"),
            trust_score=rec.confidence * 10,
            one_liner=", ".join(rec.features[:2]) if rec.features else "",
            tags=tags,
            pros=pros,
            cons=cons,
            warning=rec.filter_reason,
            photos=photos[:5] if photos else [],
            source_notes=rec.source_notes,
            must_try=must_try,
            black_list=black_list,
            stats=stats,
        )


# 单例
_poi_enricher: Optional[POIEnricherAgent] = None


def configure_poi_place_lookup_factory(
    factory: Callable[[], PlaceLookupPort],
) -> None:
    """Install the Composition Root-owned default Place lookup factory."""
    global _place_lookup_factory
    _place_lookup_factory = factory
    if _poi_enricher is not None:
        _poi_enricher.configure_default_place_lookup(factory())


def configure_poi_place_cache_factory(
    factory: Callable[[], PlaceCacheRepositoryPort],
) -> None:
    """Install the Composition Root-owned optional place-cache factory."""
    global _place_cache_factory
    _place_cache_factory = factory
    if _poi_enricher is not None:
        _poi_enricher.configure_place_cache(factory())


def get_poi_enricher() -> POIEnricherAgent:
    """获取 POIEnricherAgent 单例."""
    global _poi_enricher
    if _poi_enricher is None:
        _poi_enricher = POIEnricherAgent()
    return _poi_enricher
