"""Tiny SQLite storage shared by the core and all skills."""
import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER, role TEXT, content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER, tool TEXT, args TEXT, summary TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.executescript(SCHEMA)

    # --- generic helpers -------------------------------------------------
    def executescript(self, sql: str) -> None:
        with self.lock:
            self.conn.executescript(sql)
            self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a write statement; returns lastrowid."""
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.lastrowid

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # --- key/value -------------------------------------------------------
    def get(self, key: str, default=None):
        rows = self.query("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set(self, key: str, value) -> None:
        self.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    # --- conversation history -------------------------------------------
    def add_message(self, chat_id: int, role: str, content: str) -> None:
        self.execute(
            "INSERT INTO messages(chat_id, role, content) VALUES(?,?,?)",
            (chat_id, role, content),
        )

    def history(self, chat_id: int, limit: int) -> list[dict]:
        rows = self.query(
            "SELECT role, content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )
        return list(reversed(rows))

    def clear_history(self, chat_id: int) -> None:
        self.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
