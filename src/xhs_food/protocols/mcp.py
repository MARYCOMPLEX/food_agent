"""
MCPToolProvider Protocol - 可插拔的 MCP 工具抽象接口.

从 meet/app/core/langgraph/domains/gis/protocols/mcp.py 提取
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)


@dataclass
class ToolResult:
    """MCP 工具执行结果.
    
    Attributes:
        success: 是否执行成功
        data: 返回的数据 (dict 或其他类型)
        error_code: 错误码 (失败时)
        error_message: 错误信息 (失败时)
        metadata: 额外元数据 (如执行耗时、来源等)
    """
    success: bool = True
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def ok(cls, data: Dict[str, Any], **metadata) -> "ToolResult":
        """创建成功结果."""
        return cls(success=True, data=data, metadata=metadata)
    
    @classmethod
    def fail(cls, error_code: str, error_message: str, **metadata) -> "ToolResult":
        """创建失败结果."""
        return cls(
            success=False, 
            error_code=error_code, 
            error_message=error_message,
            metadata=metadata
        )


@runtime_checkable
class MCPToolProvider(Protocol):
    """MCP 工具提供者协议."""
    
    @property
    def name(self) -> str:
        """工具名称."""
        ...
    
    async def execute(self, **kwargs: Any) -> ToolResult:
        """执行工具调用."""
        ...
    
    async def health_check(self) -> bool:
        """健康检查."""
        ...


@dataclass
class MCPToolRegistry:
    """MCP 工具注册表."""
    _tools: Dict[str, MCPToolProvider] = field(default_factory=dict)
    
    def register(self, tool: MCPToolProvider) -> None:
        """注册一个工具 Provider."""
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Optional[MCPToolProvider]:
        """按名称获取工具."""
        return self._tools.get(name)
    
    def get_required(self, name: str) -> MCPToolProvider:
        """按名称获取工具，不存在时抛出异常."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(self._tools.keys())}")
        return tool
    
    def list_tools(self) -> List[str]:
        """列出所有已注册的工具名称."""
        return list(self._tools.keys())
    
    async def health_check_all(self) -> Dict[str, bool]:
        """对所有工具执行健康检查."""
        results = {}
        for name, tool in self._tools.items():
            try:
                results[name] = await tool.health_check()
            except Exception:
                results[name] = False
        return results
