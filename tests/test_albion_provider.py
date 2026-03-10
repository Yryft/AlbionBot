from __future__ import annotations

import asyncio
import json

from albionbot.storage.store import Store

from web.backend.albion_provider import (
    AO_BIN_DUMPS_ITEMS_LIST_URL,
    TOOLS4ALBION_ITEM_DETAILS_URL_TEMPLATE,
    AlbionProviderError,
    AlbionProviderService,
)


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


def test_albion_provider_merges_items_list_source(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    assert provider.items_list_url == AO_BIN_DUMPS_ITEMS_LIST_URL

    async def fake_fetch_items_list():
        return [
            {"id": "T4_BAG", "name": "T4_BAG", "tier": 0, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "unknown", "craftable": True},
            {"id": "T5_CAPE", "name": "T5_CAPE", "tier": 0, "enchant": 0, "icon": "https://icons/T5_CAPE.png", "category": "unknown", "craftable": True},
        ]

    monkeypatch.setattr(provider, "_fetch_items_list", fake_fetch_items_list)
    _run(provider.refresh(force=True))

    rows = _run(provider.search_items("cape", 10))
    assert len(rows) == 1
    assert rows[0]["id"] == "T5_CAPE"


def test_albion_provider_fetches_item_detail_on_demand(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    assert provider.item_details_url_template == TOOLS4ALBION_ITEM_DETAILS_URL_TEMPLATE
    provider._items_cache = [
        {"id": "T4_BAG", "name": "T4_BAG", "tier": 0, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "unknown", "craftable": True}
    ]

    async def fake_fetch_item_detail(item_id: str):
        assert item_id == "T4_BAG"
        return {
            "item": {"name": "Adept's Bag", "tier": 4, "enchant": 0, "category": "bag", "craftable": True},
            "recipe": [{"item_id": "T4_CLOTH", "item_name": "Simple Cloth", "quantity": 8}],
        }

    monkeypatch.setattr(provider, "_fetch_item_detail", fake_fetch_item_detail)

    detail = _run(provider.get_item_detail("T4_BAG"))
    assert detail["item"]["name"] == "Adept's Bag"
    assert detail["recipe"][0]["item_id"] == "T4_CLOTH"



def test_albion_provider_errors_when_no_source_and_no_cache(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()

    async def fail_fetch_items_list():
        raise AlbionProviderError("items_list_unreachable", "network down")

    monkeypatch.setattr(provider, "_fetch_items_list", fail_fetch_items_list)

    try:
        _run(provider.refresh(force=True))
        assert False, "refresh should fail when no source is configured"
    except AlbionProviderError as exc:
        assert exc.code == "items_list_unreachable"


def test_albion_provider_normalizes_list_payload_detail(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    provider._items_cache = [
        {"id": "T6_CAPE", "name": "T6_CAPE", "tier": 0, "enchant": 0, "icon": "https://icons/T6_CAPE.png", "category": "unknown", "craftable": True}
    ]

    async def fake_fetch_item_detail(item_id: str):
        assert item_id == "T6_CAPE"
        return {
            "item": {
                "ItemTypeId": "T6_CAPE",
                "LocalizedName": "Master's Cape",
                "Icon": "https://icons/T6_CAPE.png",
                "Tier": 6,
            },
            "CraftingRequirements": [
                {"ItemTypeId": "T6_CLOTH", "LocalizedName": "Master's Cloth", "Count": 8}
            ],
        }

    monkeypatch.setattr(provider, "_fetch_item_detail", fake_fetch_item_detail)

    detail = _run(provider.get_item_detail("T6_CAPE"))
    assert detail["item"]["name"] == "Master's Cape"
    assert detail["recipe"][0]["item_id"] == "T6_CLOTH"


def test_albion_provider_hydrates_focus_cost_metadata_from_store(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    store = Store(path=str(tmp_path / "state.json"), bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    store.craft_upsert_focus_cost(item_id="T4_BAG", base_focus_cost=222, source="manual_test")

    provider = AlbionProviderService(store=store)
    provider._items_cache = [
        {"id": "T4_BAG", "name": "T4_BAG", "tier": 4, "enchant": 0, "icon": "https://icons/T4_BAG.png", "category": "unknown", "craftable": True}
    ]
    provider._last_refresh_ts = 9999999999
    provider._recipes_cache = {"T4_BAG": [{"item_id": "T4_CLOTH", "item_name": "Cloth", "quantity": 2}]}

    detail = _run(provider.get_item_detail("T4_BAG"))
    assert detail["metadata"]["base_focus_cost"] == 222
    assert detail["metadata"]["base_focus_cost_source"] == "manual_test"


def test_albion_provider_infers_weapon_category_from_item_id(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    rows = provider._parse_items_list_text("T4_2H_HOLYSTAFF\n")

    assert rows[0]["category"] == "holy_staff"


def test_albion_provider_parses_prefixed_item_id_from_items_list(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    rows = provider._parse_items_list_text("1001: T6_HIDE_LEVEL1@1\n")

    assert len(rows) == 1
    assert rows[0]["id"] == "T6_HIDE_LEVEL1@1"


def test_albion_provider_keeps_normal_items_list_line_unchanged(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    rows = provider._parse_items_list_text("T5_CAPE\n")

    assert len(rows) == 1
    assert rows[0]["id"] == "T5_CAPE"






def test_albion_provider_normalize_item_fallbacks_to_item_id_when_name_blank(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    row = provider._normalize_item({"id": "T4_MAIN_SWORD", "name": "   "})

    assert row["id"] == "T4_MAIN_SWORD"
    assert row["name"] == "T4_MAIN_SWORD"
def test_albion_provider_parses_items_list_with_trailing_colon_name(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    rows = provider._parse_items_list_text("2066: T7_OFF_SHIELD_HELL@4 : Grandmaster's Caitiff Shield\n")

    assert len(rows) == 1
    assert rows[0]["id"] == "T7_OFF_SHIELD_HELL@4"
    assert rows[0]["name"] == "Grandmaster's Caitiff Shield"
    assert rows[0]["tier"] == 7
    assert rows[0]["enchant"] == 4
def test_albion_provider_parses_items_list_row_with_name_and_icon(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    rows = provider._parse_items_list_text('1001: T4_MAIN_SWORD;Adept Broadsword;https://icons/T4_MAIN_SWORD.png\n')

    assert len(rows) == 1
    assert rows[0]["id"] == "T4_MAIN_SWORD"
    assert rows[0]["name"] == "Adept Broadsword"
    assert rows[0]["icon"] == "https://icons/T4_MAIN_SWORD.png"
    assert rows[0]["tier"] == 4


def test_albion_provider_ignores_invalid_items_list_line(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    rows = provider._parse_items_list_text("1001: not-an-item\n")

    assert rows == []


def test_albion_provider_search_returns_clean_item_id_for_detail_fetch(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()

    async def fake_fetch_items_list():
        return provider._parse_items_list_text("1001: T6_HIDE_LEVEL1@1\n")

    async def fake_fetch_item_detail(item_id: str):
        assert item_id == "T6_HIDE_LEVEL1@1"
        return {
            "item": {"ItemTypeId": item_id, "LocalizedName": "Hide"},
            "recipe": [{"item_id": "T6_HIDE", "item_name": "Hide", "quantity": 1}],
        }

    monkeypatch.setattr(provider, "_fetch_items_list", fake_fetch_items_list)
    monkeypatch.setattr(provider, "_fetch_item_detail", fake_fetch_item_detail)

    _run(provider.refresh(force=True))
    rows = _run(provider.search_items("HIDE_LEVEL1", 10))

    assert rows[0]["id"] == "T6_HIDE_LEVEL1@1"

    detail = _run(provider.get_item_detail(rows[0]["id"]))
    assert detail["recipe"][0]["item_id"] == "T6_HIDE"


def test_albion_provider_normalizes_enchanted_item_id_suffix(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    item_id, enchant = provider.normalize_enchanted_item_id("T4_BAG", 2)

    assert item_id == "T4_BAG@2"
    assert enchant == 2


def test_albion_provider_parses_enchanted_suffix_from_item_id(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()
    base_item_id, enchant = provider.split_enchanted_item_id("T5_CAPE@3")

    assert base_item_id == "T5_CAPE"
    assert enchant == 3


def test_albion_provider_item_detail_empty_payload_is_item_not_found(tmp_path, monkeypatch):
    snapshot = tmp_path / "albion_snapshot.json"
    monkeypatch.setenv("ALBION_PROVIDER_URL", "")
    monkeypatch.setenv("ALBION_CACHE_SNAPSHOT_PATH", str(snapshot))

    provider = AlbionProviderService()

    class _Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            raise json.JSONDecodeError("Expecting value", "", 0)

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, endpoint: str):
            return _Response()

    monkeypatch.setattr("web.backend.albion_provider.httpx.AsyncClient", lambda timeout: _Client())

    try:
        _run(provider._fetch_item_detail("T4_BAG"))
        assert False, "expected item_not_found when provider payload is empty"
    except AlbionProviderError as exc:
        assert exc.code == "item_not_found"
