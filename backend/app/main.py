"""MTS EnergyTool AI Consultant — backend (FastAPI + SQLite)."""

from __future__ import annotations

from pathlib import Path

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# .env может лежать в корне репозитория (рядом с compose.yaml) или в backend/.
for candidate in (Path(__file__).resolve().parents[3] / ".env", Path.cwd() / ".env"):
    if candidate.exists():
        load_dotenv(candidate)
        break

from .routes import chat, leads, sessions  # noqa: E402
from .services import ai_service  # noqa: E402
from .storage import init_db  # noqa: E402

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="MTS EnergyTool AI Consultant", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # демо-режим; при необходимости сузить до frontend origin
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(leads.router)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "ai_mode": ai_service.AI_MODE,
        "ai_status": "mock" if ai_service.AI_MODE == "MOCK" else "real",
        "version": app.version,
    }
