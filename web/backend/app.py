from __future__ import annotations

import os
import secrets
from urllib.parse import urlparse

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
from .authorization import DashboardAuthorizationService
from .schemas import CompTemplateCreateRequestDTO, DiscordGuildDTO, DiscordUserDTO, MeDTO, RaidOpenRequestDTO
from .command_bus import (
    AuditLogger,
    CommandBus,
    CommandContext,
    DomainError,
    OpenRaidFromTemplate,
    RateLimiter,
    StartCompWizardFlow,
)
from .services import DashboardService, OpenRaidFromTemplateHandler, StartCompWizardFlowHandler


OAUTH_REQUIRED_ENV_VARS = (
    "DISCORD_OAUTH_CLIENT_ID",
    "DISCORD_OAUTH_CLIENT_SECRET",
    "DISCORD_OAUTH_REDIRECT_URI",
)


def _missing_oauth_env_vars() -> list[str]:
    return [name for name in OAUTH_REQUIRED_ENV_VARS if not os.getenv(name, "").strip()]


def _oauth_not_configured_error() -> HTTPException:
    missing = _missing_oauth_env_vars()
    if not missing:
        detail = "OAuth Discord non configuré"
    else:
        detail = (
            "OAuth Discord non configuré. Variables manquantes: "
            + ", ".join(missing)
            + "."
        )
    return HTTPException(status_code=503, detail=detail)


