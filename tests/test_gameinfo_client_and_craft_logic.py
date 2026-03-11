from __future__ import annotations

import asyncio

from web.backend.gameinfo_client import GameInfoClient
from web.backend.albion_provider import AlbionProviderService


def test_gameinfo_client_uses_conditional_cache(monkeypatch):
    calls: list[dict[str, str]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload=None, headers=None):
            self.status_code = status_code
            self._payload = payload
            self.headers = headers or {}
            self.text = ""

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http")

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            calls.append(headers or {})
            if len(calls) == 1:
                return FakeResponse(200, {"ok": 1}, {"ETag": "abc"})
            return FakeResponse(304, None, {})

    monkeypatch.setattr("web.backend.gameinfo_client.httpx.AsyncClient", lambda timeout: FakeClient())
    client = GameInfoClient(base_url="https://example.test")
    first = asyncio.run(client.get_json("/x"))
    second = asyncio.run(client.get_json("/x"))
    assert first == second == {"ok": 1}
    assert calls[1].get("If-None-Match") == "abc"


def test_category_fallback_marker():
    assert AlbionProviderService.item_id_matches_category_marker("T5_MAIN_HOLYSTAFF_AVALON", "holy_staff")


def test_multi_recipe_auto_select_lowest_focus():
    simulations = [(0, {"total_focus": 100}), (1, {"total_focus": 90})]
    best = min(simulations, key=lambda row: row[1]["total_focus"])
    assert best[0] == 1
