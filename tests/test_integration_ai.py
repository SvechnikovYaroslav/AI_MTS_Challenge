"""Интеграционные тесты: backend (web-app) + AI Core (ai-baseline).

Проверяют передачу session_context в REAL-режиме, изоляцию диалогов,
честные ошибки при отсутствии LLM и совместимость контрактов.
LLM всегда подменяется — реальная модель в тестах не используется.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT))

_tmp = Path(os.environ.get("DATABASE_PATH", ""))
if not _tmp.exists():
    import tempfile

    _tmp = Path(tempfile.mkdtemp()) / "integration.db"
os.environ.setdefault("DATABASE_PATH", str(_tmp))
os.environ.setdefault("AI_MODE", "MOCK")

from fastapi.testclient import TestClient  # noqa: E402

import ai_engine  # noqa: E402
import retrieval  # noqa: E402
from app.main import app  # noqa: E402
from app.services import ai_service  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _create_session(client, visitor="v-int") -> tuple[str, str]:
    r = client.post("/api/sessions", json={"visitor_id": visitor})
    assert r.status_code == 201
    return r.json()["id"], r.json()["token"]


def _chat(client, sid, token, message):
    return client.post(
        "/api/chat",
        json={"session_id": sid, "message": message, "session_token": token},
    )


# ---------- REAL-режим: передача session_context ----------

def test_real_mode_passes_session_context(client, monkeypatch):
    """Два сообщения подряд: второе получает историю первого, без дубля."""
    captured: list[dict] = []

    def fake_answer(question, session_context=None):
        captured.append({"q": question, "ctx": session_context or []})
        return {
            "answer": "Ответ консультанта",
            "sources": [{"file": "22-askue.md", "score": 1.0}],
            "suggest_lead": False,
        }

    monkeypatch.setattr(ai_service, "AI_MODE", "REAL")
    monkeypatch.setattr(ai_engine, "answer_question", fake_answer)

    sid, token = _create_session(client, "v-ctx")
    r1 = _chat(client, sid, token, "Первый вопрос про учёт")
    assert r1.status_code == 200
    assert r1.json()["ai_status"] == "real"

    r2 = _chat(client, sid, token, "Уточнение: три объекта")
    assert r2.status_code == 200
    assert r2.json()["ai_status"] == "real"

    assert len(captured) == 2
    # Первый вызов — без контекста.
    assert captured[0]["ctx"] == []
    # Второй вызов — история первого обмена, без текущего вопроса.
    ctx = captured[1]["ctx"]
    assert [m["role"] for m in ctx] == ["user", "assistant"]
    assert ctx[0]["content"] == "Первый вопрос про учёт"
    assert ctx[1]["content"] == "Ответ консультанта"
    assert all(set(m.keys()) == {"role", "content"} for m in ctx)
    assert not any("Уточнение" in m["content"] for m in ctx)
    assert captured[1]["q"] == "Уточнение: три объекта"


def test_real_mode_no_context_leak_between_sessions(client, monkeypatch):
    """Новый диалог не наследует историю предыдущего."""
    captured: list[list] = []

    def fake_answer(question, session_context=None):
        captured.append(session_context or [])
        return {"answer": "ok", "sources": [], "suggest_lead": False}

    monkeypatch.setattr(ai_service, "AI_MODE", "REAL")
    monkeypatch.setattr(ai_engine, "answer_question", fake_answer)

    sid_a, tok_a = _create_session(client, "v-a")
    sid_b, tok_b = _create_session(client, "v-b")

    _chat(client, sid_a, tok_a, "Секретная тема диалога А")
    _chat(client, sid_b, tok_b, "Вопрос из диалога Б")

    # Второй вызов (диалог Б) не должен содержать сообщений диалога А.
    assert captured[1] == []
    flat = " ".join(m["content"] for m in captured[1])
    assert "Секретная тема" not in flat


def test_real_mode_error_without_llm_config(client, monkeypatch):
    """REAL без настроенного LLM: честная ошибка, не MOCK и не «успех»."""
    # Настоящий answer_question дойдёт до _post_chat -> AICoreError,
    # т.к. LLM_* env не заданы. Чанки подменяем, чтобы дойти до LLM.
    monkeypatch.setattr(ai_service, "AI_MODE", "REAL")
    monkeypatch.setattr(
        retrieval, "retrieve",
        lambda q, top_k=None: [
            {"id": "x#c0", "file": "f.md", "section": "s", "score": 1.0,
             "content": "фрагмент"}
        ],
    )
    for v in ("LLM_BASE_URL", "QWEN_BASE_URL", "BASE_URL", "OPENAI_BASE_URL",
              "LLM_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY",
              "LLM_MODEL", "QWEN_MODEL", "GEN_MODEL", "OPENAI_MODEL"):
        monkeypatch.delenv(v, raising=False)

    sid, token = _create_session(client, "v-err")
    r = _chat(client, sid, token, "Вопрос без настроенной модели")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_status"] == "error"
    assert body["sources"] == []
    assert "error" in body["answer"].lower() or "AI Core" in body["answer"]
    assert isinstance(body["latency_ms"], int)
    # История не сломана: user-сообщение сохранено, assistant — ошибка.
    msgs = client.get(
        f"/api/sessions/{sid}/messages", params={"token": token}
    ).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["ai_status"] == "error"


def test_real_mode_sources_and_latency(client, monkeypatch):
    """REAL возвращает настоящие sources и latency_ms."""
    def fake_answer(question, session_context=None):
        return {
            "answer": "Детальный ответ",
            "sources": [{"file": "21-orem.md", "chunk_id": "21-orem.md#c001", "score": 9.9}],
            "suggest_lead": True,
        }

    monkeypatch.setattr(ai_service, "AI_MODE", "REAL")
    monkeypatch.setattr(ai_engine, "answer_question", fake_answer)

    sid, token = _create_session(client, "v-src")
    r = _chat(client, sid, token, "Что такое ОРЭМ?")
    body = r.json()
    assert body["ai_status"] == "real"
    assert body["sources"][0]["file"] == "21-orem.md"
    assert body["sources"][0]["chunk_id"] == "21-orem.md#c001"
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert body["suggest_lead"] is True


def test_mock_mode_still_works(client):
    """MOCK-режим не сломан интеграцией."""
    sid, token = _create_session(client, "v-mock")
    r = _chat(
        client, sid, token,
        "У нас несколько магазинов. Можно контролировать их потребление в одном кабинете?",
    )
    assert r.status_code == 200
    assert r.json()["ai_status"] == "mock"
    assert r.json()["sources"] and r.json()["sources"][0].get("mock") is True
