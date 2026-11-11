"""Детерминированное формирование резюме и снимка диалога для заявки.

Это НЕ ИИ-резюмирование: используются только прямые цитаты сообщений
клиента и факт наличия/отсутствия переписки. После подключения настоящей
модели здесь можно заменить build_summary на LLM-вариант — снимок
(conversation_snapshot) уже сохраняет исходный контекст.
"""

from __future__ import annotations

import json
from typing import Any

from .. import storage

# Ограничения объёма снимка: храним только необходимый контекст,
# без sources/latency/ai_status и прочих технических полей.
MAX_SNAPSHOT_MESSAGES = 50
MAX_SNAPSHOT_CHARS = 8000
MAX_MESSAGE_CHARS = 2000

EMPTY_DIALOG_SUMMARY = (
    "Заявка на консультацию по решениям МТС EnergyTool. "
    "Диалог не содержит сообщений клиента — детали обращения не уточнены."
)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def build_summary(messages: list[dict[str, Any]]) -> str:
    """Краткое описание обращения на основе слов самого клиента.

    - Основа — первое содержательное сообщение пользователя.
    - Последние сообщения клиента добавляются как прямые цитаты-уточнения.
    - Никаких придуманных фактов, рекомендаций и цифр.
    """
    user_texts = [
        m["content"].strip()
        for m in messages
        if m.get("role") == "user" and str(m.get("content", "")).strip()
    ]
    if not user_texts:
        return EMPTY_DIALOG_SUMMARY

    parts = [_clip(user_texts[0], 400)]
    if len(user_texts[0]) < 30:
        parts.append("Детали обращения не уточнены.")

    # Последние значимые сообщения клиента — как прямые цитаты, без осмысления.
    extras = user_texts[1:]
    if extras:
        quotes = [_clip(e, 160) for e in extras[-2:]]
        parts.append("Уточнения клиента: " + "; ".join(f"«{q}»" for q in quotes))

    return _clip("\n".join(parts), 1200)


def build_snapshot(messages: list[dict[str, Any]]) -> str:
    """JSON-снимок переписки: только role+content, ограниченный объём.

    Берутся самые свежие сообщения в пределах лимитов — они наиболее
    релевантны для менеджера. Первое сообщение клиента дополнительно
    отражено в summary.
    """
    items: list[dict[str, str]] = []
    total = 0
    for m in reversed(messages):
        role = m.get("role")
        content = str(m.get("content", "")).strip()
        if role not in ("user", "assistant") or not content:
            continue
        clipped = _clip(content, MAX_MESSAGE_CHARS)
        size = len(clipped) + 40
        if len(items) >= MAX_SNAPSHOT_MESSAGES or total + size > MAX_SNAPSHOT_CHARS:
            break
        items.append({"role": role, "content": clipped})
        total += size
    items.reverse()
    return json.dumps(items, ensure_ascii=False)


def build_lead_context(session_id: str) -> tuple[str, str]:
    """Сформировать (summary, conversation_snapshot_json) из SQLite."""
    messages = storage.list_messages(session_id)
    return build_summary(messages), build_snapshot(messages)
