from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
from starlette.requests import Request

from albionbot.config import Config
from albionbot.storage.store import Store
from web.backend.auth import SessionData
from web.backend.authorization import DashboardAuthorizationService


class FakeOAuthService:
    def __init__(self, session: SessionData):
        self._session = session
        self.fetch_count = 0
        self.sessions = SimpleNamespace(get=lambda session_id: self._session if session_id == session.session_id else None)

    def ensure_valid_session(self, session: SessionData) -> SessionData:
        return session

    def fetch_guild_member(self, access_token: str, guild_id: int) -> dict:
        raise HTTPException(status_code=403, detail="cannot read via user token")

    def fetch_guild_member_by_user_id(self, bot_token: str, guild_id: int, user_id: int) -> dict:
        self.fetch_count += 1
        return {"roles": ["987"], "permissions": "32"}


def _build_request(session_id: str) -> Request:
    return Request({"type": "http", "headers": [(b"cookie", f"albion_dash_session={session_id}".encode())]})


def _build_cfg(tmp_path) -> Config:
    return Config(
        discord_token="bot-token",
        guild_ids=[],
        data_path=str(tmp_path / "state.json"),
        bank_database_url="",
        bank_sqlite_path=str(tmp_path / "bank.sqlite3"),
        raid_require_manage_guild=True,
        raid_manager_role_id=None,
        bank_require_manage_guild=True,
        bank_manager_role_id=None,
        support_role_id=None,
        ticket_admin_role_id=None,
        bank_allow_negative=True,
        sched_tick_seconds=15,
        default_prep_minutes=10,
        default_cleanup_minutes=30,
        voice_check_after_minutes=5,
    )


def test_ensure_guild_member_falls_back_to_bot_member_lookup(tmp_path):
    store = Store(path=str(tmp_path / "state.json"), bank_database_url="", bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    guild_id = 123
    store.set_permission_role_ids(guild_id, "raid_manager", [987])
    session = SessionData(
        session_id="sid",
        csrf_token="csrf",
        created_at=0,
        expires_at=9999999999,
        access_token="user-token",
        refresh_token="refresh",
        token_expires_at=9999999999,
        user={"id": "42"},
        guilds=[{"id": str(guild_id), "owner": False, "permissions": "0"}],
        selected_guild_id=guild_id,
    )
    oauth = FakeOAuthService(session)
    authorizer = DashboardAuthorizationService(store, oauth, cfg=_build_cfg(tmp_path))

    member_ctx = authorizer.ensure_guild_member(_build_request(session.session_id))

    assert member_ctx.member_role_ids == [987]


def test_ensure_action_allowed_uses_bot_lookup_when_user_scope_missing(tmp_path):
    store = Store(path=str(tmp_path / "state.json"), bank_database_url="", bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    guild_id = 123
    store.set_permission_role_ids(guild_id, "raid_manager", [987])
    session = SessionData(
        session_id="sid",
        csrf_token="csrf",
        created_at=0,
        expires_at=9999999999,
        access_token="user-token",
        refresh_token="refresh",
        token_expires_at=9999999999,
        user={"id": "42"},
        guilds=[{"id": str(guild_id), "owner": False, "permissions": "0"}],
        selected_guild_id=guild_id,
    )
    oauth = FakeOAuthService(session)
    authorizer = DashboardAuthorizationService(store, oauth, cfg=_build_cfg(tmp_path))

    allowed_ctx = authorizer.ensure_action_allowed(_build_request(session.session_id), action="raid_open")

    assert allowed_ctx.guild_id == guild_id
    assert allowed_ctx.user_id == 42


def test_ensure_action_allowed_reuses_member_cache_between_calls(tmp_path):
    store = Store(path=str(tmp_path / "state.json"), bank_database_url="", bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    guild_id = 123
    store.set_permission_role_ids(guild_id, "raid_manager", [987])
    session = SessionData(
        session_id="sid",
        csrf_token="csrf",
        created_at=0,
        expires_at=9999999999,
        access_token="user-token",
        refresh_token="refresh",
        token_expires_at=9999999999,
        user={"id": "42"},
        guilds=[{"id": str(guild_id), "owner": False, "permissions": "0"}],
        selected_guild_id=guild_id,
    )
    oauth = FakeOAuthService(session)
    authorizer = DashboardAuthorizationService(store, oauth, cfg=_build_cfg(tmp_path))

    authorizer.ensure_action_allowed(_build_request(session.session_id), action="raid_open")
    authorizer.ensure_action_allowed(_build_request(session.session_id), action="raid_open")

    assert oauth.fetch_count == 1
