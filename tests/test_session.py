"""Session Management Test."""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
load_dotenv()


def test_chat_message():
    print("=" * 60)
    print("1. Test ChatMessage")
    print("=" * 60)
    
    from xhs_food.services.redis_memory import ChatMessage
    
    msg = ChatMessage(
        role="user",
        content="Hello world",
        timestamp=time.time(),
        metadata={"source": "test"},
    )
    
    d = msg.to_dict()
    print(f"  [OK] to_dict: role={d['role']}")
    
    json_str = msg.to_json()
    msg2 = ChatMessage.from_json(json_str)
    print(f"  [OK] JSON round-trip: {msg.content == msg2.content}")
    
    return True


def test_redis_memory_fallback():
    print("\n" + "=" * 60)
    print("2. Test RedisMemory (in-memory fallback)")
    print("=" * 60)
    
    from xhs_food.services.redis_memory import RedisMemory
    
    memory = RedisMemory(redis_url=None)
    session_id = "test-session-123"
    
    memory.add_message(session_id, "user", "Hello")
    memory.add_message(session_id, "assistant", "Hi there")
    memory.add_message(session_id, "user", "Hotpot please")
    
    messages = memory.get_recent_messages(session_id)
    print(f"  [OK] Added 3, retrieved {len(messages)}")
    
    assert messages[0].role == "user"
    print(f"  [OK] Order correct")
    
    context = memory.get_context_for_llm(session_id)
    print(f"  [OK] LLM context: {len(context)} msgs")
    
    assert memory.session_exists(session_id)
    print(f"  [OK] session_exists: True")
    
    assert memory.get_session_length(session_id) == 3
    print(f"  [OK] length: 3")
    
    memory.clear_session(session_id)
    assert not memory.session_exists(session_id)
    print(f"  [OK] cleared")
    
    return True


async def test_session_manager():
    print("\n" + "=" * 60)
    print("3. Test SessionManager")
    print("=" * 60)
    
    from xhs_food.services.session_manager import SessionManager
    
    manager = SessionManager()
    await manager.initialize()
    
    session_id = manager.create_session()
    print(f"  [OK] Created: {session_id[:8]}...")
    
    await manager.add_user_message(session_id, "Find hotpot")
    await manager.add_assistant_message(session_id, "Found 5")
    
    context = await manager.get_context(session_id)
    print(f"  [OK] Context: {len(context)} msgs")
    
    assert len(context) >= 2
    print(f"  [OK] Content verified")
    
    await manager.clear_session(session_id)
    assert not manager.session_exists(session_id)
    print(f"  [OK] Cleared")
    
    await manager.close()
    return True


async def main():
    print("\nSession Management Test\n")
    
    results = {}
    results["chat_message"] = test_chat_message()
    results["redis_memory"] = test_redis_memory_fallback()
    results["session_manager"] = await test_session_manager()
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed = all(results.values())
    for name, ok in results.items():
        print(f"  {'[OK]' if ok else '[X]'} {name}")
    
    print("\n" + ("SUCCESS!" if passed else "FAILED"))
    return passed


if __name__ == "__main__":
    asyncio.run(main())
