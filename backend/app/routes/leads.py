"""Маршруты заявок: POST/GET /api/leads (демонстрационный режим)."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from .. import storage
from ..schemas import LeadCreate, LeadOut, LeadsPage
from ..services import lead_context

router = APIRouter(prefix="/api", tags=["leads"])


@router.post("/leads", response_model=LeadOut, status_code=201)
def create_lead(lead: LeadCreate) -> dict:
    summary = ""
    snapshot = "[]"
    if lead.session_id:
        if not storage.session_exists(lead.session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        # session_id сам по себе не доказывает владение — требуем токен.
        if not storage.verify_session_token(lead.session_id, lead.session_token):
            raise HTTPException(status_code=403, detail="Invalid or missing session token")
        # Контекст читается из SQLite на сервере, а не из запроса клиента.
        summary, snapshot = lead_context.build_lead_context(lead.session_id)
    return storage.add_lead(
        lead.name,
        lead.phone,
        lead.company,
        lead.session_id,
        summary=summary,
        conversation_snapshot=snapshot,
    )


@router.get("/leads", response_model=LeadsPage)
def list_leads() -> dict:
    # Диагностический endpoint: выдача всех заявок с персональными данными
    # разрешена только при явном EXPOSE_LEADS=1 (локальная разработка).
    if os.environ.get("EXPOSE_LEADS") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    return {"leads": storage.list_leads()}
