from __future__ import annotations

import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx
from fastapi import HTTPException, Request, Response

DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_REVOKE_URL = "https://discord.com/api/oauth2/token/revoke"
DISCORD_API_ME_URL = "https://discord.com/api/users/@me"
DISCORD_API_GUILDS_URL = "https://discord.com/api/users/@me/guilds"
DISCORD_API_GUILD_MEMBER_URL = "https://discord.com/api/users/@me/guilds/{guild_id}/member"
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


class SessionManager:
    def __init__(self, session_ttl_seconds: int = 60 * 60 * 24 * 7):
        self._sessions: Dict[str, SessionData] = {}
        self._session_ttl_seconds = session_ttl_seconds

    def create(self, access_token: str, refresh_token: str, token_expires_in: int, user: dict, guilds: List[dict]) -> SessionData:
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
        )
        self._sessions[session_id] = data
        self.cleanup()
        return data

    def get(self, session_id: str) -> Optional[SessionData]:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        now = int(time.time())
        if session.expires_at <= now:
            self.delete(session_id)
            return None
        return session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def cleanup(self) -> None:
        now = int(time.time())
        expired = [sid for sid, sess in self._sessions.items() if sess.expires_at <= now]
        for sid in expired:
            self.delete(sid)


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
