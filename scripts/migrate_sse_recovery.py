"""
数据库迁移脚本 - 添加 SSE 恢复相关字段

运行方式:
  python scripts/migrate_sse_recovery.py
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
        # 1. 添加 session_id 列到 search_history
        print("Adding session_id column...")
        await conn.execute("""
            ALTER TABLE search_history 
            ADD COLUMN IF NOT EXISTS session_id UUID UNIQUE
        """)
        
        # 2. 添加 status 列
        print("Adding status column...")
        await conn.execute("""
            ALTER TABLE search_history 
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'loading'
        """)
        
        # 3. 添加 updated_at 列
        print("Adding updated_at column...")
        await conn.execute("""
            ALTER TABLE search_history 
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
        """)
        
        # 4. 创建 session_id 索引
        print("Creating index on session_id...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_session 
            ON search_history(session_id)
        """)
        
        # 5. 创建 search_results 表
        print("Creating search_results table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS search_results (
                id BIGSERIAL PRIMARY KEY,
                session_id UUID UNIQUE NOT NULL,
                restaurants JSONB NOT NULL DEFAULT '[]',
                summary TEXT,
                filtered_count INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        # 6. 创建索引
        print("Creating index on search_results...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_results_session 
            ON search_results(session_id)
        """)
        
        print("✅ Migration completed successfully!")
        
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
