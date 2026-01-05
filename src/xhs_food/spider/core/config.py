import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "datas"
LOG_DB_PATH = DATA_DIR / "request_log.db"

# Ensure datas directory exists
if not DATA_DIR.exists():
    DATA_DIR.mkdir(parents=True)

# Configuration
class Config:
    # Rate Limiting
    REQUEST_DELAY_MIN = 1.0  # Seconds
    REQUEST_DELAY_MAX = 3.0  # Seconds
    
    # Pagination
    DEFAULT_PAGE_SIZE = 20
    MAX_ITEMS_PER_BATCH = 100
    
    # Logging
    LOG_RETENTION_DAYS = 7
    
    # User Agent (Failover if not in headers)
    DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

config = Config()
