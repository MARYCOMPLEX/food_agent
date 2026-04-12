# -*- coding: utf-8 -*-
"""Data models and helpers for user storage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def generate_restaurant_hash(name: str, tel: Optional[str] = None) -> str:
    """
    Generate a unique hash ID for a restaurant.

    Uses SHA256(name + tel)[:32]. If tel is empty, uses name only.

    Args:
        name: Restaurant name (required)
        tel: Phone number (optional)

    Returns:
        32-character hex hash string
    """
    if not name:
        raise ValueError("Restaurant name is required for hash generation")

    # Normalize inputs
    name = name.strip()
    raw = name
    if tel and tel.strip():
        raw = f"{name}:{tel.strip()}"

    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


@dataclass
class User:
    """User data model."""
    id: str
    device_id: Optional[str] = None
    name: str = "Guest"
    device_id: Optional[str] = None
    name: str = "Guest"
    username: Optional[str] = None
    email: Optional[str] = None
    avatar: Optional[str] = None
    location: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "deviceId": self.device_id,
            "deviceId": self.device_id,
            "name": self.name,
            "username": self.username,
            "email": self.email,
            "avatar": self.avatar,
            "location": self.location,
            "settings": self.settings,
            "memberSince": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Favorite:
    """Favorite data model."""
    id: int
    user_id: str
    restaurant_id: str  # Hash ID from restaurants table
    restaurant: Optional[Dict[str, Any]] = None  # Joined from restaurants table
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.restaurant_id,
            "addedAt": self.created_at.timestamp() if self.created_at else None,
            "restaurant": self.restaurant,
        }


@dataclass
class SearchHistory:
    """Search history data model."""
    id: int
    user_id: str
    query: str
    session_id: Optional[str] = None
    status: str = "loading"
    results_count: int = 0
    location: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": f"hist_{self.id}",
            "sessionId": self.session_id,
            "query": self.query,
            "status": self.status,
            "timestamp": self.created_at.timestamp() if self.created_at else None,
            "resultsCount": self.results_count,
            "location": self.location,
        }


@dataclass
class Restaurant:
    """Restaurant data model."""
    id: str  # Hash ID
    name: str
    alias: Optional[str] = None
    tel: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    business_area: Optional[str] = None
    location: Optional[str] = None  # lat,lng
    rating: Optional[float] = None
    cost: Optional[str] = None
    open_time: Optional[str] = None
    trust_score: Optional[float] = None
    one_liner: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    warning: Optional[str] = None
    must_try: List[Dict[str, str]] = field(default_factory=list)
    black_list: List[Dict[str, str]] = field(default_factory=list)
    stats: Dict[str, str] = field(default_factory=dict)
    photos: List[Dict[str, str]] = field(default_factory=list)
    source_notes: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "id": self.id,
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
            "trustScore": round(self.trust_score, 1) if self.trust_score else None,
            "oneLiner": self.one_liner,
            "tags": self.tags,
            "pros": self.pros,
            "cons": self.cons,
            "warning": self.warning,
            "photos": self.photos,
            "sourceNotes": self.source_notes,
            "mustTry": self.must_try,
            "blackList": self.black_list,
            "stats": self.stats,
        }
