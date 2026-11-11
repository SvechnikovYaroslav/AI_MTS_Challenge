"""Маршруты сессий и сообщений."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from .. import storage
from ..schemas import MessagesPage, SessionCreate, SessionCreated

router = APIRouter(prefix="/api", tags=["sessions"])


def _check_token(session_id: str, token: str | None) -> None:
    if not storage.verify_session_token(session_id, token):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")


@router.post("/sessions", response_model=SessionCreated, status_code=201)
def create_session(payload: SessionCreate | None = Body(default=None)) -> dict:
    visitor_id = payload.visitor_id if payload else None
    return storage.create_session(visitor_id=visitor_id)


@router.get("/sessions", response_model=dict)
def list_sessions(visitor_id: str | None = Query(default=None)) -> dict:
    # История изолирована по visitor_id: без него список пуст,
    # токены сессий в ответ не попадают — см. SessionOut.
    return {"sessions": storage.list_sessions(visitor_id)}


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
