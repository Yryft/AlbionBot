from __future__ import annotations

from fastapi.testclient import TestClient

import web.backend.app as backend_app


async def _fake_item_detail(self, item_id: str):
    return {
        "item": {"id": item_id, "name": "Test Item", "craftable": True},
        "recipe": [{"item_id": "T4_BAR", "item_name": "Bar", "quantity": 2}],
        "metadata": {"base_focus_cost": 100},
    }


async def _fake_catalog_snapshot(self):
    return (
        [
            {"id": "ITEM_TEST", "name": "Test Item", "craftable": True},
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
            "mastery_level": 0,
            "specialization_level": 0,
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
    assert data["profit"] == 2300


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
            "focus_unit_price": 0,
            "include_focus_cost": True,
            "pricing_mode": "manual",
        },
    )

    assert response.status_code == 422


async def _fake_item_detail_missing_focus(self, item_id: str):
    return {
        "item": {"id": item_id, "name": "Test Item", "craftable": True},
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
            "mastery_level": 0,
            "specialization_level": 0,
            "location_key": "none",
            "available_focus": 0,
            "use_focus": False,
        },
    )

    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["code"] == "missing_focus_cost"