def _build_oauth_service() -> DiscordOAuthService | None:
    if _missing_oauth_env_vars():
        return None
    client_id = os.getenv("DISCORD_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("DISCORD_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("DISCORD_OAUTH_REDIRECT_URI", "").strip()
    return DiscordOAuthService(
        config=DiscordOAuthConfig(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="identify guilds guilds.members.read",
        ),
        session_manager=SessionManager(),
    )


def _is_local_redirect_uri(redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _resolve_secure_cookies() -> bool:
    configured = os.getenv("DASHBOARD_COOKIE_SECURE")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes"}

    redirect_uri = os.getenv("DISCORD_OAUTH_REDIRECT_URI", "").strip()
    if redirect_uri and _is_local_redirect_uri(redirect_uri):
        return False
    return True


def _resolve_cookie_samesite() -> str:
    configured = os.getenv("DASHBOARD_COOKIE_SAMESITE")
    if configured is not None:
        normalized = configured.strip().lower()
        if normalized in {"lax", "strict", "none"}:
            return normalized

    redirect_uri = os.getenv("DISCORD_OAUTH_REDIRECT_URI", "").strip()
    if redirect_uri and _is_local_redirect_uri(redirect_uri):
        return "lax"
    return "none"


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
    command_bus = CommandBus(rate_limiter=RateLimiter(), audit_logger=AuditLogger())
    oauth_service = _build_oauth_service()
    authorizer = DashboardAuthorizationService(store, oauth_service) if oauth_service is not None else None

    app = FastAPI(title="AlbionBot Dashboard API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("DASHBOARD_CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    secure_cookies = _resolve_secure_cookies()
    cookie_samesite = _resolve_cookie_samesite()
    post_login_redirect = os.getenv("DASHBOARD_POST_LOGIN_REDIRECT", "/").strip() or "/"

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/auth/discord/login")
    def auth_discord_login():
        if oauth_service is None:
            raise _oauth_not_configured_error()
        state = secrets.token_urlsafe(24)
        login_url = oauth_service.create_login_url(state)
        redirect = RedirectResponse(login_url, status_code=302)
        redirect.set_cookie(
            key=STATE_COOKIE,
            value=state,
            httponly=True,
            secure=secure_cookies,
            samesite=cookie_samesite,
            max_age=600,
            path="/",
        )
        return redirect

    @app.get("/auth/discord/callback")
    def auth_discord_callback(request: Request, code: str = "", state: str = ""):
        if oauth_service is None:
            raise _oauth_not_configured_error()
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
        set_session_cookies(redirect, session, secure=secure_cookies, same_site=cookie_samesite)
        redirect.delete_cookie(STATE_COOKIE, path="/")
        return redirect

    @app.post("/auth/logout")
    def auth_logout(request: Request):
        if oauth_service is None:
            raise _oauth_not_configured_error()
        session = check_csrf(request, oauth_service)
        if session.refresh_token:
            oauth_service.revoke_token(session.refresh_token)
        oauth_service.sessions.delete(session.session_id)
        response = Response(status_code=204)
        clear_session_cookies(response)
        return response

    @app.get("/me", response_model=MeDTO)
    def me(request: Request):
        if oauth_service is None:
            raise _oauth_not_configured_error()
        session = require_session(request, oauth_service)
        bot_guild_map = service.get_bot_guild_map()
        shared_guilds = []
        for guild in session.guilds:
            guild_id = int(guild.get("id", 0))
            if guild_id not in bot_guild_map:
                continue
            shared_guilds.append(
                DiscordGuildDTO(
                    id=str(guild_id),
                    name=bot_guild_map[guild_id].name,
                    icon=guild.get("icon"),
                    owner=bool(guild.get("owner", False)),
                    permissions=str(guild.get("permissions", "0")),
                )
            )

        selected = session.selected_guild_id
        if selected is None and shared_guilds:
            selected = int(shared_guilds[0].id)
            session.selected_guild_id = selected

        return MeDTO(
            user=DiscordUserDTO(
                id=str(session.user.get("id", "")),
                username=session.user.get("username", "unknown"),
                global_name=session.user.get("global_name"),
                avatar=session.user.get("avatar"),
            ),
            csrf_token=session.csrf_token,
            selected_guild_id=str(selected) if selected is not None else None,
            guilds=shared_guilds,
        )

    @app.post("/me/select-guild/{guild_id}")
    def select_guild(guild_id: str, request: Request):
        if oauth_service is None:
            raise _oauth_not_configured_error()
        session = check_csrf(request, oauth_service)
        resolved_guild_id = int(guild_id)
        user_guild_ids = {int(g.get("id", 0)) for g in session.guilds}
        bot_guild_ids = set(service.get_bot_guild_map().keys())
        if resolved_guild_id not in user_guild_ids or resolved_guild_id not in bot_guild_ids:
            raise HTTPException(status_code=403, detail="Guild non autorisée")
        session.selected_guild_id = resolved_guild_id
        return {"ok": True, "selected_guild_id": str(resolved_guild_id)}

    @app.get("/api/guilds")
    def list_guilds():
        return service.list_guilds()

    @app.get("/api/guilds/{guild_id}/tickets")
    def list_ticket_transcripts(guild_id: int, request: Request):
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="tickets_list", guild_id=guild_id)
        return service.list_ticket_transcripts(guild_id)

    @app.get("/api/guilds/{guild_id}/tickets/{ticket_id}")
    def get_ticket_transcript(guild_id: int, ticket_id: str, request: Request):
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="tickets_read", guild_id=guild_id)
        row = service.get_ticket_transcript(guild_id, ticket_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Ticket introuvable")
        return row


    @app.get("/api/public/overview")
    def public_overview():
        guilds = service.list_guilds()
        return {
            "ok": True,
            "guild_count": len(guilds),
            "ticket_count": len(service.store.ticket_records),
            "raid_count": len(service.store.raids),
            "template_count": len(service.store.templates),
        }

    @app.get("/api/raids")
    def list_raids(request: Request):
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="raid_list")
        return service.list_raids()

    @app.get("/api/raid-templates")
    def list_templates(request: Request):
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="raid_templates_list")
        return service.list_raid_templates()

    @app.post("/api/actions/raids/open")
    def open_raid(payload: RaidOpenRequestDTO, request: Request):
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = int(payload.guild_id)
        auth_ctx = authorizer.ensure_action_allowed(request, action="raid_open", guild_id=guild_id)
        command = OpenRaidFromTemplate(
            context=CommandContext(guild_id=auth_ctx.guild_id, user_id=auth_ctx.user_id, request_id=payload.request_id),
            template_id=payload.template_name,
            title=payload.title,
            description=payload.description,
            extra_message=payload.extra_message,
            start_at=payload.start_at,
            prep_minutes=payload.prep_minutes,
            cleanup_minutes=payload.cleanup_minutes,
        )
        try:
            return command_bus.dispatch(command, OpenRaidFromTemplateHandler(service), action="open_raid_from_template")
        except DomainError as exc:
            status_code = 429 if exc.code == "rate_limited" else 400
            raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.post("/api/actions/comp-wizard")
    def run_comp_wizard(payload: CompTemplateCreateRequestDTO, request: Request):
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = int(payload.guild_id)
        auth_ctx = authorizer.ensure_action_allowed(request, action="comp_wizard", guild_id=guild_id)
        command = StartCompWizardFlow(
            context=CommandContext(guild_id=auth_ctx.guild_id, user_id=auth_ctx.user_id, request_id=payload.request_id),
            template_id=payload.name,
            description=payload.description,
            content_type=payload.content_type,
            raid_required_role_ids=payload.raid_required_role_ids,
            spec=payload.spec,
        )
        try:
            return command_bus.dispatch(command, StartCompWizardFlowHandler(service), action="start_comp_wizard_flow")
        except DomainError as exc:
            status_code = 429 if exc.code == "rate_limited" else 400
            raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    return app


app = create_app()
