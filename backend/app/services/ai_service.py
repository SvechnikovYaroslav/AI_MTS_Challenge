"""Адаптер AI Core для backend.

AI_MODE=MOCK  — тестовый ответ с явно помеченными mock-источниками.
AI_MODE=REAL — вызов ai_engine.answer_question из корня репозитория.
               Если AI Core не реализован — честный статус not_implemented,
               БЕЗ скрытого fallback на MOCK.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

AI_MODE = os.environ.get("AI_MODE", "MOCK").upper()

# Корень репозитория (родитель backend/) — там лежит ai_engine.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

MOCK_ANSWER = (
    "Для контроля расхода электроэнергии в нескольких объектах подойдёт "
    "облачная платформа учёта МТС EnergyTool (например, ASKUE). "
    "Сколько у вас объектов и какой средний месячный расход электроэнергии?"
)
MOCK_SOURCES = [{"file": "22-askue.md", "mock": True}]
NOT_IMPLEMENTED_ANSWER = (
    "Режим REAL включён, но AI Core ещё не реализован "
    "(ai_engine.AI_CORE_READY = False). Дождитесь версии от ML-участника "
    "или используйте AI_MODE=MOCK."
)


def _suggest_lead(message: str) -> bool:
    keywords = ("заявк", "менеджер", "консультац", "связаться", "позвоните")
    return any(k in message.lower() for k in keywords)


def answer(session_id: str, message: str) -> dict[str, Any]:
    """Сформировать ответ консультанта. Возвращает dict по контракту /api/chat."""
    start = time.perf_counter()

    if AI_MODE == "REAL":
        return _answer_real(session_id, message, start)
    return _answer_mock(session_id, message, start)


def _finish(session_id: str, answer_text: str, sources: list, start: float, ai_status: str, suggest: bool | None = None) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "answer": answer_text,
        "sources": sources,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "suggest_lead": _suggest_lead(answer_text) if suggest is None else suggest,
        "ai_status": ai_status,
    }


def _answer_mock(session_id: str, message: str, start: float) -> dict[str, Any]:
    return _finish(
        session_id,
        MOCK_ANSWER,
        list(MOCK_SOURCES),
        start,
        ai_status="mock",
    )


def _answer_real(session_id: str, message: str, start: float) -> dict[str, Any]:
    try:
        import ai_engine
    except ImportError as exc:
        return _finish(
            session_id,
            f"AI Core недоступен: не удалось импортировать ai_engine ({exc}).",
            [],
            start,
            ai_status="not_implemented",
            suggest=False,
        )

    if not getattr(ai_engine, "AI_CORE_READY", False):
        return _finish(
            session_id,
            NOT_IMPLEMENTED_ANSWER,
            [],
            start,
            ai_status="not_implemented",
            suggest=False,
        )

    try:
        result = ai_engine.answer_question(message)
    except NotImplementedError as exc:
        return _finish(session_id, f"AI Core не реализован: {exc}", [], start, ai_status="not_implemented", suggest=False)
    except Exception as exc:  # noqa: BLE001
        return _finish(session_id, f"Ошибка AI Core: {exc}", [], start, ai_status="error", suggest=False)

    return _finish(
        session_id,
        str(result.get("answer", "")),
        list(result.get("sources", [])),
        start,
        ai_status="real",
        suggest=bool(result.get("suggest_lead")),
    )
