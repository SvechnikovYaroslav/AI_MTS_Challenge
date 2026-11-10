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

    r = client.post("/api/chat", json={"session_id": sid, "message": "Тестовое сообщение"})
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
