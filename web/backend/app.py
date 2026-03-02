from __future__ import annotations

import os
import secrets

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from albionbot.storage.store import Store

from .auth import (
    STATE_COOKIE,
    DiscordOAuthConfig,
    DiscordOAuthService,
    SessionManager,
    check_csrf,
    clear_session_cookies,
    require_session,
    set_session_cookies,
)
from .schemas import CompTemplateCreateRequestDTO, DiscordGuildDTO, DiscordUserDTO, MeDTO, RaidOpenRequestDTO
from .services import DashboardService


def _build_oauth_service() -> DiscordOAuthService | None:
    client_id = os.getenv("DISCORD_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("DISCORD_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("DISCORD_OAUTH_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        return None
    return DiscordOAuthService(
        config=DiscordOAuthConfig(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="identify guilds",
        ),
        session_manager=SessionManager(),
    )


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
    oauth_service = _build_oauth_service()

    app = FastAPI(title="AlbionBot Dashboard API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("DASHBOARD_CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    secure_cookies = os.getenv("DASHBOARD_COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes"}
    post_login_redirect = os.getenv("DASHBOARD_POST_LOGIN_REDIRECT", "/").strip() or "/"

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/auth/discord/login")
    def auth_discord_login():
        if oauth_service is None:
            raise HTTPException(status_code=503, detail="OAuth Discord non configuré")
        state = secrets.token_urlsafe(24)
        login_url = oauth_service.create_login_url(state)
        redirect = RedirectResponse(login_url, status_code=302)
        redirect.set_cookie(
            key=STATE_COOKIE,
            value=state,
            httponly=True,
            secure=secure_cookies,
            samesite="lax",
            max_age=600,
            path="/",
        )
        return redirect

    @app.get("/auth/discord/callback")
    def auth_discord_callback(request: Request, code: str = "", state: str = ""):
        if oauth_service is None:
            raise HTTPException(status_code=503, detail="OAuth Discord non configuré")
        state_cookie = request.cookies.get(STATE_COOKIE, "")
        if not state or state != state_cookie:
            raise HTTPException(status_code=400, detail="State OAuth invalide")
        if not code:
            raise HTTPException(status_code=400, detail="Code OAuth manquant")

        tokens = oauth_service.exchange_code(code)
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        expires_in = int(tokens.get("expires_in", 3600))
        if not access_token or not refresh_token:
            raise HTTPException(status_code=400, detail="Réponse OAuth invalide")

        user = oauth_service.fetch_user(access_token)
        user_guilds = oauth_service.fetch_user_guilds(access_token)
        session = oauth_service.sessions.create(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_in=expires_in,
            user=user,
            guilds=user_guilds,
        )

        redirect = RedirectResponse(f"{post_login_redirect}?logged_in=1", status_code=302)
        set_session_cookies(redirect, session, secure=secure_cookies)
        redirect.delete_cookie(STATE_COOKIE, path="/")
        return redirect

    @app.post("/auth/logout")
    def auth_logout(request: Request):
        if oauth_service is None:
            raise HTTPException(status_code=503, detail="OAuth Discord non configuré")
        check_csrf(request)
        session_id = request.cookies.get("albion_dash_session", "")
        if session_id:
            session = oauth_service.sessions.get(session_id)
            if session is not None and session.refresh_token:
                oauth_service.revoke_token(session.refresh_token)
            oauth_service.sessions.delete(session_id)
        response = Response(status_code=204)
        clear_session_cookies(response)
        return response

    @app.get("/me", response_model=MeDTO)
    def me(request: Request):
        if oauth_service is None:
            raise HTTPException(status_code=503, detail="OAuth Discord non configuré")
        session = require_session(request, oauth_service)
        bot_guild_map = service.get_bot_guild_map()
        shared_guilds = []
        for guild in session.guilds:
            guild_id = int(guild.get("id", 0))
            if guild_id not in bot_guild_map:
                continue
            shared_guilds.append(
                DiscordGuildDTO(
                    id=guild_id,
                    name=bot_guild_map[guild_id].name,
                    icon=guild.get("icon"),
                    owner=bool(guild.get("owner", False)),
                    permissions=str(guild.get("permissions", "0")),
                )
            )

        selected = session.selected_guild_id
        if selected is None and shared_guilds:
            selected = shared_guilds[0].id
            session.selected_guild_id = selected

        return MeDTO(
            user=DiscordUserDTO(
                id=str(session.user.get("id", "")),
                username=session.user.get("username", "unknown"),
                global_name=session.user.get("global_name"),
                avatar=session.user.get("avatar"),
            ),
            selected_guild_id=selected,
            guilds=shared_guilds,
        )

    @app.post("/me/select-guild/{guild_id}")
    def select_guild(guild_id: int, request: Request):
        if oauth_service is None:
            raise HTTPException(status_code=503, detail="OAuth Discord non configuré")
        check_csrf(request)
        session = require_session(request, oauth_service)
        user_guild_ids = {int(g.get("id", 0)) for g in session.guilds}
        bot_guild_ids = set(service.get_bot_guild_map().keys())
        if guild_id not in user_guild_ids or guild_id not in bot_guild_ids:
            raise HTTPException(status_code=403, detail="Guild non autorisée")
        session.selected_guild_id = guild_id
        return {"ok": True, "selected_guild_id": guild_id}

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
