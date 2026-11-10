"""Маршруты заявок: POST/GET /api/leads (демонстрационный режим)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import storage
from ..schemas import LeadCreate, LeadOut, LeadsPage

router = APIRouter(prefix="/api", tags=["leads"])


@router.post("/leads", response_model=LeadOut, status_code=201)
def create_lead(lead: LeadCreate) -> dict:
    return storage.add_lead(lead.name, lead.phone, lead.company, lead.session_id)


@router.get("/leads", response_model=LeadsPage)
def list_leads() -> dict:
    return {"leads": storage.list_leads()}
