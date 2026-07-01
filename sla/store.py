"""SQLite storage layer with thread safety."""

import os
import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    title TEXT,
    status INTEGER,
    priority INTEGER,
    responsible_id INTEGER,
    created_by INTEGER,
    group_id INTEGER,
    deadline TEXT,
    created_date TEXT,
    closed_date TEXT,
    changed_date TEXT,
    closed_by INTEGER,
    tags TEXT,
    raw TEXT,
    first_seen TEXT
);

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    user_id INTEGER,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    created_date TEXT,
    UNIQUE(task_id, field, old_value, new_value, created_date)
);

CREATE TABLE IF NOT EXISTS task_comments (
    id INTEGER PRIMARY KEY,
    task_id INTEGER,
    author_id INTEGER,
    created_date TEXT,
    content TEXT
);

CREATE TABLE IF NOT EXISTS task_elapsed (
    id INTEGER PRIMARY KEY,
    task_id INTEGER,
    user_id INTEGER,
    seconds INTEGER,
    created_date TEXT,
    comment TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    last_name TEXT,
    full_name TEXT,
    active INTEGER
);

CREATE TABLE IF NOT EXISTS tracked_tasks (
    task_id INTEGER PRIMARY KEY,
    adopted_at TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _normalize_dt(dt_str: Optional[str]) -> Optional[str]:
    """Strip timezone info from ISO datetime for consistent comparison."""
    if not dt_str:
        return dt_str
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt.isoformat()
    except (ValueError, TypeError):
        return dt_str


class Store:
    """Thread-safe SQLite store."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.environ.get("SLA_DB_PATH", "./sla_data.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self.lock:
            self.db.executescript(SCHEMA_SQL)
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---- Tasks ----

    def upsert_task(
        self,
        task_id: int,
        title: str = "",
        status: int = 0,
        priority: int = 2,
        responsible_id: int = 0,
        created_by: int = 0,
        group_id: int = 0,
        deadline: Optional[str] = None,
        created_date: Optional[str] = None,
        closed_date: Optional[str] = None,
        changed_date: Optional[str] = None,
        closed_by: int = 0,
        tags: str = "",
        raw: str = "",
    ) -> None:
        with self.lock:
            self.db.execute(
                """
                INSERT OR REPLACE INTO tasks
                    (id, title, status, priority, responsible_id, created_by, group_id,
                     deadline, created_date, closed_date, changed_date, closed_by, tags, raw, first_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT first_seen FROM tasks WHERE id = ?), datetime('now')))
                """,
                (
                    task_id,
                    title,
                    status,
                    priority,
                    responsible_id,
                    created_by,
                    group_id,
                    deadline,
                    _normalize_dt(created_date),
                    _normalize_dt(closed_date),
                    _normalize_dt(changed_date),
                    closed_by,
                    tags,
                    raw,
                    task_id,
                ),
            )
            self.db.commit()

    def get_tasks(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT t.* FROM tasks t
            INNER JOIN tracked_tasks tt ON t.id = tt.task_id
            WHERE 1=1
        """
        params: list = []
        if filters:
            if filters.get("date_from"):
                query += " AND t.created_date >= ?"
                params.append(filters["date_from"] + "T00:00:00")
            if filters.get("date_to"):
                query += " AND t.created_date <= ?"
                params.append(filters["date_to"] + "T23:59:59")
            if filters.get("responsible_id") is not None:
                query += " AND t.responsible_id = ?"
                params.append(int(filters["responsible_id"]))
            if filters.get("priority") is not None:
                query += " AND t.priority = ?"
                params.append(int(filters["priority"]))
            if filters.get("group_id") is not None:
                query += " AND t.group_id = ?"
                params.append(int(filters["group_id"]))
        query += " ORDER BY t.created_date DESC"

        with self.lock:
            rows = self.db.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self.lock:
            row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    # ---- History ----

    def get_history(self, task_id: int) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM task_history WHERE task_id = ? ORDER BY created_date ASC",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_history_for_task(self, task_id: int) -> None:
        with self.lock:
            self.db.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))
            self.db.commit()

    def add_history(
        self,
        task_id: int,
        user_id: int,
        field: str,
        old_value: str,
        new_value: str,
        created_date: str,
    ) -> None:
        with self.lock:
            self.db.execute(
                """
                INSERT OR IGNORE INTO task_history
                    (task_id, user_id, field, old_value, new_value, created_date)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, user_id, field, old_value, new_value, created_date),
            )
            self.db.commit()

    # ---- Comments ----

    def get_comments(self, task_id: int) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_date ASC",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_comment(
        self,
        comment_id: int,
        task_id: int,
        author_id: int,
        created_date: str,
        content: str,
    ) -> None:
        with self.lock:
            self.db.execute(
                """
                INSERT OR REPLACE INTO task_comments (id, task_id, author_id, created_date, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (comment_id, task_id, author_id, _normalize_dt(created_date), content),
            )
            self.db.commit()

    # ---- Elapsed ----

    def get_elapsed(self, task_id: int) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM task_elapsed WHERE task_id = ? ORDER BY created_date ASC",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_elapsed(
        self,
        elapsed_id: int,
        task_id: int,
        user_id: int,
        seconds: int,
        created_date: str,
        comment: str,
    ) -> None:
        with self.lock:
            self.db.execute(
                """
                INSERT OR REPLACE INTO task_elapsed (id, task_id, user_id, seconds, created_date, comment)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (elapsed_id, task_id, user_id, seconds, _normalize_dt(created_date), comment),
            )
            self.db.commit()

    # ---- Users ----

    def upsert_user(
        self,
        user_id: int,
        name: str,
        last_name: str,
        full_name: str,
        active: int = 1,
    ) -> None:
        with self.lock:
            self.db.execute(
                """
                INSERT OR REPLACE INTO users (id, name, last_name, full_name, active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, last_name, full_name, active),
            )
            self.db.commit()

    def users_map(self) -> Dict[int, Dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM users").fetchall()
            return {r["id"]: dict(r) for r in rows}

    # ---- Tracked tasks ----

    def adopt_task(self, task_id: int) -> None:
        with self.lock:
            self.db.execute(
                "INSERT OR IGNORE INTO tracked_tasks (task_id, adopted_at) VALUES (?, datetime('now'))",
                (task_id,),
            )
            self.db.commit()

    def is_tracked(self, task_id: int) -> bool:
        with self.lock:
            row = self.db.execute(
                "SELECT 1 FROM tracked_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return row is not None

    def all_tracked_ids(self) -> List[int]:
        with self.lock:
            rows = self.db.execute("SELECT task_id FROM tracked_tasks").fetchall()
            return [r["task_id"] for r in rows]

    # ---- Sync state ----

    def set_sync_state(self, key: str, value: str) -> None:
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)", (key, value)
            )
            self.db.commit()

    def get_sync_state(self, key: str) -> Optional[str]:
        with self.lock:
            row = self.db.execute(
                "SELECT value FROM sync_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    # ---- Misc ----

    def get_groups(self) -> List[Dict[str, Any]]:
        """Get unique group IDs from tasks (group_id is int in DB, stored as text)."""
        with self.lock:
            rows = self.db.execute(
                "SELECT DISTINCT group_id FROM tasks WHERE group_id IS NOT NULL AND group_id != 0"
            ).fetchall()
            return [{"id": r["group_id"], "title": f"Группа {r['group_id']}"} for r in rows]

    def clear_all_data(self) -> None:
        with self.lock:
            for table in ["tasks", "task_history", "task_comments", "task_elapsed", "users", "tracked_tasks", "sync_state"]:
                self.db.execute(f"DELETE FROM {table}")
            self.db.commit()
