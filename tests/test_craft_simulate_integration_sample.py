from fastapi.testclient import TestClient

import web.backend.app as backend_app


async def _fake_item_detail(self, item_id: str):
    return {
        "item": {"id": item_id, "name": "Avalonian Holy", "category": "holy_staff", "craftable": True},
        "recipe": [{"item_id": "T5_PLANK", "item_name": "Plank", "quantity": 4}],
        "recipes": [
            [{"item_id": "T5_MESSIANIC_CURIO", "item_name": "Messianic Curio", "quantity": 1}, {"item_id": "T5_PLANK", "item_name": "Plank", "quantity": 4}],
            [{"item_id": "T5_CRYSTALLIZED_DIVINITY", "item_name": "Crystallized Divinity", "quantity": 1}, {"item_id": "T5_PLANK", "item_name": "Plank", "quantity": 4}],
        ],
        "metadata": {"base_focus_cost": 1000, "base_focus_cost_by_enchant": {0: 1000, 1: 900, 2: 800}},
    }


async def _fake_catalog_snapshot(self):
    items = [
        {"id": "T5_MAIN_HOLYSTAFF", "name": "Holy Staff", "tier": 5, "icon": "", "category": "holy_staff", "craftable": True},
        {"id": "T5_2H_HOLYSTAFF_HELL", "name": "Damnation", "tier": 5, "icon": "", "category": "holy_staff", "craftable": True},
        {"id": "T5_MAIN_HOLYSTAFF_AVALON", "name": "Avalonian Holy", "tier": 5, "icon": "", "category": "holy_staff", "craftable": True},
        {"id": "T5_PLANK", "name": "Plank", "tier": 5, "icon": "", "category": "material", "craftable": False},
    ]
    recipes = {"T5_MAIN_HOLYSTAFF_AVALON": [{"item_id": "T5_PLANK", "quantity": 4}]}
    return items, recipes


def test_simulate_sample_item(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("BANK_SQLITE_PATH", str(tmp_path / "bank.sqlite3"))
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_item_detail", _fake_item_detail)
    monkeypatch.setattr(backend_app.AlbionProviderService, "get_catalog_snapshot", _fake_catalog_snapshot)
    client = TestClient(backend_app.create_app())

    specs = client.get("/api/craft/specializations/T5_MAIN_HOLYSTAFF_AVALON")
    assert specs.status_code == 200
    spec_data = specs.json()
    assert spec_data["category_id"] == "holy_staff"
    assert len(spec_data["items"]) >= 3

    resp = client.post("/api/craft/simulate", json={
        "item_id": "T5_MAIN_HOLYSTAFF_AVALON",
        "quantity": 10,
        "category_mastery_level": 100,
        "category_specializations": {"T5_MAIN_HOLYSTAFF_AVALON": 100},
        "item_specializations": {"T5_MAIN_HOLYSTAFF_AVALON": 100},
        "location_key": "none",
        "available_focus": 100000,
        "use_focus": True,
        "enchantment_level": 0,
    })
    assert resp.status_code == 200
    data0 = resp.json()
    assert data0["available_recipes"] == 2

    resp2 = client.post("/api/craft/simulate", json={
        "item_id": "T5_MAIN_HOLYSTAFF_AVALON",
        "quantity": 10,
        "category_mastery_level": 100,
        "category_specializations": {"T5_MAIN_HOLYSTAFF_AVALON": 100},
        "item_specializations": {"T5_MAIN_HOLYSTAFF_AVALON": 100},
        "location_key": "none",
        "available_focus": 100000,
        "use_focus": True,
        "enchantment_level": 2,
    })
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["focus_per_item"] <= data0["focus_per_item"]
