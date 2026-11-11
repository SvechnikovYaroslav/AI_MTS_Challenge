"""Маршруты сессий и сообщений."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import storage
from ..schemas import MessagesPage, SessionCreated

router = APIRouter(prefix="/api", tags=["sessions"])


def _check_token(session_id: str, token: str | None) -> None:
    if not storage.verify_session_token(session_id, token):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")


@router.post("/sessions", response_model=SessionCreated, status_code=201)
def create_session() -> dict:
    return storage.create_session()


@router.get("/sessions", response_model=dict)
def list_sessions() -> dict:
    # Токены сессий в список не попадают — см. SessionOut без поля token.
    return {"sessions": storage.list_sessions()}


@router.get("/sessions/{session_id}/messages", response_model=MessagesPage)
def get_messages(session_id: str, token: str | None = Query(default=None)) -> dict:
    if not storage.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    _check_token(session_id, token)
    return {"session_id": session_id, "messages": storage.list_messages(session_id)}


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, token: str | None = Query(default=None)) -> None:
    if not storage.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    _check_token(session_id, token)
    storage.delete_session(session_id)
