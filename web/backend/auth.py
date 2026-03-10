from __future__ import annotations

import os
import json
import secrets
import time
import urllib.parse
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx
from fastapi import HTTPException, Request, Response

DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_REVOKE_URL = "https://discord.com/api/oauth2/token/revoke"
DISCORD_API_ME_URL = "https://discord.com/api/users/@me"
DISCORD_API_GUILDS_URL = "https://discord.com/api/users/@me/guilds"
DISCORD_API_GUILD_MEMBER_URL = "https://discord.com/api/users/@me/guilds/{guild_id}/member"
DISCORD_API_GUILD_MEMBER_BY_ID_URL = "https://discord.com/api/guilds/{guild_id}/members/{user_id}"
DISCORD_API_GUILD_CHANNELS_URL = "https://discord.com/api/guilds/{guild_id}/channels"
DISCORD_API_GUILD_ROLES_URL = "https://discord.com/api/guilds/{guild_id}/roles"
DISCORD_API_GUILD_MEMBERS_URL = "https://discord.com/api/guilds/{guild_id}/members"
SESSION_COOKIE = "albion_dash_session"
CSRF_COOKIE = "albion_dash_csrf"
STATE_COOKIE = "albion_dash_state"


@dataclass
class DiscordOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scope: str = "identify guilds guilds.members.read"


@dataclass
class SessionData:
    session_id: str
    csrf_token: str
    created_at: int
    expires_at: int
    access_token: str
    refresh_token: str
    token_expires_at: int
    user: dict
    guilds: List[dict]
    selected_guild_id: Optional[int] = None
    cached_member_contexts: Dict[int, dict] = field(default_factory=dict)
    last_ip: str = ""
    last_user_agent: str = ""


