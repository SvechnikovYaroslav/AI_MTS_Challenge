"""Тесты backend API (fastapi.testclient)."""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# backend/ должен быть в sys.path для `import app`.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = str(Path(_tmp) / "test.db")
os.environ["AI_MODE"] = "MOCK"
os.environ["EXPOSE_LEADS"] = "1"  # GET /api/leads только для тестов/локальной разработки

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import normalize_ru_phone  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def create_session(client) -> tuple[str, str]:
    r = client.post("/api/sessions")
    assert r.status_code == 201
    body = r.json()
    return body["id"], body["token"]


def chat(client, sid: str, token: str, message: str):
    return client.post(
        "/api/chat",
        json={"session_id": sid, "message": message, "session_token": token},
    )


def get_messages(client, sid: str, token: str):
    return client.get(f"/api/sessions/{sid}/messages", params={"token": token})


STARTER_QUESTIONS = [
    "Расходы предприятия на электричество выросли. Что можно сделать?",
    "У нас несколько магазинов. Можно контролировать их потребление в одном кабинете?",
    "Хотим установить солнечные панели на складе. С чего начать?",
    "Наша электросетевая компания хочет эффективнее выявлять подозрительные точки учёта.",
]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_session_and_chat_flow(client):
    sid, token = create_session(client)

    r = chat(client, sid, token, STARTER_QUESTIONS[1])
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert body["sources"] and body["sources"][0].get("mock") is True
    assert body["ai_status"] == "mock"

    r = get_messages(client, sid, token)
    assert r.status_code == 200
    roles = [m["role"] for m in r.json()["messages"]]
    assert roles == ["user", "assistant"]


def test_sessions_history_preserved(client):
    r1 = client.post("/api/sessions").json()
    r2 = client.post("/api/sessions").json()
    assert r1["id"] != r2["id"]
    chat(client, r1["id"], r1["token"], "hi")

    sessions = client.get("/api/sessions").json()["sessions"]
    ids = {s["id"] for s in sessions}
    assert {r1["id"], r2["id"]} <= ids
    # Токены не утекают в список сессий
    assert all("token" not in s for s in sessions)
    msgs = get_messages(client, r1["id"], r1["token"]).json()["messages"]
    assert len(msgs) == 2


def test_session_token_required(client):
    sid, token = create_session(client)
    # chat без токена и с неверным токеном
    assert chat(client, sid, "", "hi").status_code == 403
    assert chat(client, sid, "wrong-token", "hi").status_code == 403
    # messages без токена
    assert client.get(f"/api/sessions/{sid}/messages").status_code == 403
    assert get_messages(client, sid, "wrong").status_code == 403
    # delete без токена
    assert client.delete(f"/api/sessions/{sid}").status_code == 403
    # с верным токеном всё работает
    assert chat(client, sid, token, "hi").status_code == 200


def test_chat_unknown_session_404(client):
    r = client.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404


# --- MOCK-режим: четыре стартовых сценария ---

def test_mock_starter_scenarios(client):
    sid, token = create_session(client)
    answers = []
    for q in STARTER_QUESTIONS:
        r = chat(client, sid, token, q)
        assert r.status_code == 200
        body = r.json()
        assert body["ai_status"] == "mock"
        assert body["sources"], f"empty sources for {q!r}"
        assert all(s.get("mock") is True for s in body["sources"])
        answers.append(body["answer"])

    assert len(set(answers)) == 4
    assert "ценов" in answers[0].lower()
    assert "кабинет" in answers[1].lower()
    assert "сетев" in answers[2].lower() or "гибридн" in answers[2].lower()
    assert "приоритиз" in answers[3].lower() and "хищен" in answers[3].lower()


def test_mock_neutral_answer(client):
    sid, token = create_session(client)
    r = chat(client, sid, token, "Какая сегодня погода?")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "mock"
    assert "демонстрацион" in body["answer"].lower() or "MOCK" in body["answer"]
    assert body["sources"] == []


def test_session_title_from_first_message(client):
    sid, token = create_session(client)
    chat(client, sid, token, STARTER_QUESTIONS[1])

    sessions = client.get("/api/sessions").json()["sessions"]
    title = next(s["title"] for s in sessions if s["id"] == sid)
    assert title != "Новый диалог"
    assert "магазин" in title.lower()

    sessions2 = client.get("/api/sessions").json()["sessions"]
    assert next(s["title"] for s in sessions2 if s["id"] == sid) == title


# --- Заявки: контекст, резюме, снимок ---

