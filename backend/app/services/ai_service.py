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

# Четыре демонстрационных сценария: точное совпадение с текстами
# стартовых карточек frontend (WelcomeScreen). Никакого fuzzy matching —
# для произвольных сообщений возвращается NEUTRAL_MOCK_ANSWER.
MOCK_SCENARIOS: dict[str, tuple[str, list[dict[str, Any]]]] = {
    # 1. Снижение затрат на электроэнергию
    "расходы предприятия на электричество выросли. что можно сделать?": (
        "Для начала разберём ваш счёт за электроэнергию: проанализируем "
        "ценовую категорию, параметры объекта (присоединённая мощность, "
        "график потребления) и возможные резервы снижения затрат. "
        "Пришлите последние 2–3 счёта или скажите, к какой ценовой "
        "категории относится объект — подскажем, с чего начать.",
        [{"file": "11-price-categories.md", "mock": True}, {"file": "14-tariffs.md", "mock": True}],
    ),
    # 2. Облачный учёт нескольких объектов
    "у нас несколько магазинов. можно контролировать их потребление в одном кабинете?": (
        "Да, для этого подходит облачный учёт МТС EnergyTool (ASKUE): "
        "все точки потребления отображаются в одном кабинете — текущий "
        "расход, показания счётчиков, уведомления об отклонениях. "
        "Сколько у вас объектов и какая у них сейчас система учёта?",
        [{"file": "22-askue.md", "mock": True}, {"file": "13-metering.md", "mock": True}],
    ),
    # 3. Солнечная генерация
    "хотим установить солнечные панели на складе. с чего начать?": (
        "Для склада можно рассмотреть сетевую или гибридную солнечную "
        "электростанцию. Нужно оценить параметры объекта: площадь кровли, "
        "потребление электроэнергии, график нагрузки и условия "
        "присоединения к сети. Пришлите данные по объекту — подберём "
        "конфигурацию и следующий шаг.",
        [{"file": "23-solar.md", "mock": True}, {"file": "15-microgeneration.md", "mock": True}],
    ),
    # 4. Коммерческие потери (без утверждения о доказанном хищении)
    "наша электросетевая компания хочет эффективнее выявлять подозрительные точки учёта.": (
        "Для электросетевой компании подойдёт инструмент выявления "
        "коммерческих потерь: система анализирует данные учёта и "
        "приоритизирует подозрительные точки для проверки. Важно: это "
        "инструмент приоритизации проверок, а не доказательство хищения — "
        "решения принимает ваша служба.",
        [{"file": "24-losses.md", "mock": True}],
    ),
}

NEUTRAL_MOCK_ANSWER = (
    "Сейчас работает демонстрационный MOCK-режим: ответ не формируется "
    "по базе знаний МТС и не является консультацией. Настоящий ответ "
    "будет доступен после подключения AI Core (режим REAL). Вы можете "
    "задать один из четырёх стартовых вопросов или оформить заявку "
    "менеджеру."
)


def _normalize_mock_key(text: str) -> str:
    return " ".join(text.split()).casefold()
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
    scenario = MOCK_SCENARIOS.get(_normalize_mock_key(message))
    if scenario is None:
        return _finish(
            session_id,
            NEUTRAL_MOCK_ANSWER,
            [],
            start,
            ai_status="mock",
        )
    answer_text, sources = scenario
    return _finish(
        session_id,
        answer_text,
        [dict(s) for s in sources],
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
