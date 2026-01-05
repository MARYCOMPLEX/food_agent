# -*- coding: utf-8 -*-
"""XHS Food Agent Configuration Test."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
load_dotenv()


def test_env_variables():
    print("=" * 60)
    print("1. Test Environment Variables")
    print("=" * 60)
    
    errors = []
    
    xhs_cookies = os.getenv("XHS_COOKIES")
    if not xhs_cookies or xhs_cookies.startswith("a1=xxx"):
        print("  [!] XHS_COOKIES: Not configured")
        errors.append("XHS_COOKIES needs real cookies")
    else:
        print(f"  [OK] XHS_COOKIES: Configured ({len(xhs_cookies)} chars)")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("  [X] OPENAI_API_KEY: Not configured")
        errors.append("OPENAI_API_KEY is required")
    else:
        masked = api_key[:8] + "..." + api_key[-4:]
        print(f"  [OK] OPENAI_API_KEY: {masked}")
    
    api_base = os.getenv("OPENAI_API_BASE", "https://api.siliconflow.cn/v1/")
    print(f"  [OK] OPENAI_API_BASE: {api_base}")
    
    model = os.getenv("DEFAULT_LLM_MODEL", "Qwen/Qwen3-8B")
    print(f"  [OK] DEFAULT_LLM_MODEL: {model}")
    
    if errors:
        print(f"\n  [FAIL] Config errors: {len(errors)}")
        return False
    
    print("\n  [PASS] Environment configured!")
    return True


def test_llm_service_init():
    print("\n" + "=" * 60)
    print("2. Test LLM Service Initialization")
    print("=" * 60)
    
    try:
        from xhs_food.services import LLMService
        
        service = LLMService()
        print(f"  [OK] LLMService created")
        print(f"    - Model: {service._model_name}")
        
        llm = service._get_llm()
        print(f"  [OK] ChatOpenAI created: {type(llm).__name__}")
        
        return True
    except Exception as e:
        print(f"  [X] Failed: {e}")
        return False


async def test_llm_connection():
    print("\n" + "=" * 60)
    print("3. Test LLM API Connection")
    print("=" * 60)
    
    try:
        from xhs_food.services import LLMService
        from langchain_core.messages import HumanMessage, SystemMessage
        
        service = LLMService()
        
        messages = [
            SystemMessage(content="Reply briefly."),
            HumanMessage(content="Say hello."),
        ]
        
        print("  Sending test request...")
        response = await service.call(messages)
        
        content = response.content if hasattr(response, 'content') else str(response)
        print(f"  [OK] Response: {content[:80]}")
        
        return True
    except Exception as e:
        print(f"  [X] Failed: {e}")
        return False


async def test_intent_parser():
    print("\n" + "=" * 60)
    print("4. Test Intent Parser")
    print("=" * 60)
    
    try:
        from xhs_food.agents import IntentParserAgent
        
        parser = IntentParserAgent()
        test_query = "chengdu local hotpot"
        print(f"  Test: '{test_query}'")
        
        result = await parser.parse(test_query)
        
        if result.success and result.intent:
            print(f"  [OK] Location: {result.intent.location}")
            print(f"  [OK] Food: {result.intent.food_type}")
            return True
        else:
            print(f"  [!] Parse issue: {result.error}")
            return False
            
    except Exception as e:
        print(f"  [X] Failed: {e}")
        return False


def test_orchestrator_init():
    print("\n" + "=" * 60)
    print("5. Test Orchestrator")
    print("=" * 60)
    
    try:
        from xhs_food import XHSFoodOrchestrator
        from xhs_food.di import get_xhs_tool_registry
        
        registry = get_xhs_tool_registry()
        tools = registry.list_tools()
        print(f"  [OK] Tools: {tools}")
        
        orchestrator = XHSFoodOrchestrator(xhs_registry=registry)
        print(f"  [OK] Orchestrator created")
        
        return True
    except Exception as e:
        print(f"  [X] Failed: {e}")
        return False


async def main():
    print("\nXHS Food Agent Config Test\n")
    
    results = {}
    results["env"] = test_env_variables()
    
    if not results["env"]:
        print("\nSkipping further tests due to env issues")
        return
    
    results["llm_init"] = test_llm_service_init()
    results["llm_conn"] = await test_llm_connection()
    
    if results["llm_conn"]:
        results["intent"] = await test_intent_parser()
    
    results["orchestrator"] = test_orchestrator_init()
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed = all(results.values())
    for name, ok in results.items():
        print(f"  {'[OK]' if ok else '[X]'} {name}")
    
    print("\n" + ("SUCCESS!" if passed else "Some tests failed"))


if __name__ == "__main__":
    asyncio.run(main())
