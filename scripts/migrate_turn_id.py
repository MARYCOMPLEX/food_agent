"""
数据库迁移脚本 - 添加 turn_id 支持多轮对话历史

运行方式:
  python scripts/migrate_turn_id.py

变更说明:
  - search_results 表新增 turn_id 字段
  - 主键改为 (session_id, turn_id) 联合主键
  - 支持同一个 session 保存多轮搜索结果
"""
import asyncio
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def migrate():
    # 构建数据库 URL
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "xhs_food_agent")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    
    database_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    print(f"Connecting to: {host}:{port}/{db}")
    
    conn = await asyncpg.connect(database_url)
    
    try:
        # 1. 添加 turn_id 列
        print("Adding turn_id column...")
        await conn.execute("""
            ALTER TABLE search_results 
            ADD COLUMN IF NOT EXISTS turn_id INTEGER DEFAULT 1
        """)
        
        # 2. 添加 query 列（记录每轮的查询）
        print("Adding query column...")
        await conn.execute("""
            ALTER TABLE search_results 
            ADD COLUMN IF NOT EXISTS query TEXT
        """)
        
        # 3. 删除旧的 UNIQUE 约束（session_id）
        print("Dropping old unique constraint...")
        try:
            await conn.execute("""
                ALTER TABLE search_results 
                DROP CONSTRAINT IF EXISTS search_results_session_id_key
            """)
        except Exception as e:
            print(f"  Note: {e}")
        
        # 4. 创建新的联合唯一约束
        print("Creating composite unique constraint...")
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_results_session_turn 
            ON search_results(session_id, turn_id)
        """)
        
        # 5. 创建索引方便查询最新轮次
        print("Creating index on turn_id...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_results_turn 
            ON search_results(session_id, turn_id DESC)
        """)
        
        print("✅ Migration completed successfully!")
        
        # 显示当前表结构
        print("\n📊 Current table structure:")
        rows = await conn.fetch("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns 
            WHERE table_name = 'search_results'
            ORDER BY ordinal_position
        """)
        for row in rows:
            print(f"  - {row['column_name']}: {row['data_type']} (default: {row['column_default']})")
        
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
