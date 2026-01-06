# -*- coding: utf-8 -*-
"""
高德地图 API 服务.

提供 POI 搜索、详情查询、地理编码等功能。
用于补充店铺的详细位置信息、营业时间、电话等。
"""

import os
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv 不是必须的

class AmapAPI:
    """高德地图 API 封装."""
    
    BASE_URL = "https://restapi.amap.com/v3"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化高德 API.
        
        Args:
            api_key: 高德 API Key，不传则从环境变量获取
                    支持 GAODE_APIKEY 或 AMAP_MAPS_API_KEY
        """
        self.api_key = api_key or os.getenv("GAODE_APIKEY") or os.getenv("AMAP_MAPS_API_KEY")
        if not self.api_key:
            logger.warning("GAODE_APIKEY / AMAP_MAPS_API_KEY not set - Amap API calls will fail")
    
    def _request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """发送 API 请求."""
        params["key"] = self.api_key
        try:
            response = requests.get(f"{self.BASE_URL}/{endpoint}", params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                return {"error": f"API failed: {data.get('info', 'Unknown error')}"}
            
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Amap API request failed: {e}")
            return {"error": str(e)}
    
    # =========================================================================
    # POI 搜索
    # =========================================================================
    
    def search_poi(
        self,
        keywords: str,
        city: str = "",
        types: str = "",  # 空=不限类型，050000=餐饮服务
        page: int = 1,
        page_size: int = 1,  # 默认只取1个
    ) -> Dict[str, Any]:
        """
        关键词搜索 POI.
        
        Args:
            keywords: 搜索关键词（店铺名称）
            city: 城市名称（提高精度）
            types: POI 类型码，空=不限，050000=餐饮服务
            page: 页码
            page_size: 每页数量（默认1，只取最匹配的）
            
        Returns:
            搜索结果，包含 pois 列表
        """
        data = self._request("place/text", {
            "keywords": keywords,
            "city": city,
            "types": types,
            "citylimit": "true" if city else "false",
            "offset": page_size,
            "page": page,
            "extensions": "all",  # 返回全部信息
        })
        
        if "error" in data:
            return data
        
        pois = []
        for poi in data.get("pois", []):
            pois.append(self._parse_poi(poi))
        
        return {
            "count": int(data.get("count", 0)),
            "pois": pois,
        }
    
    def search_around(
        self,
        location: str,
        keywords: str = "",
        types: str = "050000",
        radius: int = 1000,
    ) -> Dict[str, Any]:
        """
        周边搜索 POI.
        
        Args:
            location: 中心点坐标 "经度,纬度"
            keywords: 搜索关键词
            types: POI 类型码
            radius: 搜索半径（米）
            
        Returns:
            搜索结果
        """
        data = self._request("place/around", {
            "location": location,
            "keywords": keywords,
            "types": types,
            "radius": radius,
            "extensions": "all",
        })
        
        if "error" in data:
            return data
        
        pois = []
        for poi in data.get("pois", []):
            pois.append(self._parse_poi(poi))
        
        return {"pois": pois}
    
    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """
        获取 POI 详情.
        
        Args:
            poi_id: POI ID（从搜索结果获取）
            
        Returns:
            POI 详细信息
        """
        data = self._request("place/detail", {
            "id": poi_id,
        })
        
        if "error" in data:
            return data
        
        if not data.get("pois"):
            return {"error": "POI not found"}
        
        return self._parse_poi(data["pois"][0])
    
    def _parse_poi(self, poi: Dict[str, Any]) -> Dict[str, Any]:
        """解析 POI 数据为标准格式."""
        biz_ext = poi.get("biz_ext", {}) or {}
        photos = poi.get("photos", []) or []
        
        return {
            # 基本信息
            "poi_id": poi.get("id"),
            "name": poi.get("name"),
            "alias": poi.get("alias"),
            "type": poi.get("type"),
            "typecode": poi.get("typecode"),
            
            # 位置信息
            "address": poi.get("address"),
            "location": poi.get("location"),  # 经度,纬度
            "pcode": poi.get("pcode"),
            "pname": poi.get("pname"),  # 省份
            "citycode": poi.get("citycode"),
            "cityname": poi.get("cityname"),  # 城市
            "adcode": poi.get("adcode"),
            "adname": poi.get("adname"),  # 区县
            "business_area": poi.get("business_area"),  # 商圈
            
            # 联系信息
            "tel": poi.get("tel"),
            "website": poi.get("website"),
            
            # 营业信息 (biz_ext)
            "rating": biz_ext.get("rating"),  # 评分
            "cost": biz_ext.get("cost"),  # 人均消费
            "open_time": biz_ext.get("open_time") or biz_ext.get("opentime"),  # 营业时间
            
            # 图片
            "photos": [
                {
                    "url": p.get("url"),
                    "title": p.get("title"),
                }
                for p in photos[:5]  # 最多5张
            ] if photos else [],
            
            # 其他
            "tag": poi.get("tag"),
            "navi_poiid": poi.get("navi_poiid"),
        }
    
    # =========================================================================
    # 地理编码
    # =========================================================================
    
    def geocode(self, address: str, city: Optional[str] = None) -> Dict[str, Any]:
        """
        地址转坐标.
        
        Args:
            address: 详细地址
            city: 城市名称
            
        Returns:
            包含 location 的结果
        """
        params = {"address": address}
        if city:
            params["city"] = city
        
        data = self._request("geocode/geo", params)
        
        if "error" in data:
            return data
        
        geocodes = data.get("geocodes", [])
        if not geocodes:
            return {"error": "Geocode failed"}
        
        geo = geocodes[0]
        return {
            "location": geo.get("location"),
            "province": geo.get("province"),
            "city": geo.get("city"),
            "district": geo.get("district"),
            "street": geo.get("street"),
            "number": geo.get("number"),
            "level": geo.get("level"),
        }
    
    def reverse_geocode(self, location: str) -> Dict[str, Any]:
        """
        坐标转地址.
        
        Args:
            location: 坐标 "经度,纬度"
            
        Returns:
            行政区划信息
        """
        data = self._request("geocode/regeo", {"location": location})
        
        if "error" in data:
            return data
        
        regeo = data.get("regeocode", {})
        addr_comp = regeo.get("addressComponent", {})
        
        return {
            "formatted_address": regeo.get("formatted_address"),
            "province": addr_comp.get("province"),
            "city": addr_comp.get("city"),
            "district": addr_comp.get("district"),
            "township": addr_comp.get("township"),
            "street": addr_comp.get("street"),
            "number": addr_comp.get("number"),
            "business_areas": addr_comp.get("businessAreas", []),
        }


# 单例
_amap_api: Optional[AmapAPI] = None


def get_amap_api() -> AmapAPI:
    """获取 AmapAPI 单例."""
    global _amap_api
    if _amap_api is None:
        _amap_api = AmapAPI()
    return _amap_api
