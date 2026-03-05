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
from web.backend.auth import SessionData, SessionManager


class FakeOAuthService:
    def __init__(self, session: SessionData):
        self._session = session
        self.sessions = SimpleNamespace(get=lambda session_id: self._session if session_id == session.session_id else None)

    def ensure_valid_session(self, session: SessionData) -> SessionData:
        return session

    def revoke_token(self, token: str) -> None:
        return None



def _write_state(path) -> None:
    path.write_text(json.dumps({"templates": {}, "raids": {}}), encoding="utf-8")



def _build_client(tmp_path, monkeypatch) -> TestClient:
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
        last_user_agent="test-agent",
    )
    monkeypatch.setattr(backend_app, "_build_oauth_service", lambda: FakeOAuthService(session))
    app = backend_app.create_app()
    client = TestClient(app)
    client.cookies.set("albion_dash_session", "sid")
    client.cookies.set("albion_dash_csrf", "csrf")
    return client



def test_session_manager_persists_sessions_to_disk(tmp_path):
    path = tmp_path / "sessions.json"
    mgr = SessionManager(session_ttl_seconds=3600, persistence_path=str(path))
    created = mgr.create(
        access_token="a",
        refresh_token="r",
        token_expires_in=3600,
        user={"id": "42"},
        guilds=[],
        ip_address="1.2.3.4",
        user_agent="UA",
    )

    reloaded = SessionManager(session_ttl_seconds=3600, persistence_path=str(path))
    got = reloaded.get(created.session_id)

    assert got is not None
    assert got.last_ip == "1.2.3.4"
    assert got.last_user_agent == "UA"



def test_craft_preferences_are_persisted_for_user(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch)

    update_response = client.put(
        "/api/user/preferences/craft",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 2,
            "quantity": 5,
            "category_mastery_level": 10,
            "target_specialization_level": 20,
            "location_key": "city",
            "city_key": "lymhurst",
            "hideout_biome_key": "forest",
            "hideout_territory_level": 9,
            "hideout_zone_quality": 6,
            "available_focus": 30000,
            "use_focus": True,
            "tax_rate": 6.5,
            "focus_unit_price": 0,
            "journal_unit_price": 0,
            "sale_unit_price": 0,
            "pricing_mode": "manual",
        },
        headers={"X-CSRF-Token": "csrf"},
    )
    assert update_response.status_code == 200

    get_response = client.get("/api/user/preferences/craft")
    assert get_response.status_code == 200
    data = get_response.json()
    assert data["item_id"] == "ITEM_TEST"
    assert data["enchantment_level"] == 2
    assert data["city_key"] == "lymhurst"
    assert data["hideout_biome_key"] == "forest"
