"""
Basic import and functionality test for XHS Food Agent.
"""

import sys
sys.path.insert(0, "src")


def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    # Core module
    from xhs_food import XHSFoodOrchestrator
    from xhs_food import XHSFoodState
    from xhs_food import FoodSearchIntent, XHSFoodResponse
    print("  ✓ xhs_food module")
    
    # Schemas
    from xhs_food.schemas import (
        WanghongScore,
        SearchPhase,
        ConversationContext,
        RestaurantRecommendation,
    )
    print("  ✓ schemas")
    
    # Protocols
    from xhs_food.protocols import ToolResult, MCPToolRegistry
    print("  ✓ protocols")
    
    # Services
    from xhs_food.services import LLMService
    print("  ✓ services")
    
    # Agents
    from xhs_food.agents import IntentParserAgent, AnalyzerAgent
    print("  ✓ agents")
    
    # Providers
    from xhs_food.providers import XHSSearchProvider, XHSNoteProvider
    print("  ✓ providers")
    
    # DI
    from xhs_food.di import get_xhs_tool_registry
    print("  ✓ di")
    
    print("\n✅ All imports successful!")


def test_schema_creation():
    """Test that schemas can be instantiated."""
    print("\nTesting schema creation...")
    
    from xhs_food.schemas import (
        FoodSearchIntent,
        ConversationContext,
        RestaurantRecommendation,
        WanghongAnalysis,
        WanghongScore,
    )
    
    # Create intent
    intent = FoodSearchIntent(
        location="成都",
        food_type="火锅",
        requirements=["本地人常去", "老店"],
        exclude_keywords=["网红"],
    )
    print(f"  ✓ FoodSearchIntent: {intent.location} {intent.food_type}")
    
    # Create context
    ctx = ConversationContext()
    ctx.turn_count = 1
    print(f"  ✓ ConversationContext: turn={ctx.turn_count}")
    
    # Create recommendation
    rec = RestaurantRecommendation(
        name="测试老店",
        location="XX路XX号",
        features=["本地人推荐"],
        confidence=0.85,
    )
    print(f"  ✓ RestaurantRecommendation: {rec.name}")
    
    print("\n✅ All schemas created successfully!")


def test_orchestrator_creation():
    """Test that orchestrator can be created."""
    print("\nTesting orchestrator creation...")
    
    from xhs_food import XHSFoodOrchestrator
    from xhs_food.di import get_xhs_tool_registry
    
    # Create without registry (will lazy-load)
    orch = XHSFoodOrchestrator()
    print(f"  ✓ XHSFoodOrchestrator created (lazy init)")
    
    # Create with registry
    registry = get_xhs_tool_registry()
    tools = registry.list_tools()
    print(f"  ✓ Registry tools: {tools}")
    
    orch2 = XHSFoodOrchestrator(xhs_registry=registry)
    print(f"  ✓ XHSFoodOrchestrator with registry")
    
    print("\n✅ Orchestrator creation successful!")


if __name__ == "__main__":
    print("=" * 50)
    print("XHS Food Agent - Basic Test")
    print("=" * 50)
    
    test_imports()
    test_schema_creation()
    test_orchestrator_creation()
    
    print("\n" + "=" * 50)
    print("All basic tests passed!")
    print("=" * 50)
