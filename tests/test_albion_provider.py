from __future__ import annotations

import asyncio
import json

from web.backend.albion_provider import AlbionProviderError, AlbionProviderService


def _run(coro):
    return asyncio.run(coro)


def test_albion_provider_refresh_and_snapshot(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "https://provider.example/catalog")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()

    async def fake_fetch():
        return (
            [{"id": "T4_BAG", "name": "Adept's Bag", "tier": 4, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "bag", "craftable": True}],
            {"T4_BAG": [{"item_id": "T4_CLOTH", "item_name": "Simple Cloth", "quantity": 8}]},
        )

    monkeypatch.setattr(provider, "_fetch_remote_catalog", fake_fetch)
    _run(provider.refresh(force=True))

    assert snapshot.exists()
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    assert data["items"][0]["id"] == "T4_BAG"

    rows = _run(provider.search_items("bag", 10))
    assert len(rows) == 1
    detail = _run(provider.get_item_detail("T4_BAG"))
    assert detail["recipe"][0]["item_id"] == "T4_CLOTH"


def test_albion_provider_fallback_snapshot_when_sync_fails(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "updated_at": 1700000000,
                "items": [{"id": "T4_PLANKS", "name": "Adept's Planks", "tier": 4, "enchant": 0, "icon": "https://icons/T4_PLANKS.png", "category": "material", "craftable": True}],
                "recipes": {"T4_PLANKS": [{"item_id": "T4_LOG", "item_name": "Adept's Log", "quantity": 2}]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALBION_PROVIDER_URL", "https://provider.example/catalog")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()

    async def fail_fetch():
        raise AlbionProviderError("provider_unreachable", "network down")

    monkeypatch.setattr(provider, "_fetch_remote_catalog", fail_fetch)
    _run(provider.refresh(force=True))

    rows = _run(provider.search_items("planks", 5))
    assert rows[0]["id"] == "T4_PLANKS"
