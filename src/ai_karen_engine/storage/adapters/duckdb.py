"""
DuckDB adapter for analytical/local storage.
"""

import duckdb
import json
import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DuckDBClient:
    def __init__(self, db_path="kari_duckdb.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._initialized = False

        self._enabled = os.getenv("KARI_ENABLE_DUCKDB", "true").lower() not in ("false", "0", "no")
        if not self._enabled:
            logger.info("DuckDB disabled via KARI_ENABLE_DUCKDB environment variable")

    def _get_conn(self):
        if not self._enabled:
            raise RuntimeError("DuckDB is disabled. Set KARI_ENABLE_DUCKDB=true to enable.")
        return duckdb.connect(self.db_path)

    def _ensure_initialized(self):
        if self._initialized:
            return
        if not self._enabled:
            raise RuntimeError("DuckDB is disabled. Set KARI_ENABLE_DUCKDB=true to enable.")
        logger.info(f"Initializing DuckDB tables at {self.db_path}")
        self._ensure_tables()
        self._initialized = True
        logger.info("DuckDB client initialized successfully")

    def _ensure_tables(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id VARCHAR PRIMARY KEY,
                    profile_json VARCHAR,
                    last_update TIMESTAMP
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile_history (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR,
                    timestamp DOUBLE,
                    field VARCHAR,
                    old VARCHAR,
                    new VARCHAR
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    user_id VARCHAR,
                    memory_json VARCHAR
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id VARCHAR,
                    role VARCHAR
                );
            """)

    def get_profile(self, user_id):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            res = conn.execute("SELECT profile_json FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
            return json.loads(res[0]) if res else None

    def update_profile(self, user_id, field, value):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            cur = conn.execute("SELECT profile_json FROM profiles WHERE user_id = ?", (user_id,))
            res = cur.fetchone()
            profile = json.loads(res[0]) if res else {}
            profile[field] = value
            profile["last_update"] = datetime.utcnow().timestamp()
            profile_json = json.dumps(profile)
            if res:
                conn.execute("UPDATE profiles SET profile_json = ?, last_update = ? WHERE user_id = ?", (profile_json, datetime.utcnow(), user_id))
            else:
                conn.execute("INSERT INTO profiles (user_id, profile_json, last_update) VALUES (?, ?, ?)", (user_id, profile_json, datetime.utcnow()))

    def create_profile(self, user_id, profile):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            profile["last_update"] = datetime.utcnow().timestamp()
            conn.execute("INSERT INTO profiles (user_id, profile_json, last_update) VALUES (?, ?, ?)", (user_id, json.dumps(profile), datetime.utcnow()))

    def save_profile(self, user_id, profile):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            profile["last_update"] = datetime.utcnow().timestamp()
            profile_json = json.dumps(profile)
            res = conn.execute("SELECT 1 FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
            if res:
                conn.execute(
                    "UPDATE profiles SET profile_json = ?, last_update = ? WHERE user_id = ?",
                    (profile_json, datetime.utcnow(), user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO profiles (user_id, profile_json, last_update) VALUES (?, ?, ?)",
                    (user_id, profile_json, datetime.utcnow()),
                )

    def delete_profile(self, user_id):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            conn.execute("DELETE FROM profiles WHERE user_id = ?", (user_id,))

    def append_profile_history(self, user_id, entry):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            conn.execute(
                "INSERT INTO profile_history (user_id, timestamp, field, old, new) VALUES (?, ?, ?, ?, ?)",
                (user_id, entry.get("timestamp"), entry.get("field"), json.dumps(entry.get("old")), json.dumps(entry.get("new")))
            )

    def get_profile_history(self, user_id):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            res = conn.execute("SELECT timestamp, field, old, new FROM profile_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 100", (user_id,))
            rows = res.fetchall()
            return [{"timestamp": ts, "field": f, "old": json.loads(o), "new": json.loads(n)} for (ts, f, o, n) in rows]

    def profile_edit_count(self, user_id):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            res = conn.execute("SELECT COUNT(*) FROM profile_history WHERE user_id = ?", (user_id,)).fetchone()
            return int(res[0]) if res else 0

    def delete_long_term_memory(self, user_id):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            conn.execute("DELETE FROM long_term_memory WHERE user_id = ?", (user_id,))

    def total_interactions(self, user_id):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            res = conn.execute("SELECT COUNT(*) FROM profile_history WHERE user_id = ?", (user_id,)).fetchone()
            return int(res[0]) if res else 0

    def recent_interactions(self, user_id, window_days=7):
        self._ensure_initialized()
        cutoff = datetime.utcnow().timestamp() - window_days * 86400
        with self._lock, self._get_conn() as conn:
            res = conn.execute(
                "SELECT COUNT(*) FROM profile_history WHERE user_id = ? AND timestamp >= ?", (user_id, cutoff)
            ).fetchone()
            return int(res[0]) if res else 0

    def get_user_roles(self, user_id):
        self._ensure_initialized()
        with self._lock, self._get_conn() as conn:
            res = conn.execute("SELECT role FROM user_roles WHERE user_id = ?", (user_id,)).fetchall()
            return [r[0] for r in res]

    def health(self):
        try:
            if not self._enabled:
                return False
            if not self._initialized:
                logger.debug("DuckDB client not yet initialized (lazy mode) - reporting as healthy")
                return True
            with self._get_conn() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"DuckDB health check failed: {e}")
            return False
