"""Small SQLite store for durable conversation state.

The Web process keeps conversations in memory for speed, while this store is
the recovery source after an LRU eviction or process restart. It intentionally
has no network identity model: ``session_id`` is a local locator and the Web
app must be kept on loopback when no authentication layer is configured.
"""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from .conversation import Conversation
from .user_memory import extract_user_facts, memory_score


class SessionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    memory_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS messages (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    message_time TEXT NOT NULL,
                    PRIMARY KEY(session_id, seq)
                );
                CREATE TABLE IF NOT EXISTS user_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    source_seq INTEGER,
                    status TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL,
                    retrieval_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(session_id, kind, value)
                );
                CREATE TABLE IF NOT EXISTS turns (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    turn_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    user_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT,
                    played_indices TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(session_id, turn_id)
                );
                """
            )
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(user_memories)")}
            if "source_seq" not in columns:
                db.execute("ALTER TABLE user_memories ADD COLUMN source_seq INTEGER")
            if "status" not in columns:
                db.execute("ALTER TABLE user_memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            # A process restart cannot continue an in-flight turn. Mark it as
            # interrupted so recovery never presents it as a completed reply.
            db.execute("UPDATE turns SET status = 'interrupted' WHERE status = 'active'")

    def begin_turn(self, session_id: str, turn_id: str, generation: int, user_text: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(session_id) VALUES (?) ON CONFLICT(session_id) DO NOTHING",
                (session_id,),
            )
            db.execute(
                "INSERT OR REPLACE INTO turns(session_id, turn_id, generation, user_text, status) "
                "VALUES (?, ?, ?, ?, 'active')",
                (session_id, turn_id, generation, user_text),
            )

    def finish_turn(
        self, session_id: str, turn_id: str, status: str, played_indices: set[int]
    ) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE turns SET status = ?, finished_at = CURRENT_TIMESTAMP, played_indices = ? "
                "WHERE session_id = ? AND turn_id = ?",
                (status, json.dumps(sorted(played_indices)), session_id, turn_id),
            )

    def load(self, session_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            session = db.execute(
                "SELECT summary FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session is None:
                return None
            rows = db.execute(
                "SELECT role, content, message_time FROM messages "
                "WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ).fetchall()
        return {
            "summary": str(session["summary"]),
            "messages": [
                {"role": str(row["role"]), "content": str(row["content"])}
                for row in rows
            ],
            "message_times": [str(row["message_time"]) for row in rows],
        }

    def save(self, session_id: str, conversation: Conversation) -> None:
        snapshot = conversation.snapshot()
        messages = snapshot["messages"]
        times = snapshot["message_times"]
        summary = snapshot["summary"]
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(session_id, summary) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary, "
                "updated_at=CURRENT_TIMESTAMP",
                (session_id, summary),
            )
            db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            db.executemany(
                "INSERT INTO messages(session_id, seq, role, content, message_time) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (session_id, index, message["role"], message["content"], times[index])
                    for index, message in enumerate(messages)
                ],
            )

    def memory_enabled(self, session_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT memory_enabled FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return bool(row and row["memory_enabled"])

    def set_memory_enabled(self, session_id: str, enabled: bool) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(session_id, memory_enabled) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET memory_enabled=excluded.memory_enabled",
                (session_id, int(enabled)),
            )

    def remember_user_message(
        self, session_id: str, text: str, *, source_seq: int | None = None
    ) -> list[dict[str, object]]:
        if not self.memory_enabled(session_id):
            return []
        facts = extract_user_facts(text)
        if not facts:
            return []
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            for kind, value in facts:
                if kind == "name":
                    db.execute(
                        "UPDATE user_memories SET status = 'superseded' "
                        "WHERE session_id = ? AND kind = ? AND value != ? AND status = 'active'",
                        (session_id, kind, value),
                    )
                db.execute(
                    "INSERT INTO user_memories(session_id, kind, value, source_text, source_seq, status, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'active', ?) ON CONFLICT(session_id, kind, value) DO UPDATE SET "
                    "source_text=excluded.source_text, source_seq=excluded.source_seq, "
                    "status='active', updated_at=excluded.updated_at",
                    (session_id, kind, value, text, source_seq, now),
                )
        return self.list_memories(session_id)

    def list_memories(self, session_id: str) -> list[dict[str, object]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, kind, value, source_text, source_seq, status, updated_at, retrieval_count "
                "FROM user_memories WHERE session_id = ? AND status = 'active' "
                "ORDER BY updated_at DESC, id DESC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recall(self, session_id: str, query: str, limit: int = 4) -> list[str]:
        if not self.memory_enabled(session_id):
            return []
        relevant = [
            item for item in self.list_memories(session_id)
            if item["kind"] == "name"
            or str(item["value"]) in query
            or (item["kind"] == "preference" and any(word in query for word in ("喜欢", "爱吃", "偏好")))
            or (item["kind"] == "dislike" and any(word in query for word in ("不喜欢", "讨厌")))
        ]
        ranked = sorted(
            relevant,
            key=lambda item: memory_score(
                kind=str(item["kind"]), updated_at=str(item["updated_at"]),
                retrieval_count=int(item["retrieval_count"]), query=query,
                value=str(item["value"]),
            ),
            reverse=True,
        )[:limit]
        with self._connect() as db:
            db.executemany(
                "UPDATE user_memories SET retrieval_count = retrieval_count + 1 WHERE id = ?",
                [(item["id"],) for item in ranked],
            )
        return [
            f"{item['kind']}: {item['value']}（用户原话：{item['source_text']}；来源消息序号：{item['source_seq']}）"
            for item in ranked
        ]

    def delete_memory(self, session_id: str, memory_id: int) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE user_memories SET status = 'deleted' WHERE session_id = ? AND id = ?",
                (session_id, memory_id),
            )

    def delete(self, session_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
