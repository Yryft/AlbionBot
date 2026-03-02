from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from albionbot.storage.store import Store

from .schemas import CompTemplateCreateRequestDTO, RaidOpenRequestDTO
from .services import DashboardService


def create_app() -> FastAPI:
    data_path = os.getenv("DATA_PATH", "data/state.json").strip()
    bank_database_url = os.getenv("BANK_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    bank_sqlite_path = os.getenv("BANK_SQLITE_PATH", "data/bank.sqlite3").strip()

    store = Store(
        path=data_path,
        bank_database_url=bank_database_url,
        bank_sqlite_path=bank_sqlite_path,
    )
    service = DashboardService(store)

    app = FastAPI(title="AlbionBot Dashboard API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("DASHBOARD_CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/guilds")
    def list_guilds():
        return service.list_guilds()

    @app.get("/api/guilds/{guild_id}/tickets")
    def list_ticket_transcripts(guild_id: int):
        return service.list_ticket_transcripts(guild_id)

    @app.get("/api/guilds/{guild_id}/tickets/{ticket_id}")
    def get_ticket_transcript(guild_id: int, ticket_id: str):
        row = service.get_ticket_transcript(guild_id, ticket_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Ticket introuvable")
        return row

    @app.get("/api/raids")
    def list_raids():
        return service.list_raids()

    @app.get("/api/raid-templates")
    def list_templates():
        return service.list_raid_templates()

    @app.post("/api/actions/raids/open")
    def open_raid(payload: RaidOpenRequestDTO):
        try:
            return service.open_raid(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/actions/comp-wizard")
    def run_comp_wizard(payload: CompTemplateCreateRequestDTO):
        try:
            return service.create_comp_template_from_wizard(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
