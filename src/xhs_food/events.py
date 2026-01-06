# -*- coding: utf-8 -*-
"""
搜索事件流 - 用于 SSE 推送的事件管理.

支持 orchestrator 中间步骤和 POI 补充结果的流式输出。
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger


class SearchEventType(str, Enum):
    """搜索事件类型."""
    
    # 步骤状态
    STEP_START = "step_start"
    STEP_DONE = "step_done"
    STEP_ERROR = "step_error"
    
    # 进度
    PROGRESS = "progress"
    
    # 中间结果
    INTENT_PARSED = "intent_parsed"
    NOTES_FOUND = "notes_found"
    ANALYSIS_DONE = "analysis_done"
    
    # 店铺结果（流式）
    RESTAURANT = "restaurant"
    
    # 最终状态
    RESULT = "result"
    ERROR = "error"
    DONE = "done"


@dataclass
class SearchEvent:
    """搜索事件."""
    
    type: SearchEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_sse(self) -> Dict[str, str]:
        """转换为 SSE 格式."""
        return {
            "event": self.type.value,
            "data": json.dumps(self.data, ensure_ascii=False),
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典."""
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class SearchEventEmitter:
    """搜索事件发射器."""
    
    def __init__(self):
        self._queue: asyncio.Queue[SearchEvent] = asyncio.Queue()
        self._steps: List[Dict[str, str]] = []
        self._current_step: int = 0
        self._total_steps: int = 6
    
    def reset(self):
        """重置事件队列."""
        self._queue = asyncio.Queue()
        self._steps = []
        self._current_step = 0
    
    def init_steps(self, query: str):
        """初始化步骤列表."""
        self._steps = [
            {"id": "step1", "label": "解析用户意图", "status": "pending"},
            {"id": "step2", "label": "搜索小红书笔记", "status": "pending"},
            {"id": "step3", "label": "分析评论内容", "status": "pending"},
            {"id": "step4", "label": "交叉验证筛选", "status": "pending"},
            {"id": "step5", "label": "补充 POI 信息", "status": "pending"},
            {"id": "step6", "label": "生成推荐结果", "status": "pending"},
        ]
        self._current_step = 0
    
    async def emit(self, event: SearchEvent):
        """发射事件."""
        await self._queue.put(event)
    
    async def step_start(self, step_id: str, message: str = ""):
        """步骤开始."""
        # 更新步骤状态
        for step in self._steps:
            if step["id"] == step_id:
                step["status"] = "loading"
                if message:
                    step["label"] = message
        
        await self.emit(SearchEvent(
            type=SearchEventType.STEP_START,
            data={
                "step": step_id,
                "message": message,
                "steps": self._steps,
                "progress": int((self._current_step / self._total_steps) * 100),
            }
        ))
    
    async def step_done(self, step_id: str, message: str = "", extra: Dict[str, Any] = None):
        """步骤完成."""
        # 更新步骤状态
        for step in self._steps:
            if step["id"] == step_id:
                step["status"] = "done"
                if message:
                    step["label"] = message
        
        self._current_step += 1
        
        data = {
            "step": step_id,
            "message": message,
            "steps": self._steps,
            "progress": int((self._current_step / self._total_steps) * 100),
        }
        if extra:
            data.update(extra)
        
        await self.emit(SearchEvent(type=SearchEventType.STEP_DONE, data=data))
    
    async def step_error(self, step_id: str, error: str):
        """步骤失败."""
        for step in self._steps:
            if step["id"] == step_id:
                step["status"] = "error"
        
        await self.emit(SearchEvent(
            type=SearchEventType.STEP_ERROR,
            data={"step": step_id, "error": error, "steps": self._steps}
        ))
    
    async def emit_restaurant(self, restaurant: Dict[str, Any]):
        """发射单个店铺结果."""
        await self.emit(SearchEvent(
            type=SearchEventType.RESTAURANT,
            data={"restaurant": restaurant}
        ))
    
    async def emit_result(self, summary: str, total: int, filtered: int = 0):
        """发射最终结果."""
        await self.emit(SearchEvent(
            type=SearchEventType.RESULT,
            data={
                "summary": summary,
                "total": total,
                "filtered": filtered,
                "steps": self._steps,
            }
        ))
    
    async def emit_error(self, error: str):
        """发射错误."""
        await self.emit(SearchEvent(
            type=SearchEventType.ERROR,
            data={"error": error}
        ))
    
    async def emit_done(self):
        """发射完成信号."""
        await self.emit(SearchEvent(
            type=SearchEventType.DONE,
            data={"message": "搜索完成"}
        ))
    
    async def events(self, timeout: float = 60.0) -> AsyncGenerator[SearchEvent, None]:
        """
        事件流生成器.
        
        用于 SSE 端点消费。
        
        Args:
            timeout: 超时时间（秒）
            
        Yields:
            SearchEvent
        """
        start_time = time.time()
        
        while True:
            try:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    break
                
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=min(30.0, remaining)
                )
                yield event
                
                # 结束信号
                if event.type in (SearchEventType.DONE, SearchEventType.ERROR):
                    break
                    
            except asyncio.TimeoutError:
                # 发送心跳
                yield SearchEvent(
                    type=SearchEventType.PROGRESS,
                    data={"heartbeat": True, "timestamp": time.time()}
                )


# Session event emitters
_emitters: Dict[str, SearchEventEmitter] = {}


def get_emitter(session_id: str) -> SearchEventEmitter:
    """获取或创建 session 的事件发射器."""
    if session_id not in _emitters:
        _emitters[session_id] = SearchEventEmitter()
    return _emitters[session_id]


def remove_emitter(session_id: str):
    """移除 session 的事件发射器."""
    _emitters.pop(session_id, None)
