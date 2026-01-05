"""
XHS Tool Providers - 封装 Spider XHS 服务的 MCPToolProvider 实现.

提供:
- XHSSearchProvider: 搜索笔记
- XHSNoteProvider: 获取笔记详情和评论
- XHSBatchProvider: 批量研究
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from xhs_food.protocols.mcp import MCPToolProvider, ToolResult


# Lazy import to avoid circular dependencies
_xhs_service = None

def _get_xhs_service():
    """Lazy load XHSService."""
    global _xhs_service
    if _xhs_service is None:
        from xhs_food.spider.services.xhs_service import XHSService
        _xhs_service = XHSService()
    return _xhs_service


class XHSSearchProvider:
    """搜索小红书笔记.
    
    封装 XHSService.search_xhs 方法。
    """
    
    @property
    def name(self) -> str:
        return "xhs_search"
    
    async def execute(
        self,
        keyword: str,
        count: int = 10,
        sort_type: str = "most_comments",
        include_details: bool = True,
        include_comments: bool = True,
        **kwargs
    ) -> ToolResult:
        """
        搜索小红书笔记.
        
        Args:
            keyword: 搜索关键词
            count: 返回数量 (默认10)
            sort_type: 排序方式 (general/newest/popular/most_comments)
            include_details: 是否获取详情
            include_comments: 是否获取评论
            
        Returns:
            ToolResult: 包含笔记列表
        """
        try:
            service = _get_xhs_service()
            # Run sync method in thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: service.search_xhs(
                    keyword=keyword,
                    count=count,
                    sort_type=sort_type,
                    include_details=include_details,
                    include_comments=include_comments,
                )
            )
            
            if result.get("status") == "success":
                return ToolResult.ok(result)
            else:
                return ToolResult.fail(
                    "SEARCH_FAILED",
                    result.get("message", "Unknown error")
                )
        except Exception as e:
            return ToolResult.fail("SEARCH_ERROR", str(e))
    
    async def health_check(self) -> bool:
        """检查服务是否可用."""
        try:
            _get_xhs_service()
            return True
        except Exception:
            return False


class XHSNoteProvider:
    """获取单篇笔记详情和评论.
    
    封装 XHSService.get_xhs_note 方法。
    """
    
    @property
    def name(self) -> str:
        return "xhs_note"
    
    async def execute(
        self,
        note_id: str,
        max_comments: int = 30,
        **kwargs
    ) -> ToolResult:
        """
        获取笔记详情和评论.
        
        Args:
            note_id: 笔记ID或URL
            max_comments: 最大评论数
            
        Returns:
            ToolResult: 包含笔记详情和评论
        """
        try:
            service = _get_xhs_service()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: service.get_xhs_note(
                    url_or_id=note_id,
                    max_comments=max_comments,
                )
            )
            
            if result.get("status") == "success":
                return ToolResult.ok(result)
            else:
                return ToolResult.fail(
                    "NOTE_FETCH_FAILED",
                    result.get("message", "Unknown error")
                )
        except Exception as e:
            return ToolResult.fail("NOTE_ERROR", str(e))
    
    async def health_check(self) -> bool:
        try:
            _get_xhs_service()
            return True
        except Exception:
            return False


class XHSBatchProvider:
    """批量研究多个话题.
    
    封装 XHSService.batch_xhs_research 方法。
    """
    
    @property
    def name(self) -> str:
        return "xhs_batch"
    
    async def execute(
        self,
        topics: List[str],
        notes_per_topic: int = 4,
        **kwargs
    ) -> ToolResult:
        """
        批量研究多个话题.
        
        Args:
            topics: 话题列表
            notes_per_topic: 每个话题获取的笔记数
            
        Returns:
            ToolResult: 包含各话题的笔记
        """
        try:
            service = _get_xhs_service()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: service.batch_xhs_research(
                    topics=topics,
                    notes_per_topic=notes_per_topic,
                )
            )
            
            if result.get("status") == "success":
                return ToolResult.ok(result)
            else:
                return ToolResult.fail(
                    "BATCH_FAILED",
                    result.get("message", "Unknown error")
                )
        except Exception as e:
            return ToolResult.fail("BATCH_ERROR", str(e))
    
    async def health_check(self) -> bool:
        try:
            _get_xhs_service()
            return True
        except Exception:
            return False
