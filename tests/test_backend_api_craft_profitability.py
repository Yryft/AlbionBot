from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import web.backend.app as backend_app
from web.backend.albion_provider import AlbionProviderError


async def _fake_item_detail(self, item_id: str):
    return {
        "item": {"id": item_id, "name": "Test Item", "category": "nature_staff", "craftable": True},
        "recipe": [{"item_id": "T4_BAR", "item_name": "Bar", "quantity": 2}],
        "metadata": {"base_focus_cost": 100},
    }


async def _fake_catalog_snapshot(self):
    return (
        [
            {"id": "ITEM_TEST", "name": "Test Item", "craftable": True},
            {"id": "ITEM_TEST@2", "name": "Test Item .2", "craftable": True},
            {"id": "ITEM_TEST@3", "name": "Test Item .3", "craftable": True},
            {"id": "T4_BAR", "name": "Bar", "craftable": False},
        ],
        {"ITEM_TEST": [{"item_id": "T4_BAR", "item_name": "Bar", "quantity": 2}]},
    )


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot)
    app = backend_app.create_app()
    return TestClient(app)


def test_craft_profitability_returns_line_breakdown_and_totals(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    simulate_response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )
    assert simulate_response.status_code == 200

    payload = {
        "simulation": simulate_response.json(),
        "material_unit_prices": {"T4_BAR": 100},
        "imbuer_journal_unit_price": 50,
        "item_sale_unit_price": 500,
        "crafted_quantity": 10,
        "market_tax_rate": 10,
        "station_fee_rate": 5,
        "focus_unit_price": 2,
        "include_focus_cost": False,
        "pricing_mode": "manual",
    }

    response = client.post("/api/craft/profitability", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["material_lines"][0]["item_id"] == "T4_BAR"
    assert data["material_lines"][0]["quantity"] == 17
    assert data["total_material_cost"] == 1700
    assert data["imbuer_journal_cost"] == 500
    assert data["gross_revenue"] == 5000
    assert data["market_tax_amount"] == 500
    assert data["net_revenue"] == 4500
    assert data["station_fee_amount"] == 250
    assert data["profit"] == 2050


def test_craft_profitability_validates_payload(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/craft/profitability",
        json={
            "simulation": {
                "item_id": "ITEM_TEST",
                "focus_efficiency": 0,
                "focus_per_item": 100,
                "total_focus": 100,
                "items_craftable_with_available_focus": 1,
                "base_materials": [],
                "intermediate_materials": [],
                "applied_yields": {},
            },
            "material_unit_prices": {},
            "imbuer_journal_unit_price": 0,
            "item_sale_unit_price": 100,
            "crafted_quantity": 0,
            "market_tax_rate": 5,
            "station_fee_rate": 0,
            "focus_unit_price": 0,
            "include_focus_cost": True,
            "pricing_mode": "manual",
        },
    )

    assert response.status_code == 422


async def _fake_item_detail_missing_focus(self, item_id: str):
    return {
        "item": {"id": item_id, "name": "Test Item", "category": "nature_staff", "craftable": True},
        "recipe": [{"item_id": "T4_BAR", "item_name": "Bar", "quantity": 2}],
        "metadata": {},
    }


def test_craft_simulate_errors_when_focus_cost_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail_missing_focus)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot)
    client = TestClient(backend_app.create_app())

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["code"] == "missing_focus_cost"


async def _fake_item_detail_with_enchant(self, item_id: str):
    if item_id != "ITEM_TEST@2":
        raise AlbionProviderError("item_not_found", "missing variant")
    return {
        "item": {"id": item_id, "name": "Test Item .2", "category": "nature_staff", "craftable": True},
        "recipe": [{"item_id": "T4_BAR", "item_name": "Bar", "quantity": 2}],
        "metadata": {"base_focus_cost": 100},
    }


def test_craft_simulate_accepts_valid_enchantment_level(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail_with_enchant)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot)
    client = TestClient(backend_app.create_app())

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 2,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["item_id"] == "ITEM_TEST@2"


def test_craft_simulate_rejects_invalid_enchantment_level(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 9,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )

    assert response.status_code == 422


async def _fake_item_detail_variant_fallback(self, item_id: str):
    if item_id == "ITEM_TEST@3":
        raise AlbionProviderError("item_detail_unreachable", "variant unavailable")
    if item_id == "ITEM_TEST":
        return {
            "item": {"id": item_id, "name": "Test Item", "category": "nature_staff", "craftable": True},
            "recipe": [{"item_id": "T4_BAR", "item_name": "Bar", "quantity": 2}],
            "metadata": {"base_focus_cost": 100},
        }
    raise AlbionProviderError("item_not_found", "missing")


def test_craft_simulate_fallbacks_to_base_item_when_variant_detail_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail_variant_fallback)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot)
    client = TestClient(backend_app.create_app())

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 3,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["item_id"] == "ITEM_TEST"


def test_craft_simulate_applies_city_bonus_only_on_matching_city_category(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 0,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "city",
            "city_key": "lymhurst",
            "available_focus": 0,
            "use_focus": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["applied_yields"]["location_return_rate_bonus"] == 0.15

    mismatch_response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 0,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "city",
            "city_key": "martlock",
            "available_focus": 0,
            "use_focus": False,
        },
    )
    assert mismatch_response.status_code == 200
    assert mismatch_response.json()["applied_yields"]["location_return_rate_bonus"] == 0.0


