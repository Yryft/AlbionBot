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

from web.backend.auth import SessionData
import web.backend.app as backend_app


class FakeOAuthService:
    def __init__(self, session: SessionData, role_ids: list[int], member_permissions: str = "0"):
        self._session = session
        self._role_ids = role_ids
        self._member_permissions = member_permissions
        self.sessions = SimpleNamespace(get=lambda session_id: self._session if session_id == session.session_id else None)

    def ensure_valid_session(self, session: SessionData) -> SessionData:
        return session

    def fetch_guild_member(self, access_token: str, guild_id: int) -> dict:
        return {"roles": [str(role_id) for role_id in self._role_ids], "permissions": self._member_permissions}


RAID_OPEN_PAYLOAD = {
    "request_id": "req-1",
    "guild_id": "123",
    "channel_id": "456",
    "template_name": "zvz",
    "title": "Prime time",
    "description": "desc",
    "extra_message": "",
    "start_at": int(time.time()) + 3600,
    "prep_minutes": 10,
    "cleanup_minutes": 30,
}

BANK_APPLY_PAYLOAD = {
    "request_id": "bank-req-1",
    "guild_id": "123",
    "action_type": "add",
    "amount": 100,
    "target_user_ids": ["77"],
    "note": "test",
}


def _write_state(path) -> None:
    path.write_text(
        json.dumps(
            {
                "templates": {
                    "zvz": {
                        "name": "zvz",
                        "description": "template",
                        "created_by": 1,
                        "created_at": int(time.time()),
                        "content_type": "pvp",
                        "raid_required_role_ids": [],
                        "roles": [
                            {
                                "key": "dps",
                                "label": "DPS",
                                "slots": 5,
                                "ip_required": False,
                                "required_role_ids": [],
                            }
                        ],
                    }
                },
                "raids": {},
                "guild_permissions": {
                    "123": {
                        "raid_manager": [111],
                        "bank_manager": [222],
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _build_client(tmp_path, monkeypatch, *, role_ids: list[int], guild_permissions: str = "0", member_permissions: str = "0") -> TestClient:
    data_path = tmp_path / "state.json"
    _write_state(data_path)
    monkeypatch.setenv("DATA_PATH", str(data_path))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setenv("DISCORD_TOKEN", "bot-token")

    session = SessionData(
        session_id="sid",
        csrf_token="csrf",
        created_at=0,
        expires_at=9999999999,
        access_token="user-token",
        refresh_token="refresh",
        token_expires_at=9999999999,
        user={"id": "42"},
        guilds=[{"id": "123", "owner": False, "permissions": guild_permissions}],
        selected_guild_id=123,
    )
    monkeypatch.setattr(backend_app, "_build_oauth_service", lambda: FakeOAuthService(session, role_ids, member_permissions=member_permissions))

    app = backend_app.create_app()
    client = TestClient(app)
    client.cookies.set("albion_dash_session", "sid")
    return client


def test_raid_manager_without_bank_permission_can_open_raid(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[111])

    response = client.post("/api/actions/raids/open", json=RAID_OPEN_PAYLOAD, headers={"X-CSRF-Token": "csrf"})

    assert response.status_code == 200


def test_bank_manager_without_raid_permission_cannot_open_raid(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[222])

    response = client.post("/api/actions/raids/open", json=RAID_OPEN_PAYLOAD, headers={"X-CSRF-Token": "csrf"})

    assert response.status_code == 403


def test_bank_apply_requires_csrf_header(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[111])

    response = client.post("/api/actions/bank/apply", json=BANK_APPLY_PAYLOAD)

    assert response.status_code == 403


def test_bank_apply_with_valid_csrf_header_behaves_normally(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[222])

    response = client.post("/api/actions/bank/apply", json=BANK_APPLY_PAYLOAD, headers={"X-CSRF-Token": "csrf"})

    assert response.status_code == 200


def test_raid_open_requires_csrf_header(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[111])

    response = client.post("/api/actions/raids/open", json=RAID_OPEN_PAYLOAD)

    assert response.status_code == 403


def test_raid_open_with_valid_csrf_header_behaves_normally(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[111])

    response = client.post("/api/actions/raids/open", json=RAID_OPEN_PAYLOAD, headers={"X-CSRF-Token": "csrf"})

    assert response.status_code == 200


def test_admin_can_list_and_update_permission_bindings(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[], guild_permissions=str(1 << 3), member_permissions=str(1 << 3))

    list_response = client.get('/api/guilds/123/permissions')
    assert list_response.status_code == 200
    payload = list_response.json()
    assert any(item['permission_key'] == 'raid_manager' for item in payload)

    update_response = client.put(
        '/api/guilds/123/permissions/raid_manager',
        json={'role_ids': ['333'], 'user_ids': ['42']},
        headers={'X-CSRF-Token': 'csrf'},
    )
    assert update_response.status_code == 200
    assert update_response.json()['user_ids'] == ['42']


def test_non_admin_cannot_update_permission_bindings(tmp_path, monkeypatch):
    client = _build_client(tmp_path, monkeypatch, role_ids=[111], guild_permissions='0', member_permissions='0')

    response = client.put(
        '/api/guilds/123/permissions/raid_manager',
        json={'role_ids': ['333'], 'user_ids': ['42']},
        headers={'X-CSRF-Token': 'csrf'},
    )

    assert response.status_code == 403
