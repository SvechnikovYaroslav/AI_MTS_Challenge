"""Маршруты сессий и сообщений."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import storage
from ..schemas import MessagesPage, SessionOut

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session() -> dict:
    return storage.create_session()


@router.get("/sessions", response_model=dict)
def list_sessions() -> dict:
    return {"sessions": storage.list_sessions()}


@router.get("/sessions/{session_id}/messages", response_model=MessagesPage)
def get_messages(session_id: str) -> dict:
    if not storage.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": storage.list_messages(session_id)}
