"""SQLite persistence for chat history and long-term user memories.

Two tables:
  * messages - every chat turn, used for short-term (per-session) history.
  * memories - one row per (user, category), e.g. ("user-123", "career_goal").
               Saving the same category again overwrites it, so a user's
               correction ("actually, reply in English") replaces the old value.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Memory:
    key: str    # category, e.g. "career_goal"
    value: str  # what the user said, e.g. "I'm planning to switch jobs next year"


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (user_id, session_id, id);

CREATE TABLE IF NOT EXISTS memories (
    user_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, key)
);
"""


class Storage:
    """Thin wrapper around a single SQLite connection.

    Pass ":memory:" as db_path for a throwaway database (used in tests).
    """

    def __init__(self, db_path: str = "chat.db") -> None:
        # FastAPI runs sync endpoints in a thread pool, so allow cross-thread
        # use and serialise access with a lock.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    # ---- conversation history -------------------------------------------

    def add_message(self, user_id: str, session_id: str, role: str, content: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages (user_id, session_id, role, content) VALUES (?, ?, ?, ?)",
                (user_id, session_id, role, content),
            )

    def recent_messages(self, user_id: str, session_id: str, limit: int) -> list[dict]:
        """Return the last `limit` messages of a session, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages "
                "WHERE user_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, session_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # ---- long-term memory -----------------------------------------------

    def save_memory(self, user_id: str, key: str, value: str) -> None:
        """Insert a memory, or replace the existing one for the same category."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO memories (user_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT (user_id, key) DO UPDATE "
                "SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                (user_id, key, value),
            )

    def get_memories(self, user_id: str) -> list[Memory]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM memories WHERE user_id = ? ORDER BY key",
                (user_id,),
            ).fetchall()
        return [Memory(r["key"], r["value"]) for r in rows]
