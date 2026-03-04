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
from .schemas import (
    BalanceEntryDTO,
    BankActionHistoryEntryDTO,
    BankActionRequestDTO,
    BankBalanceDTO,
    BankTransferRequestDTO,
    BankUndoRequestDTO,
    CompTemplateCreateRequestDTO,
    DiscordDirectoryDTO,
    DiscordGuildDTO,
    DiscordUserDTO,
    MeDTO,
    RaidOpenRequestDTO,
    RaidTemplateUpdateRequestDTO,
    TemplateMutationResultDTO,
    RaidUpdateRequestDTO,
    RaidRosterDTO,
    RaidSignupRequestDTO,
    RaidStateUpdateRequestDTO,
)
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


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def create_app() -> FastAPI:
    data_path = os.getenv("DATA_PATH", "data/state.json").strip()
    bank_database_url = os.getenv("BANK_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    bank_sqlite_path = os.getenv("BANK_SQLITE_PATH", "data/bank.sqlite3").strip()

    store = Store(
        path=data_path,
        bank_database_url=bank_database_url,
        bank_sqlite_path=bank_sqlite_path,
    )
    service = DashboardService(store, bank_allow_negative=_env_bool("BANK_ALLOW_NEGATIVE", True))
    command_bus = CommandBus(rate_limiter=RateLimiter(), audit_logger=AuditLogger())
    oauth_service = _build_oauth_service()
    authorizer = DashboardAuthorizationService(store, oauth_service) if oauth_service is not None else None

    app = FastAPI(title="AlbionBot Dashboard API", version="0.1.0")

    @app.middleware("http")
    async def refresh_store_state(request: Request, call_next):
        """Always serve requests from the latest shared state snapshot.

        The Discord bot process and the dashboard API can run as distinct
        processes that both read/write the same state file. Without an
        opportunistic reload, the API may keep stale in-memory data and return
        outdated publish statuses (e.g. `pending` while the raid is already
        sent on Discord), or overwrite fresh bot updates on the next save.
        """

        store.reload_if_changed()
        return await call_next(request)

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

    def parse_discord_id(raw_id: str, field_name: str) -> int:
        value = (raw_id or "").strip()
        if not value.isdigit() or int(value) <= 0:
            raise HTTPException(status_code=422, detail=f"{field_name} invalide")
        return int(value)

    def ensure_csrf_for_mutation(request: Request):
        if oauth_service is None:
            raise _oauth_not_configured_error()
        return check_csrf(request, oauth_service)

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
        session = ensure_csrf_for_mutation(request)
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
                    name=str(guild.get("name") or bot_guild_map[guild_id].name),
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
        session = ensure_csrf_for_mutation(request)
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
    def list_ticket_transcripts(guild_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="tickets_list", guild_id=resolved_guild_id)
        return service.list_ticket_transcripts(resolved_guild_id)

    @app.get("/api/guilds/{guild_id}/tickets/{ticket_id}")
    def get_ticket_transcript(guild_id: str, ticket_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="tickets_read", guild_id=resolved_guild_id)
        row = service.get_ticket_transcript(resolved_guild_id, ticket_id)
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


    @app.get("/api/my/raids")
    def list_my_raids(request: Request):
        if authorizer is None:
            raise _oauth_not_configured_error()
        member_ctx = authorizer.ensure_guild_member(request)
        return service.list_user_raids(member_ctx.member_role_ids, include_all=member_ctx.is_owner)

    @app.get("/api/raids/{raid_id}/roster", response_model=RaidRosterDTO)
    def get_raid_roster(raid_id: str, request: Request):
        if authorizer is None:
            raise _oauth_not_configured_error()
        member_ctx = authorizer.ensure_guild_member(request)
        try:
            return service.get_raid_roster(raid_id, member_ctx.member_role_ids)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.post("/api/raids/{raid_id}/signup", response_model=RaidRosterDTO)
    def signup_raid(raid_id: str, payload: RaidSignupRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        member_ctx = authorizer.ensure_guild_member(request)
        try:
            return service.signup_raid(raid_id, member_ctx.user_id, member_ctx.member_role_ids, payload.role_key, payload.ip)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.post("/api/raids/{raid_id}/leave", response_model=RaidRosterDTO)
    def leave_raid(raid_id: str, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        member_ctx = authorizer.ensure_guild_member(request)
        try:
            return service.leave_raid(raid_id, member_ctx.user_id, member_ctx.member_role_ids)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

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

    @app.put("/api/raid-templates/{template_name}", response_model=TemplateMutationResultDTO)
    def update_template(template_name: str, payload: RaidTemplateUpdateRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="comp_wizard")
        role_ids = [parse_discord_id(role_id, "raid_required_role_ids") for role_id in payload.raid_required_role_ids]
        payload = payload.model_copy(update={"raid_required_role_ids": role_ids})
        try:
            return service.update_raid_template(template_name, payload)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc


    @app.delete("/api/raid-templates/{template_name}")
    def delete_template(template_name: str, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="comp_wizard")
        try:
            service.delete_raid_template(template_name)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc
        return {"ok": True}

    @app.put("/api/raids/{raid_id}")
    def update_raid(raid_id: str, payload: RaidUpdateRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="raid_open")
        try:
            return service.update_raid(raid_id, payload)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc


    @app.post("/api/raids/{raid_id}/state")
    def update_raid_state(raid_id: str, payload: RaidStateUpdateRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="raid_open")
        if payload.action != "close":
            raise HTTPException(status_code=422, detail="Action de statut non supportée")
        try:
            return service.close_raid(raid_id)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.get("/api/guilds/{guild_id}/discord-directory", response_model=DiscordDirectoryDTO)
    def get_discord_directory(guild_id: str, request: Request):
        if authorizer is None or oauth_service is None:
            raise _oauth_not_configured_error()
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        authorizer.ensure_guild_member(request, guild_id=resolved_guild_id)
        cfg = authorizer.cfg
        channels = oauth_service.fetch_guild_channels(cfg.discord_token, resolved_guild_id)
        roles = oauth_service.fetch_guild_roles(cfg.discord_token, resolved_guild_id)
        members = oauth_service.fetch_guild_members(cfg.discord_token, resolved_guild_id)
        return {
            "channels": [
                {
                    "id": str(ch.get("id", "")),
                    "name": str(ch.get("name") or f"channel-{ch.get('id', '')}"),
                    "type": int(ch.get("type", 0) or 0),
                }
                for ch in channels
                if ch.get("type") in {0, 2}
            ],
            "roles": [
                {"id": str(role.get("id", "")), "name": str(role.get("name") or "role")}
                for role in roles
                if int(role.get("id", 0)) > 0
            ],
            "members": [
                {
                    "id": str((m.get("user") or {}).get("id", "")),
                    "display_name": str(m.get("nick") or (m.get("user") or {}).get("global_name") or (m.get("user") or {}).get("username") or (m.get("user") or {}).get("id") or ""),
                }
                for m in members
                if (m.get("user") or {}).get("id")
            ],
        }

    @app.get("/api/guilds/{guild_id}/balances", response_model=list[BalanceEntryDTO])
    def list_balances(guild_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="bank_manage", guild_id=resolved_guild_id)
        return service.list_balances(resolved_guild_id)

    @app.get("/api/guilds/{guild_id}/balances/{user_id}", response_model=BankBalanceDTO)
    def get_user_balance(guild_id: str, user_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        resolved_user_id = parse_discord_id(user_id, "user_id")
        if authorizer is None:
            raise _oauth_not_configured_error()
        member_ctx = authorizer.ensure_guild_member(request, guild_id=resolved_guild_id)
        if member_ctx.user_id != resolved_user_id:
            authorizer.ensure_action_allowed(request, action="bank_manage", guild_id=resolved_guild_id)
        return service.get_balance(resolved_guild_id, resolved_user_id)

    @app.get("/api/guilds/{guild_id}/bank/actions", response_model=list[BankActionHistoryEntryDTO])
    def list_bank_actions(guild_id: str, request: Request, limit: int = 25):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        if authorizer is None:
            raise _oauth_not_configured_error()
        authorizer.ensure_action_allowed(request, action="bank_manage", guild_id=resolved_guild_id)
        return service.list_bank_action_history(resolved_guild_id, limit=max(1, min(limit, 100)))


    @app.delete("/api/raids/{raid_id}")
    def delete_raid(raid_id: str, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="raid_open")
        try:
            service.delete_raid(raid_id)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc
        return {"ok": True}

    @app.delete("/api/guilds/{guild_id}/tickets/{ticket_id}")
    def delete_ticket_transcript(guild_id: str, ticket_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        ensure_csrf_for_mutation(request)
        if authorizer is not None:
            authorizer.ensure_action_allowed(request, action="tickets_read", guild_id=resolved_guild_id)
        try:
            service.delete_ticket_transcript(resolved_guild_id, ticket_id)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc
        return {"ok": True}

    @app.post("/api/actions/bank/apply")
    def apply_bank_action(payload: BankActionRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = parse_discord_id(payload.guild_id, "guild_id")
        target_user_ids = [parse_discord_id(user_id, "target_user_ids") for user_id in payload.target_user_ids]
        auth_ctx = authorizer.ensure_action_allowed(request, action="bank_manage", guild_id=guild_id)
        try:
            return service.apply_bank_action(
                guild_id=guild_id,
                actor_id=auth_ctx.user_id,
                action_type=payload.action_type,
                amount=payload.amount,
                target_user_ids=target_user_ids,
                note=payload.note,
            )
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.post("/api/actions/bank/undo")
    def undo_bank_action(payload: BankUndoRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = parse_discord_id(payload.guild_id, "guild_id")
        auth_ctx = authorizer.ensure_action_allowed(request, action="bank_manage", guild_id=guild_id)
        try:
            return service.undo_last_bank_action(guild_id=guild_id, actor_id=auth_ctx.user_id)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.post("/api/actions/bank/pay")
    def pay_bank(payload: BankTransferRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = parse_discord_id(payload.guild_id, "guild_id")
        to_user_id = parse_discord_id(payload.to_user_id, "to_user_id")
        member_ctx = authorizer.ensure_guild_member(request, guild_id=guild_id)
        try:
            return service.transfer_balance(
                guild_id=guild_id,
                from_user_id=member_ctx.user_id,
                to_user_id=to_user_id,
                amount=payload.amount,
                note=payload.note,
            )
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.post("/api/actions/raids/open")
    def open_raid(payload: RaidOpenRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = parse_discord_id(payload.guild_id, "guild_id")
        channel_id = parse_discord_id(payload.channel_id, "channel_id")
        voice_channel_id = parse_discord_id(payload.voice_channel_id, "voice_channel_id") if payload.voice_channel_id else None
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
            channel_id=channel_id,
            voice_channel_id=voice_channel_id,
        )
        try:
            return command_bus.dispatch(command, OpenRaidFromTemplateHandler(service), action="open_raid_from_template")
        except DomainError as exc:
            status_code = 429 if exc.code == "rate_limited" else 400
            raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    @app.post("/api/actions/comp-wizard", response_model=TemplateMutationResultDTO)
    def run_comp_wizard(payload: CompTemplateCreateRequestDTO, request: Request):
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = parse_discord_id(payload.guild_id, "guild_id")
        auth_ctx = authorizer.ensure_action_allowed(request, action="comp_wizard", guild_id=guild_id)
        command = StartCompWizardFlow(
            context=CommandContext(guild_id=auth_ctx.guild_id, user_id=auth_ctx.user_id, request_id=payload.request_id),
            template_id=payload.name,
            description=payload.description,
            content_type=payload.content_type,
            raid_required_role_ids=[parse_discord_id(role_id, "raid_required_role_ids") for role_id in payload.raid_required_role_ids],
            spec=payload.spec,
        )
        try:
            return command_bus.dispatch(command, StartCompWizardFlowHandler(service), action="start_comp_wizard_flow")
        except DomainError as exc:
            status_code = 429 if exc.code == "rate_limited" else 400
            raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

    return app


app = create_app()
