"""
数据库迁移脚本：重建 favorites 和 restaurants 表.

运行方式：
cd src
..\.venv\Scripts\python.exe scripts/migrate_favorites.py
"""
import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"✓ 已加载环境变量: {env_file}")
    else:
        print(f"⚠ 未找到 .env 文件: {env_file}")
except ImportError:
    print("⚠ 未安装 python-dotenv，使用系统环境变量")

async def main():
    try:
        import asyncpg
    except ImportError:
        print("请先安装 asyncpg: pip install asyncpg")
        return

    # 从环境变量获取数据库连接信息
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "xhs_food")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")

    if password:
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    else:
        dsn = f"postgresql://{user}@{host}:{port}/{db}"

    print(f"连接数据库: {host}:{port}/{db}")
    
    try:
        conn = await asyncpg.connect(dsn)
        
        print("删除旧表...")
        await conn.execute("DROP TABLE IF EXISTS favorites CASCADE")
        await conn.execute("DROP TABLE IF EXISTS restaurants CASCADE")
        
        print("创建 restaurants 表...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS restaurants (
                id VARCHAR(32) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                alias VARCHAR(255),
                tel VARCHAR(50),
                address TEXT,
                city VARCHAR(100),
                district VARCHAR(100),
                business_area VARCHAR(100),
                location VARCHAR(50),
                rating REAL,
                cost VARCHAR(50),
                open_time VARCHAR(255),
                trust_score REAL,
                one_liner TEXT,
                tags JSONB DEFAULT '[]',
                pros JSONB DEFAULT '[]',
                cons JSONB DEFAULT '[]',
                warning TEXT,
                must_try JSONB DEFAULT '[]',
                black_list JSONB DEFAULT '[]',
                stats JSONB DEFAULT '{}',
                photos JSONB DEFAULT '[]',
                source_notes JSONB DEFAULT '[]',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_restaurants_name ON restaurants(name)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_restaurants_city ON restaurants(city)")
        
        print("创建 favorites 表...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                restaurant_id VARCHAR(32) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                deleted_at TIMESTAMPTZ DEFAULT NULL,
                UNIQUE(user_id, restaurant_id)
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_restaurant ON favorites(restaurant_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_deleted ON favorites(deleted_at) WHERE deleted_at IS NULL")
        
        # 为现有表添加 deleted_at 列（如果不存在）
        print("添加软删除字段...")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL")
        await conn.execute("ALTER TABLE search_history ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_deleted ON users(deleted_at) WHERE deleted_at IS NULL")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_history_deleted ON search_history(deleted_at) WHERE deleted_at IS NULL")
        
        await conn.close()
        print("✅ 迁移完成！")
        
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
