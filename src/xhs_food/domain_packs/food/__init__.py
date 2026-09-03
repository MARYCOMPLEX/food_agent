"""Food Domain Pack authority resources.

Loading these resources does not register or activate the Food Pack. Composition
Root owns registration and activation after validating all required capabilities.
"""

from .decision import FoodDecisionPolicy, WanghongDecision
from .intent import FoodSearchIntent
from .pack import FoodBehavior, FoodPack, create_food_pack
from .resources import (
    FOOD_DOMAIN_ID,
    FOOD_PACK_VERSION,
    load_food_contract_resources,
    load_food_manifest,
    load_food_schema_bundle,
)
from .workflow import FoodWorkflowPolicy

__all__ = [
    "FOOD_DOMAIN_ID",
    "FOOD_PACK_VERSION",
    "FoodBehavior",
    "FoodDecisionPolicy",
    "FoodPack",
    "FoodSearchIntent",
    "FoodWorkflowPolicy",
    "WanghongDecision",
    "create_food_pack",
    "load_food_contract_resources",
    "load_food_manifest",
    "load_food_schema_bundle",
]
