"""Stable six-step progress projection, independent of source execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LegacyStepDefinition:
    capability: str
    step_id: str
    label: str


LEGACY_SIX_STEP_DEFINITIONS = (
    LegacyStepDefinition("intent_parsing", "step1", "解析用户意图"),
    LegacyStepDefinition("evidence_collection", "step2", "搜索小红书笔记"),
    LegacyStepDefinition("evidence_analysis", "step3", "分析评论内容"),
    LegacyStepDefinition("evidence_validation", "step4", "交叉验证筛选"),
    LegacyStepDefinition("shop_profile_enrichment", "step5", "补充店铺结构化档案"),
    LegacyStepDefinition("result_generation", "step6", "生成推荐结果"),
)


class LegacySixStepProjection:
    """Own transport progress without knowing how a step is executed."""

    def __init__(self) -> None:
        self._steps: list[dict[str, str]] = []
        self._current_step = 0

    @property
    def steps(self) -> list[dict[str, str]]:
        return self._steps

    def reset(self) -> None:
        self._steps = []
        self._current_step = 0

    def initialize(self) -> None:
        self._steps = [
            {
                "id": definition.step_id,
                "label": definition.label,
                "status": "pending",
            }
            for definition in LEGACY_SIX_STEP_DEFINITIONS
        ]
        self._current_step = 0

    def update(self, step_id: str, status: str, message: str = "") -> None:
        for step in self._steps:
            if step["id"] == step_id:
                step["status"] = status
                if message:
                    step["label"] = message
                break

    def advance(self) -> None:
        self._current_step += 1

    def progress(self) -> int:
        total_steps = len(LEGACY_SIX_STEP_DEFINITIONS)
        return int((self._current_step / total_steps) * 100) if total_steps else 0


__all__ = [
    "LEGACY_SIX_STEP_DEFINITIONS",
    "LegacySixStepProjection",
    "LegacyStepDefinition",
]
