import sqlite3
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional
from loguru import logger
from .config import LOG_DB_PATH

class RequestLogger:
    def __init__(self, db_path=LOG_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database schema."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    endpoint TEXT,
                    params TEXT,
                    response TEXT,
                    success INTEGER,
                    error_msg TEXT
                )
            ''')
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize log database: {e}")

    def log_request(self, tool_name: str, endpoint: str, params: Dict[str, Any], response: Any, success: bool, error_msg: Optional[str] = None):
        """Log a request and its response to the database."""
        try:
            timestamp = datetime.now().isoformat()
            # Use ensure_ascii=True to avoid encoding issues on Windows (GBK)
            # This will escape non-ASCII characters as \uXXXX sequences
            params_json = json.dumps(params, ensure_ascii=True)
            response_json = json.dumps(response, ensure_ascii=True) if response is not None else ""
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO request_logs (timestamp, tool_name, endpoint, params, response, success, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp, tool_name, endpoint, params_json, response_json, 1 if success else 0, error_msg))
            conn.commit()
            conn.close()
            logger.debug(f"Logged request for {tool_name}")
        except Exception as e:
            logger.error(f"Failed to log request: {e}")

    def get_recent_logs(self, limit=10):
        """Retrieve recent logs for debugging."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM request_logs ORDER BY id DESC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to retrieve logs: {e}")
            return []

# Global instance
request_logger = RequestLogger()
