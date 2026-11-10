"""Pydantic-схемы API. Контракт — docs/api-contract.md."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int = 0


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


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[dict[str, Any]]
    latency_ms: int
    suggest_lead: bool
    ai_status: str


class LeadCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=5, max_length=32)
    company: str = Field(default="", max_length=200)
    session_id: str | None = None


class LeadOut(BaseModel):
    id: int
    name: str
    phone: str
    company: str
    session_id: str | None
    created_at: str


class LeadsPage(BaseModel):
    leads: list[LeadOut]
