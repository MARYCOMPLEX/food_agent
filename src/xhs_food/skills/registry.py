"""Skill registry and fixed workflow adapter."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from typing import Any

from xhs_food.runtime.models import AgentRunContext

from .models import SkillDefinition, SkillManifest


class FixedWorkflowSkill:
    """Expose a deterministic workflow as one callable capability.

    The Agent Loop can choose this capability for routine work, while complex
    tasks can instead compose lower-level tools.  The workflow itself remains
    outside the model and is therefore testable and auditable.
    """

    def __init__(self, definition: SkillDefinition) -> None:
        self._definition = definition

    @property
    def manifest(self) -> SkillManifest:
        return self._definition.manifest

    async def invoke(self, args: Mapping[str, Any], context: AgentRunContext) -> Any:
        value = self._definition.handler(args, context)
        return await value if inspect.isawaitable(value) else value


class SkillRegistry:
    def __init__(self, skills: Iterable[SkillDefinition] = ()) -> None:
        self._skills: dict[str, FixedWorkflowSkill] = {}
        for skill in skills:
            self.register(skill)

    def register(self, definition: SkillDefinition, *, replace: bool = False) -> None:
        name = definition.manifest.name
        if name in self._skills and not replace:
            raise ValueError(f"skill {name!r} is already registered")
        self._skills[name] = FixedWorkflowSkill(definition)

    def get(self, name: str) -> FixedWorkflowSkill | None:
        return self._skills.get(name)

    def require(self, name: str) -> FixedWorkflowSkill:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"skill {name!r} is not registered")
        return skill

    def list(self) -> list[SkillManifest]:
        return [skill.manifest for skill in self._skills.values()]

    def capabilities(self) -> list[FixedWorkflowSkill]:
        return list(self._skills.values())
