from __future__ import annotations

import json
import pathlib
import sys
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

repo_root = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))
sys.path.append(str(repo_root / "src"))

import web.backend.app as backend_app
from web.backend.auth import SessionData


class FakeOAuthService:
    def __init__(self, session: SessionData):
        self._session = session
        self.ensure_count = 0
        self.sessions = SimpleNamespace(get=lambda session_id: self._session if session_id == session.session_id else None)

    def ensure_valid_session(self, session: SessionData) -> SessionData:
        self.ensure_count += 1
        return session

    def create_login_url(self, state: str) -> str:
        return f"https://discord.test/login?state={state}"


def _write_state(path) -> None:
    path.write_text(json.dumps({"templates": {}, "raids": {}}), encoding="utf-8")


def _build_client(tmp_path, monkeypatch) -> tuple[TestClient, FakeOAuthService]:
    data_path = tmp_path / "state.json"
    _write_state(data_path)
    monkeypatch.setenv("DATA_PATH", str(data_path))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setenv("DISCORD_TOKEN", "bot-token")

    session = SessionData(
        session_id="sid",
        csrf_token="csrf",
        created_at=int(time.time()),
        expires_at=9999999999,
        access_token="user-token",
        refresh_token="refresh",
        token_expires_at=9999999999,
        user={"id": "42", "username": "Tester"},
        guilds=[],
        selected_guild_id=None,
        last_ip="testclient",
        last_user_agent="testclient",
    )
    oauth = FakeOAuthService(session)
    monkeypatch.setattr(backend_app, "_build_oauth_service", lambda: oauth)
    app = backend_app.create_app()
    client = TestClient(app)
    client.cookies.set("albion_dash_session", "sid")
    return client, oauth


def test_login_resumes_existing_session_by_default(tmp_path, monkeypatch):
    client, oauth = _build_client(tmp_path, monkeypatch)

    response = client.get("/auth/discord/login", headers={"user-agent": "testclient"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/?resumed=1"
    assert oauth.ensure_count == 1


def test_login_force_bypasses_resume_and_starts_oauth(tmp_path, monkeypatch):
    client, oauth = _build_client(tmp_path, monkeypatch)

    response = client.get("/auth/discord/login?force=1", headers={"user-agent": "testclient"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://discord.test/login?state=")
    assert "albion_dash_state" in response.headers.get("set-cookie", "")
    assert oauth.ensure_count == 0
