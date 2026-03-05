from __future__ import annotations

import asyncio

from albionbot.storage.store import Store
from web.backend.albion_provider import AlbionProviderError, AlbionProviderService


def _run(coro):
    return asyncio.run(coro)


def _build_provider(tmp_path, monkeypatch) -> tuple[Store, AlbionProviderService]:
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(tmp_path / "snapshot.json"))
    store = Store(path=str(tmp_path / "state.json"), bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    provider = AlbionProviderService(store=store)
    return store, provider


def test_daily_sync_first_import_and_idempotence(tmp_path, monkeypatch):
    store, provider = _build_provider(tmp_path, monkeypatch)

    async def fetch_items_list():
        return [
            {"id": "T4_BAG", "name": "Adept Bag", "tier": 4, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "bag", "craftable": True},
            {"id": "T5_CAPE", "name": "Expert Cape", "tier": 5, "enchant": 0, "icon": "https://icons/T5_CAPE.png", "category": "cape", "craftable": True},
        ]

    monkeypatch.setattr(provider, "_fetch_items_list", fetch_items_list)
    _run(provider.refresh(force=True))

    rows = store.craft_search_items(query="", limit=20)
    assert len(rows) == 2
    sync = store.craft_get_sync_state()
    assert sync is not None
    assert sync["status"] == "ok"
    assert int(sync["inserted_count"]) == 2

    _run(provider.refresh(force=True))
    sync = store.craft_get_sync_state()
    assert sync is not None
    assert int(sync["inserted_count"]) == 0
    assert int(sync["updated_count"]) == 0
    assert int(sync["deactivated_count"]) == 0


def test_daily_sync_update_and_deactivate(tmp_path, monkeypatch):
    store, provider = _build_provider(tmp_path, monkeypatch)

    async def first_items_list():
        return [
            {"id": "T4_BAG", "name": "Adept Bag", "tier": 4, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "bag", "craftable": True},
            {"id": "T5_CAPE", "name": "Expert Cape", "tier": 5, "enchant": 0, "icon": "https://icons/T5_CAPE.png", "category": "cape", "craftable": True},
        ]

    async def second_items_list():
        return [
            {"id": "T4_BAG", "name": "Adept Bag Renamed", "tier": 4, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "bag", "craftable": True},
            {"id": "T6_CAPE", "name": "Master Cape", "tier": 6, "enchant": 0, "icon": "https://icons/T6_CAPE.png", "category": "cape", "craftable": True},
        ]

    monkeypatch.setattr(provider, "_fetch_items_list", first_items_list)
    _run(provider.refresh(force=True))

    monkeypatch.setattr(provider, "_fetch_items_list", second_items_list)
    _run(provider.refresh(force=True))

    sync = store.craft_get_sync_state()
    assert sync is not None
    assert int(sync["inserted_count"]) == 1
    assert int(sync["updated_count"]) == 1
    assert int(sync["deactivated_count"]) == 1

    active_rows = store.craft_search_items(query="", limit=20)
    assert sorted(row["item_id"] for row in active_rows) == ["T4_BAG", "T6_CAPE"]
    assert store.craft_get_item("T5_CAPE")["active"] in (0, False)


def test_daily_sync_fallback_when_network_fails(tmp_path, monkeypatch):
    store, provider = _build_provider(tmp_path, monkeypatch)

    async def first_items_list():
        return [{"id": "T4_BAG", "name": "Adept Bag", "tier": 4, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "bag", "craftable": True}]

    async def fail_items_list():
        raise AlbionProviderError("items_list_unreachable", "network down")

    monkeypatch.setattr(provider, "_fetch_items_list", first_items_list)
    _run(provider.refresh(force=True))
    first_sync = store.craft_get_sync_state()
    assert first_sync is not None

    monkeypatch.setattr(provider, "_fetch_items_list", fail_items_list)
    _run(provider.refresh(force=True))

    rows = _run(provider.search_items("bag", 10))
    assert rows and rows[0]["id"] == "T4_BAG"

    sync = store.craft_get_sync_state()
    assert sync is not None
    assert sync["status"] == "error"
    assert int(sync["last_success_at"]) == int(first_sync["last_success_at"])
