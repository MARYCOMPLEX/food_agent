"""Rollback binding for the pre-registration Food workflow semantics."""

from xhs_food.contracts.base import JsonValue
from xhs_food.domain_packs.food.decision import FoodDecisionPolicy
from xhs_food.domain_packs.food.resources import load_food_manifest
from xhs_food.domain_packs.food.workflow import FoodWorkflowPolicy


class LegacyFoodPackAdapter:
    """Keep legacy workflow behavior selectable without a registered Pack snapshot."""

    version = "legacy/v1"

    def __init__(self) -> None:
        self._manifest = load_food_manifest()
        self.workflow = FoodWorkflowPolicy()
        self.decision = FoodDecisionPolicy()

    def validate_final_output(self, value: JsonValue) -> None:
        self._manifest.validate_final_output(value)


__all__ = ["LegacyFoodPackAdapter"]
