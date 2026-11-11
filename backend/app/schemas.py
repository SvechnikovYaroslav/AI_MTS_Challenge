"""Pydantic-схемы API. Контракт — docs/api-contract.md."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def normalize_ru_phone(raw: str) -> str:
    """Нормализовать российский номер к виду +7XXXXXXXXXX.

    Принимает: 9531234567, 89531234567, 79531234567, +79531234567,
    а также форматированные варианты (+7 (953) 123-45-67 и т.п.).
    Отклоняет неполные и произвольные длинные последовательности цифр —
    без обрезки до «последних десяти».
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    subscriber = digits[1:] if digits.startswith("7") else digits
    if len(subscriber) != 10 or not subscriber.isdigit():
        raise ValueError("Некорректный номер телефона: ожидается +7 и 10 цифр")
    return "+7" + subscriber


class SessionCreate(BaseModel):
    """Тело POST /api/sessions (все поля опциональны)."""

    visitor_id: str | None = Field(default=None, max_length=64)


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int = 0


class SessionCreated(SessionOut):
    """Ответ POST /api/sessions: содержит секретный токен сессии.

    Токен выдаётся один раз при создании и НЕ возвращается в списке сессий.
    """

    token: str


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    sources: list[dict[str, Any]] | None = None
    latency_ms: int | None = None
    ai_status: str | None = None
    created_at: str


class MessagesPage(BaseModel):
    session_id: str
    messages: list[MessageOut]


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4000)
    session_token: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[dict[str, Any]]
    latency_ms: int
    suggest_lead: bool
    ai_status: str


class LeadCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=5, max_length=40)
    company: str = Field(default="", max_length=200)
    session_id: str | None = None
    session_token: str | None = None

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        return normalize_ru_phone(v)


class SnapshotMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LeadOut(BaseModel):
    id: int
    name: str
    phone: str
    company: str
    session_id: str | None
    summary: str = ""
    conversation_snapshot: list[SnapshotMessage] = []
    created_at: str


class LeadsPage(BaseModel):
    leads: list[LeadOut]
