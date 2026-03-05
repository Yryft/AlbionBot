from __future__ import annotations

import os
import secrets
import asyncio
import contextlib
import logging
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
from .albion_provider import AlbionProviderError, AlbionProviderService
from .domain.crafting import CraftSimulationError, CraftSimulationInput, FocusYieldConfig, simulate_crafting
from .schemas import (
    BalanceEntryDTO,
    BankActionHistoryEntryDTO,
    BankActionRequestDTO,
    BankBalanceDTO,
    BankTransferRequestDTO,
    BankUndoRequestDTO,
    CompTemplateCreateRequestDTO,
    DiscordDirectoryDTO,
    GuildPermissionBindingDTO,
    GuildPermissionUpdateRequestDTO,
    DiscordGuildDTO,
    DiscordUserDTO,
    MeDTO,
    RaidOpenPreviewDTO,
    RaidOpenPreviewRequestDTO,
    RaidOpenRequestDTO,
    RaidTemplateUpdateRequestDTO,
    TemplateMutationResultDTO,
    RaidUpdateRequestDTO,
    RaidRosterDTO,
    RaidSignupRequestDTO,
    RaidStateUpdateRequestDTO,
    CraftItemDTO,
    CraftItemDetailDTO,
    CraftSimulationRequestDTO,
    CraftSimulationResultDTO,
    CraftProfitabilityRequestDTO,
    CraftProfitabilityResultDTO,
    CraftFocusCostBulkUpsertRequestDTO,
    CraftFocusCostEntryDTO,
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


DISCORD_PERM_ADMINISTRATOR = 1 << 3
logger = logging.getLogger(__name__)

OAUTH_REQUIRED_ENV_VARS = (
    "DISCORD_OAUTH_CLIENT_ID",
    "DISCORD_OAUTH_CLIENT_SECRET",
    "DISCORD_OAUTH_REDIRECT_URI",
)


CRAFT_LOCATION_BONUSES = {
    "none": {"location_return_rate_bonus": 0.0, "hideout_return_rate_bonus": 0.0, "focus_return_rate_bonus": 0.0, "additional_return_rate_bonus": 0.0},
    "city": {"location_return_rate_bonus": 0.15, "hideout_return_rate_bonus": 0.0, "focus_return_rate_bonus": 0.25, "additional_return_rate_bonus": 0.0},
    "hideout": {"location_return_rate_bonus": 0.0, "hideout_return_rate_bonus": 0.28, "focus_return_rate_bonus": 0.25, "additional_return_rate_bonus": 0.0},
    "hideout_quality": {"location_return_rate_bonus": 0.0, "hideout_return_rate_bonus": 0.28, "focus_return_rate_bonus": 0.25, "additional_return_rate_bonus": 0.03},
}


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
    albion_provider = AlbionProviderService(store=store)
    command_bus = CommandBus(rate_limiter=RateLimiter(), audit_logger=AuditLogger())
    oauth_service = _build_oauth_service()
    authorizer = DashboardAuthorizationService(store, oauth_service) if oauth_service is not None else None

    app = FastAPI(title="AlbionBot Dashboard API", version="0.1.0")
    app.state.albion_sync_task = None

    async def _run_albion_sync_loop() -> None:
        while True:
            try:
                if albion_provider.provider_url or albion_provider.items_list_url:
                    await albion_provider.refresh(force=True)
            except AlbionProviderError as exc:
                logger.exception("Albion periodic sync failed (%s): %s", exc.code, exc.message)
            await asyncio.sleep(max(60, albion_provider.sync_interval_s))

    @app.on_event("startup")
    async def start_albion_sync_job() -> None:
        app.state.albion_sync_task = asyncio.create_task(_run_albion_sync_loop())

    @app.on_event("shutdown")
    async def stop_albion_sync_job() -> None:
        task = app.state.albion_sync_task
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

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


    def ensure_guild_admin(request: Request, guild_id: int) -> None:
        if authorizer is None:
            raise _oauth_not_configured_error()
        member_ctx = authorizer.ensure_guild_member(request, guild_id=guild_id)
        if member_ctx.is_owner:
            return
        user_guild = next((g for g in member_ctx.session.guilds if int(g.get("id", 0)) == guild_id), None)
        permission_bits = int((user_guild or {}).get("permissions", "0") or "0")
        if not bool(permission_bits & DISCORD_PERM_ADMINISTRATOR):
            raise HTTPException(status_code=403, detail="Action réservée aux administrateurs du serveur")

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

    @app.get("/api/craft/items", response_model=list[CraftItemDTO])
    async def search_craft_items(q: str = "", limit: int = 20):
        try:
            return await albion_provider.search_items(query=q, limit=limit)
        except AlbionProviderError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": exc.message, "details": {"last_sync_error": albion_provider.last_sync_error}},
            ) from exc

    @app.get("/api/craft/items/{item_id}", response_model=CraftItemDetailDTO)
    async def craft_item_detail(item_id: str):
        try:
            return await albion_provider.get_item_detail(item_id)
        except AlbionProviderError as exc:
            status = 404 if exc.code == "item_not_found" else 503
            raise HTTPException(
                status_code=status,
                detail={"code": exc.code, "message": exc.message, "details": {"last_sync_error": albion_provider.last_sync_error}},
            ) from exc


    @app.get("/api/admin/craft/focus-costs", response_model=list[CraftFocusCostEntryDTO])
    async def list_craft_focus_costs(guild_id: str, request: Request, limit: int = 500):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        ensure_guild_admin(request, resolved_guild_id)
        rows = store.craft_list_focus_costs(limit=limit)
        return [
            {
                "item_id": str(row.get("item_id", "")),
                "base_focus_cost": int(row.get("base_focus_cost", 0) or 0),
                "tier": (int(row["tier"]) if row.get("tier") is not None else None),
                "enchant": (int(row["enchant"]) if row.get("enchant") is not None else None),
                "source": str(row.get("source", "manual")),
                "updated_at": int(row.get("updated_at", 0) or 0),
            }
            for row in rows
        ]

    @app.post("/api/admin/craft/focus-costs")
    async def upsert_craft_focus_costs(payload: CraftFocusCostBulkUpsertRequestDTO, guild_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        ensure_csrf_for_mutation(request)
        ensure_guild_admin(request, resolved_guild_id)
        for entry in payload.entries:
            store.craft_upsert_focus_cost(
                item_id=entry.item_id,
                base_focus_cost=entry.base_focus_cost,
                tier=entry.tier,
                enchant=entry.enchant,
                source=entry.source,
            )
        return {"ok": True, "updated": len(payload.entries)}

    @app.get("/api/craft/metadata")
    async def craft_metadata():
        return {
            "sync": albion_provider.get_sync_status(),
            "last_sync_error": albion_provider.last_sync_error,
        }

    @app.get("/api/admin/craft/sync-status")
    async def admin_craft_sync_status(guild_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        ensure_guild_admin(request, resolved_guild_id)
        return {
            "sync": albion_provider.get_sync_status(),
            "last_sync_error": albion_provider.last_sync_error,
        }

    @app.post("/api/craft/simulate", response_model=CraftSimulationResultDTO)
    async def simulate_craft(payload: CraftSimulationRequestDTO):
        try:
            item_detail = await albion_provider.get_item_detail(payload.item_id)
            item = item_detail["item"]
            if not item.get("craftable", False):
                raise CraftSimulationError("item_not_craftable", "L'item cible n'est pas craftable")

            location = CRAFT_LOCATION_BONUSES.get(payload.location_key)
            if location is None:
                raise CraftSimulationError("invalid_location", "location_key inconnu", details={"location_key": payload.location_key})

            items, recipes = await albion_provider.get_catalog_snapshot()
            names_by_item_id = {row["id"]: row.get("name", row["id"]) for row in items}
            craftable_by_item_id = {row["id"]: bool(row.get("craftable", False)) for row in items}

            raw_focus_cost = item_detail.get("metadata", {}).get("base_focus_cost")
            if raw_focus_cost is None:
                raise CraftSimulationError(
                    "missing_focus_cost",
                    "Coût focus introuvable pour cet item.",
                    details={"item_id": payload.item_id},
                )
            try:
                base_focus_cost = int(raw_focus_cost)
            except (TypeError, ValueError) as exc:
                raise CraftSimulationError(
                    "invalid_focus_cost",
                    "Coût focus invalide pour cet item.",
                    details={"item_id": payload.item_id, "raw_value": raw_focus_cost},
                ) from exc
            if base_focus_cost <= 0:
                raise CraftSimulationError(
                    "invalid_focus_cost",
                    "Coût focus invalide pour cet item.",
                    details={"item_id": payload.item_id, "raw_value": raw_focus_cost},
                )

            simulation = simulate_crafting(
                simulation_input=CraftSimulationInput(
                    quantity=payload.quantity,
                    mastery_level=payload.mastery_level,
                    specialization_level=payload.specialization_level,
                    available_focus=payload.available_focus,
                    base_focus_cost=base_focus_cost,
                    use_focus=payload.use_focus,
                    yields=FocusYieldConfig(
                        base_return_rate=0.152,
                        location_return_rate_bonus=location["location_return_rate_bonus"],
                        hideout_return_rate_bonus=location["hideout_return_rate_bonus"],
                        focus_return_rate_bonus=location["focus_return_rate_bonus"],
                        additional_return_rate_bonus=location["additional_return_rate_bonus"],
                    ),
                ),
                recipe=item_detail.get("recipe", []),
                recipes_by_item_id=recipes,
                craftable_by_item_id=craftable_by_item_id,
                names_by_item_id=names_by_item_id,
            )

            return {
                "item_id": payload.item_id,
                "focus_efficiency": simulation.focus_efficiency,
                "focus_per_item": simulation.focus_per_item,
                "total_focus": simulation.total_focus,
                "items_craftable_with_available_focus": simulation.items_craftable_with_available_focus,
                "base_materials": [row.__dict__ for row in simulation.base_materials],
                "intermediate_materials": [row.__dict__ for row in simulation.intermediate_materials],
                "applied_yields": simulation.applied_yields,
            }
        except CraftSimulationError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc
        except AlbionProviderError as exc:
            status = 404 if exc.code == "item_not_found" else 503
            raise HTTPException(
                status_code=status,
                detail={"code": exc.code, "message": exc.message, "details": {"last_sync_error": albion_provider.last_sync_error}},
            ) from exc


    @app.post("/api/craft/profitability", response_model=CraftProfitabilityResultDTO)
    async def simulate_craft_profitability(payload: CraftProfitabilityRequestDTO):
        try:
            simulation = payload.simulation
            if simulation.item_id.strip() == "":
                raise CraftSimulationError("invalid_item_id", "simulation.item_id requis")

            material_lines = []
            total_material_cost = 0.0
            for row in simulation.base_materials:
                unit_price = float(payload.material_unit_prices.get(row.item_id, 0.0))
                quantity = int(row.net_quantity)
                line_total = unit_price * quantity
                total_material_cost += line_total
                source = "prefilled" if payload.pricing_mode.value == "prefilled" and row.item_id in payload.material_unit_prices else "manual"
                material_lines.append(
                    {
                        "item_id": row.item_id,
                        "item_name": row.item_name,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "total_cost": line_total,
                        "source": source,
                    }
                )

            focus_cost = 0.0
            if payload.include_focus_cost:
                focus_cost = float(simulation.total_focus) * float(payload.focus_unit_price)

            crafted_quantity = int(payload.crafted_quantity)
            imbuer_journal_cost = float(payload.imbuer_journal_unit_price) * crafted_quantity
            gross_revenue = float(payload.item_sale_unit_price) * crafted_quantity
            market_tax_amount = gross_revenue * (float(payload.market_tax_rate) / 100.0)
            net_revenue = gross_revenue - market_tax_amount

            total_cost = total_material_cost + focus_cost + imbuer_journal_cost
            profit = net_revenue - total_cost
            margin_pct = (profit / net_revenue * 100.0) if net_revenue > 0 else 0.0

            return {
                "simulation": simulation.model_dump() if hasattr(simulation, "model_dump") else simulation.dict(),
                "pricing_mode": payload.pricing_mode,
                "material_lines": material_lines,
                "total_material_cost": total_material_cost,
                "focus_cost": focus_cost,
                "imbuer_journal_cost": imbuer_journal_cost,
                "total_cost": total_cost,
                "gross_revenue": gross_revenue,
                "market_tax_amount": market_tax_amount,
                "net_revenue": net_revenue,
                "profit": profit,
                "margin_pct": margin_pct,
            }
        except CraftSimulationError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc


    @app.post("/api/admin/craft/cache/invalidate")
    async def invalidate_craft_cache(guild_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        ensure_csrf_for_mutation(request)
        ensure_guild_admin(request, resolved_guild_id)
        await albion_provider.invalidate()
        await albion_provider.refresh(force=True)
        return {"ok": True}


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


    @app.get("/api/guilds/{guild_id}/permissions", response_model=list[GuildPermissionBindingDTO])
    def list_guild_permissions(guild_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        ensure_guild_admin(request, resolved_guild_id)
        return service.list_permission_bindings(resolved_guild_id)

    @app.put("/api/guilds/{guild_id}/permissions/{permission_key}", response_model=GuildPermissionBindingDTO)
    def update_guild_permission(guild_id: str, permission_key: str, payload: GuildPermissionUpdateRequestDTO, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        ensure_csrf_for_mutation(request)
        ensure_guild_admin(request, resolved_guild_id)
        role_ids = [parse_discord_id(role_id, "role_ids") for role_id in payload.role_ids]
        user_ids = [parse_discord_id(user_id, "user_ids") for user_id in payload.user_ids]
        try:
            return service.set_permission_binding(resolved_guild_id, permission_key, role_ids, user_ids)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc

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

    @app.delete("/api/guilds/{guild_id}/balances/{user_id}")
    def delete_user_balance(guild_id: str, user_id: str, request: Request):
        resolved_guild_id = parse_discord_id(guild_id, "guild_id")
        resolved_user_id = parse_discord_id(user_id, "user_id")
        ensure_csrf_for_mutation(request)
        if authorizer is None:
            raise _oauth_not_configured_error()
        authorizer.ensure_action_allowed(request, action="bank_manage", guild_id=resolved_guild_id)
        try:
            service.delete_bank_balance(resolved_guild_id, resolved_user_id)
        except DomainError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "details": exc.details}) from exc
        return {"ok": True}

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

    @app.post("/api/actions/raids/preview", response_model=RaidOpenPreviewDTO)
    def preview_open_raid(payload: RaidOpenPreviewRequestDTO, request: Request):
        if authorizer is None:
            raise _oauth_not_configured_error()
        guild_id = parse_discord_id(payload.guild_id, "guild_id")
        authorizer.ensure_action_allowed(request, action="raid_open", guild_id=guild_id)
        try:
            return service.build_raid_open_preview(
                template_name=payload.template_name,
                title=payload.title,
                description=payload.description,
                extra_message=payload.extra_message,
                start_at=payload.start_at,
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