def test_lead_flow(client):
    sid, token = create_session(client)
    r = client.post(
        "/api/leads",
        json={
            "name": "Тест Тестов",
            "phone": "+7 000 111-22-33",
            "company": "Test",
            "session_id": sid,
            "session_token": token,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"]
    assert body["phone"] == "+70001112233"  # нормализовано
    assert "summary" in body and "conversation_snapshot" in body

    leads = client.get("/api/leads").json()["leads"]
    assert any(l["name"] == "Тест Тестов" for l in leads)


def test_lead_context_saved(client):
    sid, token = create_session(client)
    chat(client, sid, token, "Нужен учёт электроэнергии на трёх складах")
    chat(client, sid, token, "Объекты в разных городах, ищем облачное решение")

    r = client.post(
        "/api/leads",
        json={"name": "Контекст Тестов", "phone": "9531234567", "session_id": sid, "session_token": token},
    )
    assert r.status_code == 201
    body = r.json()

    # Резюме построено из слов клиента
    assert "склад" in body["summary"].lower()
    # Снимок содержит обе пары сообщений, только role+content
    snap = body["conversation_snapshot"]
    assert len(snap) == 4
    assert all(set(m.keys()) == {"role", "content"} for m in snap)
    assert [m["role"] for m in snap] == ["user", "assistant", "user", "assistant"]
    # Телефон нормализован на backend
    assert body["phone"] == "+79531234567"


def test_lead_empty_session(client):
    sid, token = create_session(client)
    r = client.post(
        "/api/leads",
        json={"name": "Пустой Диалог", "phone": "+79000000000", "session_id": sid, "session_token": token},
    )
    assert r.status_code == 201
    body = r.json()
    assert "не содержит сообщений" in body["summary"] or "не уточнены" in body["summary"]
    assert body["conversation_snapshot"] == []


def test_lead_unknown_session_404(client):
    r = client.post(
        "/api/leads",
        json={"name": "Нет Сессии", "phone": "+79000000000", "session_id": "nope", "session_token": "x"},
    )
    assert r.status_code == 404


def test_lead_requires_valid_token(client):
    sid, _token = create_session(client)
    chat(client, sid, _token, "привет")
    # Без токена и с чужим токеном контекст чужой сессии не отдаём
    r1 = client.post(
        "/api/leads",
        json={"name": "Чужой Токен", "phone": "+79000000000", "session_id": sid},
    )
    assert r1.status_code == 403
    r2 = client.post(
        "/api/leads",
        json={"name": "Чужой Токен", "phone": "+79000000000", "session_id": sid, "session_token": "forged"},
    )
    assert r2.status_code == 403


def test_leads_listing_restricted(client, monkeypatch):
    # Без EXPOSE_LEADS диагностический список заявок закрыт
    monkeypatch.delenv("EXPOSE_LEADS", raising=False)
    assert client.get("/api/leads").status_code == 404


# --- Удаление диалогов ---

def test_delete_session_removes_messages_keeps_lead(client):
    sid, token = create_session(client)
    chat(client, sid, token, "Тест на удаление")
    client.post(
        "/api/leads",
        json={"name": "Лид Лидов", "phone": "+7 000 222-33-44", "company": "KeepCo", "session_id": sid, "session_token": token},
    )

    r = client.delete(f"/api/sessions/{sid}", params={"token": token})
    assert r.status_code == 204

    assert client.get(f"/api/sessions/{sid}/messages", params={"token": token}).status_code == 404
    ids = {s["id"] for s in client.get("/api/sessions").json()["sessions"]}
    assert sid not in ids

    # Заявка и её контекст сохраняются после удаления диалога
    leads = client.get("/api/leads").json()["leads"]
    lead = next(l for l in leads if l["name"] == "Лид Лидов")
    assert lead["session_id"] == sid
    assert lead["summary"]
    assert lead["conversation_snapshot"]


def test_delete_unknown_session_404(client):
    assert client.delete("/api/sessions/does-not-exist", params={"token": "x"}).status_code == 404


# --- Телефон ---

def test_phone_normalization():
    assert normalize_ru_phone("9531234567") == "+79531234567"
    assert normalize_ru_phone("89531234567") == "+79531234567"
    assert normalize_ru_phone("79531234567") == "+79531234567"
    assert normalize_ru_phone("+79531234567") == "+79531234567"
    assert normalize_ru_phone("+7 (953) 123-45-67") == "+79531234567"


def test_phone_rejects_invalid(client):
    for bad in ["123", "+7 (953) 123-45", "12345678901234567890", ""]:
        r = client.post("/api/leads", json={"name": "Bad Phone", "phone": bad})
        assert r.status_code == 422, f"phone={bad!r} should be rejected"


# --- Миграция старой схемы ---

OLD_SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    sources_json TEXT, latency_ms INTEGER, ai_status TEXT, created_at TEXT NOT NULL
);
CREATE TABLE leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, phone TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '', session_id TEXT, created_at TEXT NOT NULL
);
"""


def test_migration_old_schema(tmp_path, monkeypatch):
    from app import storage

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO leads (name, phone, company, session_id, created_at) VALUES (?,?,?,?,?)",
        ("Старый Лид", "+79000000000", "OldCo", None, "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(storage, "DB_PATH", db)
    storage.init_db()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    session_cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    lead_cols = {r["name"] for r in conn.execute("PRAGMA table_info(leads)")}
    conn.close()
    assert "token" in session_cols
    assert {"summary", "conversation_snapshot"} <= lead_cols

    leads = storage.list_leads()
    assert leads[0]["name"] == "Старый Лид"
    assert leads[0]["summary"] == ""
    assert leads[0]["conversation_snapshot"] == []
