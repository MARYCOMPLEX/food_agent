"""Skill metadata."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from xhs_food.capabilities.models import CapabilityKind, CapabilityManifest
from xhs_food.runtime.models import AgentRunContext

SkillHandler = Callable[
    [Mapping[str, Any], AgentRunContext], Any | Awaitable[Any]
]


class SkillManifest(CapabilityManifest):
    """A capability manifest marked as a reusable workflow."""

    kind: CapabilityKind = CapabilityKind.SKILL
    skill_pack: str = "core"


class SkillDefinition:
    def __init__(self, manifest: SkillManifest, handler: SkillHandler) -> None:
        self.manifest = manifest
        self.handler = handler
