# -*- coding: utf-8 -*-
"""
POI 信息补充 Agent (流式输出版).

使用高德地图 API 补充店铺的详细 POI 信息，并格式化输出。
支持流式输出，方便 SSE 端点调用。

优化：
- 先查数据库缓存，避免重复调用高德 API
- 如果数据库有完整 POI 信息，直接使用
"""

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from xhs_food.spider.apis.amap_api import get_amap_api, AmapAPI
from xhs_food.schemas import RestaurantRecommendation
from xhs_food.services.user_storage import generate_restaurant_hash


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
    tags: List[str] = None
    pros: List[str] = None
    cons: List[str] = None
    warning: Optional[str] = None
    
    # 图片
    photos: List[Dict[str, str]] = None
    
    # 来源
    source_notes: List[str] = None
    
    # 新增字段
    must_try: List[Dict[str, str]] = None  # 必点推荐
    black_list: List[Dict[str, str]] = None  # 避雷菜品
    stats: Dict[str, str] = None  # 综合评级
    
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



class POIEnricherAgent:
    """POI 信息补充 Agent（流式输出）."""
    
    def __init__(self, amap_api: Optional[AmapAPI] = None):
        """
        初始化 POI 补充 Agent.
        
        Args:
            amap_api: 高德 API 实例，不传则使用默认单例
        """
        self._amap = amap_api or get_amap_api()
    
    async def enrich_stream(
        self,
        recommendations: List[RestaurantRecommendation],
        city: str = "",
    ) -> AsyncGenerator[EnrichedRestaurant, None]:
        """
        流式补充并格式化店铺信息.
        
        每处理完一个店铺立即 yield，适合 SSE 推送。
        
        Args:
            recommendations: 推荐列表
            city: 城市名称（提高搜索精度）
            
        Yields:
            EnrichedRestaurant: 格式化后的店铺信息
        """
        logger.info(f"[POIEnricher] 开始流式处理 {len(recommendations)} 家店铺...")
        
        for idx, rec in enumerate(recommendations):
            try:
                enriched = await self._enrich_and_format(rec, idx + 1, city)
                logger.debug(f"[POIEnricher] 完成 {idx + 1}/{len(recommendations)}: {rec.name}")
                yield enriched
            except Exception as e:
                logger.warning(f"[POIEnricher] 处理 {rec.name} 失败: {e}")
                # 失败时返回基础格式化结果
                yield self._format_basic(rec, idx + 1)
        
        logger.info(f"[POIEnricher] 流式处理完成")
    
    async def enrich(
        self,
        recommendations: List[RestaurantRecommendation],
        city: str = "",
    ) -> List[EnrichedRestaurant]:
        """
        批量补充并格式化店铺信息（非流式）.
        
        Args:
            recommendations: 推荐列表
            city: 城市名称
            
        Returns:
            格式化后的店铺列表
        """
        results = []
        async for enriched in self.enrich_stream(recommendations, city):
            results.append(enriched)
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
            from xhs_food.services import get_user_storage_service
            
            storage = await get_user_storage_service()
            if not storage._initialized or not storage._pool:
                return None
            
            async with storage._pool.acquire() as conn:
                # 优先精确匹配
                row = await conn.fetchrow(
                    """
                    SELECT * FROM restaurants 
                    WHERE name = $1
                    LIMIT 1
                    """,
                    name,
                )
                
                # 如果精确匹配失败，尝试模糊匹配
                if not row:
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM restaurants 
                        WHERE name ILIKE $1 OR name ILIKE $2
                        ORDER BY updated_at DESC NULLS LAST
                        LIMIT 1
                        """,
                        f"{name}%",  # 前缀匹配: "贡井清香园" → "贡井清香园(泰丰店)"
                        f"%{name}",  # 后缀匹配: "清香园" → "贡井清香园"
                    )
                
                if row:
                    return dict(row)
            return None
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
            except:
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
        import re
        # 匹配括号内的分店名
        clean = re.sub(r'[\(（][^)）]*[店分部号馆][\)）]$', '', name)
        # 也处理不带括号的情况，如 "xx总店"
        clean = re.sub(r'[总分新老][店]$', '', clean)
        return clean.strip()
    
    async def _do_poi_search(self, keywords: str, city: str) -> Optional[Dict[str, Any]]:
        """执行单次 POI 搜索."""
        try:
            result = await asyncio.to_thread(
                self._amap.search_poi,
                keywords=keywords,
                city=city,
                types="050000",  # 餐饮服务
            )
            
            if "error" in result:
                return None
            
            pois = result.get("pois", [])
            if not pois:
                return None
            
            # 只取第一个（最匹配的）
            return pois[0]
            
        except Exception as e:
            logger.debug(f"POI search failed: {e}")
            return None
    
    def _build_enriched(
        self,
        rec: RestaurantRecommendation,
        idx: int,
        poi: Optional[Dict[str, Any]],
    ) -> EnrichedRestaurant:
        """构建格式化结果."""
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

    
    def _format_basic(self, rec: RestaurantRecommendation, idx: int) -> EnrichedRestaurant:
        """基础格式化（无 POI 信息）."""
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


# 单例
_poi_enricher: Optional[POIEnricherAgent] = None


def get_poi_enricher() -> POIEnricherAgent:
    """获取 POIEnricherAgent 单例."""
    global _poi_enricher
    if _poi_enricher is None:
        _poi_enricher = POIEnricherAgent()
    return _poi_enricher
