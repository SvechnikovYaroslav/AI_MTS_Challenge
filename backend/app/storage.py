"""Слой хранения на SQLite (stdlib sqlite3, без ORM).

Таблицы: sessions, messages, leads. Соединение на запрос,
check_same_thread=False + lock — достаточно для демо-нагрузки.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("DATABASE_PATH", "./data/app.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    token TEXT,
    visitor_id TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    sources_json TEXT,
    latency_ms INTEGER,
    ai_status TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    session_id TEXT,
    summary TEXT NOT NULL DEFAULT '',
    conversation_snapshot TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    """Лёгкая миграция: добавить колонку, если её нет (данные сохраняются)."""
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "sessions", "token", "TEXT")
        _ensure_column(conn, "sessions", "visitor_id", "TEXT")
        _ensure_column(conn, "leads", "summary", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "leads", "conversation_snapshot", "TEXT NOT NULL DEFAULT '[]'")
        # Бэкфилл токенов для сессий, созданных до введения токенов.
        for row in conn.execute("SELECT id FROM sessions WHERE token IS NULL").fetchall():
            conn.execute("UPDATE sessions SET token=? WHERE id=?", (uuid.uuid4().hex, row["id"]))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- sessions ----------

def create_session(title: str = "Новый диалог", visitor_id: str | None = None) -> dict[str, Any]:
    sid = str(uuid.uuid4())
    token = uuid.uuid4().hex
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, token, visitor_id) VALUES (?,?,?,?,?)",
            (sid, title, now, token, visitor_id or None),
        )
    return {"id": sid, "title": title, "created_at": now, "token": token}


def list_sessions(visitor_id: str | None = None) -> list[dict[str, Any]]:
    """Список сессий только одного посетителя.

    Без visitor_id возвращаем пустой список: глобальная история
    (названия чужих диалогов) не должна быть доступна всем.
    """
    if not visitor_id:
        return []
    with _lock, _connect() as conn:
        rows = conn.execute(
            """SELECT s.id, s.title, s.created_at,
                      COUNT(m.id) AS message_count
               FROM sessions s
               LEFT JOIN messages m ON m.session_id = s.id
               WHERE s.visitor_id = ?
               GROUP BY s.id
               ORDER BY s.created_at DESC""",
            (visitor_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def session_exists(session_id: str) -> bool:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
    return row is not None


def verify_session_token(session_id: str, token: str | None) -> bool:
    """Проверка владения сессией по секретному токену, выданному при создании.

    session_id сам по себе не является доказательством владения.
    """
    if not token:
        return False
    with _lock, _connect() as conn:
        row = conn.execute("SELECT token FROM sessions WHERE id=?", (session_id,)).fetchone()
    return bool(row and row["token"] and secrets.compare_digest(row["token"], token))


def delete_session(session_id: str) -> bool:
    """Удалить сессию вместе с сообщениями.

    Заявки (leads) НЕ удаляются: session_id в них остаётся как историческая
    ссылка на удалённый диалог.
    """
    with _lock, _connect() as conn:
        row = conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return True


# ---------- messages ----------

def _derive_title(text: str) -> str:
    """Короткое название диалога из первого вопроса пользователя."""
    flat = " ".join(text.split())
    if len(flat) > 60:
        flat = flat[:57].rstrip() + "…"
    return flat or "Новый диалог"


def add_message(
    session_id: str,
    role: str,
    content: str,
    sources: Any = None,
    latency_ms: int | None = None,
    ai_status: str | None = None,
) -> int:
    with _lock, _connect() as conn:
        prev_count = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE session_id=?", (session_id,)
        ).fetchone()["c"]
        cur = conn.execute(
            """INSERT INTO messages
               (session_id, role, content, sources_json, latency_ms, ai_status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                session_id,
                role,
                content,
                json.dumps(sources, ensure_ascii=False) if sources is not None else None,
                latency_ms,
                ai_status,
                _now(),
            ),
        )
        if role == "user" and prev_count == 0:
            conn.execute(
                "UPDATE sessions SET title=? WHERE id=?",
                (_derive_title(content), session_id),
            )
        return int(cur.lastrowid)


def list_messages(session_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """SELECT id, role, content, sources_json, latency_ms, ai_status, created_at
               FROM messages WHERE session_id=? ORDER BY id ASC""",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d.pop("sources_json")) if d.get("sources_json") else None
        out.append(d)
    return out


# ---------- leads ----------

def add_lead(
    name: str,
    phone: str,
    company: str,
    session_id: str | None,
    summary: str = "",
    conversation_snapshot: str = "[]",
) -> dict[str, Any]:
    """Атомарно сохранить заявку вместе с резюме и снимком переписки.

    summary и conversation_snapshot формируются сервером из SQLite,
    а не передаются клиентом.
    """
    now = _now()
    snapshot_obj = json.loads(conversation_snapshot) if conversation_snapshot else []
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO leads
               (name, phone, company, session_id, summary, conversation_snapshot, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                name.strip(),
                phone.strip(),
                company.strip(),
                session_id,
                summary,
                conversation_snapshot or "[]",
                now,
            ),
        )
        lead_id = int(cur.lastrowid)
    return {
        "id": lead_id,
        "name": name.strip(),
        "phone": phone.strip(),
        "company": company.strip(),
        "session_id": session_id,
        "summary": summary,
        "conversation_snapshot": snapshot_obj,
        "created_at": now,
    }


def list_leads() -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["conversation_snapshot"] = json.loads(d.get("conversation_snapshot") or "[]")
        except (TypeError, ValueError):
            d["conversation_snapshot"] = []
        d["summary"] = d.get("summary") or ""
        out.append(d)
    return out
