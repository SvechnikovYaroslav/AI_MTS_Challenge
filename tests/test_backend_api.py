"""Тесты backend API (fastapi.testclient)."""

import os
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

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_session_and_chat_flow(client):
    r = client.post("/api/sessions")
    assert r.status_code == 201
    sid = r.json()["id"]

    r = client.post(
        "/api/chat",
        json={
            "session_id": sid,
            "message": "У нас несколько магазинов. Можно контролировать их потребление в одном кабинете?",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert body["sources"] and body["sources"][0].get("mock") is True
    assert body["ai_status"] == "mock"
    assert body["latency_ms"] >= 0
    assert body["suggest_lead"] in (True, False)

    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200
    roles = [m["role"] for m in r.json()["messages"]]
    assert roles == ["user", "assistant"]


def test_sessions_history_preserved(client):
    r1 = client.post("/api/sessions").json()
    r2 = client.post("/api/sessions").json()
    assert r1["id"] != r2["id"]
    client.post("/api/chat", json={"session_id": r1["id"], "message": "hi"})

    sessions = client.get("/api/sessions").json()["sessions"]
    ids = {s["id"] for s in sessions}
    assert {r1["id"], r2["id"]} <= ids
    # История первой сессии не удалена
    msgs = client.get(f"/api/sessions/{r1['id']}/messages").json()["messages"]
    assert len(msgs) == 2


def test_chat_unknown_session_404(client):
    r = client.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404


def test_lead_flow(client):
    sid = client.post("/api/sessions").json()["id"]
    r = client.post(
        "/api/leads",
        json={"name": "Тест Тестов", "phone": "+7 000 111-22-33", "company": "Test", "session_id": sid},
    )
    assert r.status_code == 201
    assert r.json()["id"]

    leads = client.get("/api/leads").json()["leads"]
    assert any(l["name"] == "Тест Тестов" for l in leads)


# --- MOCK-режим: четыре стартовых сценария ---

STARTER_QUESTIONS = [
    "Расходы предприятия на электричество выросли. Что можно сделать?",
    "У нас несколько магазинов. Можно контролировать их потребление в одном кабинете?",
    "Хотим установить солнечные панели на складе. С чего начать?",
    "Наша электросетевая компания хочет эффективнее выявлять подозрительные точки учёта.",
]


def test_mock_starter_scenarios(client):
    sid = client.post("/api/sessions").json()["id"]
    answers = []
    for q in STARTER_QUESTIONS:
        r = client.post("/api/chat", json={"session_id": sid, "message": q})
        assert r.status_code == 200
        body = r.json()
        assert body["ai_status"] == "mock"
        assert body["sources"], f"empty sources for {q!r}"
        assert all(s.get("mock") is True for s in body["sources"])
        answers.append(body["answer"])

    # Четыре разных ответа, каждый по своей теме
    assert len(set(answers)) == 4
    assert "ценов" in answers[0].lower()          # затраты: счёт, ценовая категория
    assert "кабинет" in answers[1].lower()       # учёт: один кабинет
    assert "сетев" in answers[2].lower() or "гибридн" in answers[2].lower()  # СЭС
    assert "приоритиз" in answers[3].lower() and "хищен" in answers[3].lower()  # потери


def test_mock_neutral_answer(client):
    sid = client.post("/api/sessions").json()["id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "Какая сегодня погода?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "mock"
    assert "демонстрацион" in body["answer"].lower() or "MOCK" in body["answer"]
    assert body["sources"] == []


def test_session_title_from_first_message(client):
    sid = client.post("/api/sessions").json()["id"]
    client.post(
        "/api/chat",
        json={"session_id": sid, "message": STARTER_QUESTIONS[1]},
    )

    sessions = client.get("/api/sessions").json()["sessions"]
    title = next(s["title"] for s in sessions if s["id"] == sid)
    assert title != "Новый диалог"
    assert "магазин" in title.lower()

    # Название сохраняется после «перезагрузки» (повторный запрос списка)
    sessions2 = client.get("/api/sessions").json()["sessions"]
    assert next(s["title"] for s in sessions2 if s["id"] == sid) == title


def test_delete_session_removes_messages_keeps_lead(client):
    sid = client.post("/api/sessions").json()["id"]
    client.post("/api/chat", json={"session_id": sid, "message": "Тест на удаление"})
    client.post(
        "/api/leads",
        json={"name": "Лид Лидов", "phone": "+7 000 222-33-44", "company": "KeepCo", "session_id": sid},
    )

    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 204

    # Сессия и сообщения удалены
    assert client.get(f"/api/sessions/{sid}/messages").status_code == 404
    ids = {s["id"] for s in client.get("/api/sessions").json()["sessions"]}
    assert sid not in ids

    # Заявка сохранена
    leads = client.get("/api/leads").json()["leads"]
    assert any(l["name"] == "Лид Лидов" and l["session_id"] == sid for l in leads)


def test_delete_unknown_session_404(client):
    assert client.delete("/api/sessions/does-not-exist").status_code == 404