class SessionManager:
    def __init__(self, session_ttl_seconds: int = 60 * 60 * 24 * 7, persistence_path: str = ""):
        self._sessions: Dict[str, SessionData] = {}
        self._session_ttl_seconds = session_ttl_seconds
        self._persistence_path = (persistence_path or os.getenv("DASHBOARD_SESSIONS_PATH", "data/dashboard_sessions.json")).strip()
        self._lock = threading.RLock()
        self._load()

    def _serialize_session(self, session: SessionData) -> dict:
        return {
            "session_id": session.session_id,
            "csrf_token": session.csrf_token,
            "created_at": int(session.created_at),
            "expires_at": int(session.expires_at),
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "token_expires_at": int(session.token_expires_at),
            "user": dict(session.user),
            "guilds": list(session.guilds),
            "selected_guild_id": (int(session.selected_guild_id) if session.selected_guild_id is not None else None),
            "cached_member_contexts": dict(session.cached_member_contexts),
            "last_ip": str(session.last_ip or ""),
            "last_user_agent": str(session.last_user_agent or ""),
        }

    def _save(self) -> None:
        if not self._persistence_path:
            return
        with self._lock:
            os.makedirs(os.path.dirname(self._persistence_path) or ".", exist_ok=True)
            payload = {
                "sessions": [self._serialize_session(s) for s in self._sessions.values()]
            }
            tmp_file = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=os.path.dirname(self._persistence_path) or ".",
                prefix="dashboard_sessions_",
                suffix=".tmp",
                delete=False,
            )
            tmp_path = tmp_file.name
            try:
                with tmp_file:
                    json.dump(payload, tmp_file, ensure_ascii=False)
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())
                os.replace(tmp_path, self._persistence_path)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    def _load(self) -> None:
        if not self._persistence_path or not os.path.exists(self._persistence_path):
            return
        with self._lock:
            try:
                with open(self._persistence_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                return
            now = int(time.time())
            for row in payload.get("sessions", []):
                try:
                    session = SessionData(
                        session_id=str(row.get("session_id", "")),
                        csrf_token=str(row.get("csrf_token", "")),
                        created_at=int(row.get("created_at", now)),
                        expires_at=int(row.get("expires_at", now)),
                        access_token=str(row.get("access_token", "")),
                        refresh_token=str(row.get("refresh_token", "")),
                        token_expires_at=int(row.get("token_expires_at", now)),
                        user=dict(row.get("user", {}) or {}),
                        guilds=list(row.get("guilds", []) or []),
                        selected_guild_id=(int(row["selected_guild_id"]) if row.get("selected_guild_id") is not None else None),
                        cached_member_contexts=dict(row.get("cached_member_contexts", {}) or {}),
                        last_ip=str(row.get("last_ip", "") or ""),
                        last_user_agent=str(row.get("last_user_agent", "") or ""),
                    )
                except Exception:
                    continue
                if session.session_id and session.expires_at > now:
                    self._sessions[session.session_id] = session

    def create(self, access_token: str, refresh_token: str, token_expires_in: int, user: dict, guilds: List[dict], ip_address: str = "", user_agent: str = "") -> SessionData:
        with self._lock:
            now = int(time.time())
            session_id = secrets.token_urlsafe(32)
            data = SessionData(
                session_id=session_id,
                csrf_token=secrets.token_urlsafe(24),
                created_at=now,
                expires_at=now + self._session_ttl_seconds,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=now + token_expires_in,
                user=user,
                guilds=guilds,
                last_ip=str(ip_address or ""),
                last_user_agent=str(user_agent or ""),
            )
            self._sessions[session_id] = data
            self.cleanup()
            self._save()
            return data

    def get(self, session_id: str) -> Optional[SessionData]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            now = int(time.time())
            if session.expires_at <= now:
                self.delete(session_id)
                return None
            # sliding session timeout
            session.expires_at = now + self._session_ttl_seconds
            self._save()
            return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            self._save()

    def cleanup(self) -> None:
        with self._lock:
            now = int(time.time())
            expired = [sid for sid, sess in self._sessions.items() if sess.expires_at <= now]
            for sid in expired:
                self._sessions.pop(sid, None)
            if expired:
                self._save()


class DiscordOAuthService:
    def __init__(self, config: DiscordOAuthConfig, session_manager: SessionManager):
        self.config = config
        self.sessions = session_manager

    def create_login_url(self, state: str) -> str:
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": self.config.scope,
            "state": state,
            "prompt": "consent",
        }
        return f"{DISCORD_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def _refresh_if_needed(self, session: SessionData) -> SessionData:
        now = int(time.time())
        if session.token_expires_at - 30 > now:
            return session

        refreshed = self.refresh_token(session.refresh_token)
        session.access_token = refreshed["access_token"]
        if refreshed.get("refresh_token"):
            session.refresh_token = refreshed["refresh_token"]
        session.token_expires_at = now + int(refreshed.get("expires_in", 3600))
        session.user = self.fetch_user(session.access_token)
        session.guilds = self.fetch_user_guilds(session.access_token)
        session.cached_member_contexts.clear()
        return session

    def ensure_valid_session(self, session: SessionData) -> SessionData:
        try:
            return self._refresh_if_needed(session)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Session Discord expirée") from exc

    def exchange_code(self, code: str) -> dict:
        data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(DISCORD_TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code >= 400:
            raise HTTPException(status_code=400, detail="Impossible d'échanger le code OAuth")
        return resp.json()

    def refresh_token(self, refresh_token: str) -> dict:
        data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(DISCORD_TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code >= 400:
            raise HTTPException(status_code=401, detail="Refresh token Discord invalide")
        return resp.json()

    def revoke_token(self, token: str) -> None:
        data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "token": token,
            "token_type_hint": "refresh_token",
        }
        with httpx.Client(timeout=15.0) as client:
            client.post(DISCORD_REVOKE_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})

    def fetch_user(self, access_token: str) -> dict:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(DISCORD_API_ME_URL, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code >= 400:
            raise HTTPException(status_code=401, detail="Accès utilisateur Discord refusé")
        return resp.json()

    def fetch_user_guilds(self, access_token: str) -> List[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(DISCORD_API_GUILDS_URL, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code >= 400:
            raise HTTPException(status_code=401, detail="Impossible de lire les guilds Discord")
        return resp.json()

    def fetch_guild_member(self, access_token: str, guild_id: int) -> dict:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                DISCORD_API_GUILD_MEMBER_URL.format(guild_id=int(guild_id)),
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=403, detail="Impossible de lire les rôles Discord de l'utilisateur")
        return resp.json()

    def fetch_guild_member_by_user_id(self, bot_token: str, guild_id: int, user_id: int) -> dict:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                DISCORD_API_GUILD_MEMBER_BY_ID_URL.format(guild_id=int(guild_id), user_id=int(user_id)),
                headers={"Authorization": f"Bot {bot_token}"},
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Impossible de lire les rôles Discord via le bot")
        return resp.json()

    def fetch_guild_channels(self, bot_token: str, guild_id: int) -> List[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                DISCORD_API_GUILD_CHANNELS_URL.format(guild_id=int(guild_id)),
                headers={"Authorization": f"Bot {bot_token}"},
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Impossible de lire les channels Discord")
        return resp.json()

    def fetch_guild_roles(self, bot_token: str, guild_id: int) -> List[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                DISCORD_API_GUILD_ROLES_URL.format(guild_id=int(guild_id)),
                headers={"Authorization": f"Bot {bot_token}"},
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Impossible de lire les rôles Discord")
        return resp.json()

    def fetch_guild_members(self, bot_token: str, guild_id: int, limit: int = 200) -> List[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                DISCORD_API_GUILD_MEMBERS_URL.format(guild_id=int(guild_id)),
                params={"limit": min(max(limit, 1), 1000)},
                headers={"Authorization": f"Bot {bot_token}"},
            )
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Impossible de lire les membres Discord")
        return resp.json()


def require_session(request: Request, oauth_service: DiscordOAuthService) -> SessionData:
    session_id = request.cookies.get(SESSION_COOKIE, "")
    if not session_id:
        raise HTTPException(status_code=401, detail="Non authentifié")
    session = oauth_service.sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="Session invalide")
    return oauth_service.ensure_valid_session(session)


def check_csrf(request: Request, oauth_service: DiscordOAuthService) -> SessionData:
    session = require_session(request, oauth_service)
    header_token = request.headers.get("x-csrf-token", "")
    if not header_token or session.csrf_token != header_token:
        raise HTTPException(status_code=403, detail="CSRF invalide")
    return session


def set_session_cookies(response: Response, session: SessionData, secure: bool, same_site: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session.session_id,
        httponly=True,
        samesite=same_site,
        secure=secure,
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=session.csrf_token,
        httponly=False,
        samesite=same_site,
        secure=secure,
        max_age=7 * 24 * 60 * 60,
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(STATE_COOKIE, path="/")
