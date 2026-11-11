"""Маршрут чата: POST /api/chat."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import storage
from ..schemas import ChatRequest, ChatResponse
from ..services import ai_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> dict:
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message must not be empty")
    if len(message) > 4000:
        raise HTTPException(status_code=400, detail="Message too long (max 4000 chars)")
    if not storage.session_exists(req.session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if not storage.verify_session_token(req.session_id, req.session_token):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")

    storage.add_message(req.session_id, "user", message)

    result = ai_service.answer(req.session_id, message)

    storage.add_message(
        req.session_id,
        "assistant",
        result["answer"],
        sources=result["sources"],
        latency_ms=result["latency_ms"],
        ai_status=result["ai_status"],
    )
    return result