def test_craft_simulate_applies_hideout_level_and_quality_bonus(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 0,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "hideout",
            "hideout_biome_key": "mountain",
            "hideout_territory_level": 9,
            "hideout_zone_quality": 6,
            "available_focus": 0,
            "use_focus": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["applied_yields"]["hideout_return_rate_bonus"] == pytest.approx(0.285)


def test_craft_simulate_applies_hideout_biome_activity_bonus_on_match(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 0,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "hideout",
            "hideout_biome_key": "forest",
            "hideout_territory_level": 9,
            "hideout_zone_quality": 6,
            "available_focus": 0,
            "use_focus": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["applied_yields"]["location_return_rate_bonus"] == pytest.approx(0.15)

    mismatch_response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "enchantment_level": 0,
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "hideout",
            "hideout_biome_key": "mountain",
            "hideout_territory_level": 9,
            "hideout_zone_quality": 6,
            "available_focus": 0,
            "use_focus": False,
        },
    )
    assert mismatch_response.status_code == 200
    assert mismatch_response.json()["applied_yields"]["location_return_rate_bonus"] == pytest.approx(0.0)

async def _fake_item_detail_provider_unreachable(self, item_id: str):
    raise AlbionProviderError("provider_unreachable", "Provider Albion indisponible")


def test_craft_simulate_surfaces_provider_error_code_and_message(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail_provider_unreachable)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot)
    client = TestClient(backend_app.create_app())

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "quantity": 10,
            "category_mastery_level": 0,
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["code"] == "provider_unreachable"
    assert payload["detail"]["message"] == "Provider Albion indisponible"


def test_craft_simulate_uses_category_specializations_for_target_focus(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/craft/simulate",
        json={
            "item_id": "ITEM_TEST",
            "quantity": 1,
            "category_mastery_level": 0,
            "category_specializations": {"ITEM_TEST": 100},
            "item_specializations": {"ITEM_TEST": 0},
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["focus_efficiency"] == pytest.approx(0.2)
    assert data["focus_per_item"] == 80


async def _fake_catalog_snapshot_specializations(self):
    return (
        [
            {"id": "ITEM_TEST", "name": "Test Item", "craftable": True, "category": "nature_staff", "tier": 4, "icon": "https://icons/ITEM_TEST.png"},
            {"id": "ITEM_OTHER", "name": "Other Item", "craftable": True, "category": "nature_staff", "tier": 7, "icon": "https://icons/ITEM_OTHER.png"},
            {"id": "ITEM_OTHER@2", "name": "Other Item .2", "craftable": True, "category": "nature_staff", "tier": 7, "icon": "https://icons/ITEM_OTHER.png"},
            {"id": "ITEM_DIFF_CAT", "name": "Diff", "craftable": True, "category": "axe", "tier": 5, "icon": "https://icons/ITEM_DIFF_CAT.png"},
        ],
        {},
    )


async def _fake_item_detail_holy_staff(self, item_id: str):
    return {
        "item": {
            "id": item_id,
            "name": "Expert's Holy Staff",
            "category": "holystaff",
            "craftable": True,
            "icon": "https://icons/T5_MAIN_HOLYSTAFF.png",
        },
        "recipe": [{"item_id": "T5_PLANKS", "item_name": "Planks", "quantity": 16}],
        "metadata": {},
    }


async def _fake_catalog_snapshot_holy_staff_unknown_category(self):
    return (
        [
            {"id": "T5_MAIN_HOLYSTAFF", "name": "Expert's Holy Staff", "craftable": True, "category": "unknown", "tier": 5, "icon": "https://icons/T5_MAIN_HOLYSTAFF.png"},
            {"id": "T5_2H_HOLYSTAFF", "name": "Great Holy Staff", "craftable": True, "category": "unknown", "tier": 5, "icon": "https://icons/T5_2H_HOLYSTAFF.png"},
            {"id": "T5_MAIN_NATURESTAFF", "name": "Nature Staff", "craftable": True, "category": "unknown", "tier": 5, "icon": "https://icons/T5_MAIN_NATURESTAFF.png"},
        ],
        {},
    )


def test_craft_specializations_lists_category_items_without_tier_filter(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot_specializations)
    client = TestClient(backend_app.create_app())

    response = client.get("/api/craft/specializations/ITEM_TEST")
    assert response.status_code == 200
    payload = response.json()

    assert payload["category"] == "nature_staff"
    assert payload["category_mastery_item_id"] == "T4_MAIN_NATURESTAFF"
    assert [row["item_id"] for row in payload["items"]] == ["ITEM_OTHER", "ITEM_TEST"]


def test_craft_specializations_matches_category_marker_when_catalog_categories_are_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail_holy_staff)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot_holy_staff_unknown_category)
    client = TestClient(backend_app.create_app())

    response = client.get("/api/craft/specializations/T5_MAIN_HOLYSTAFF")
    assert response.status_code == 200
    payload = response.json()

    assert payload["category"] == "holystaff"
    assert payload["category_mastery_item_id"] == "T4_MAIN_HOLYSTAFF"
    assert [row["item_id"] for row in payload["items"]] == ["T5_MAIN_HOLYSTAFF", "T5_2H_HOLYSTAFF"]
