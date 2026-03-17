from __future__ import annotations

from pathlib import Path

from albionbot.storage.store import Store
from web.backend.crafting import CraftingService


def test_crafting_profile_and_presets_persistence(tmp_path: Path):
    db_path = tmp_path / "bank.sqlite3"
    store = Store(path=str(tmp_path / "state.json"), bank_sqlite_path=str(db_path))
    service = CraftingService(store=store)

    profile = service.set_user_profile(
        guild_id=1,
        user_id=42,
        category_specs={"holy": 88},
        item_specs={"2H_HOLYSTAFF_HELL": 100},
        preferences={"tier": 8, "enchant": 3},
    )
    assert profile["category_specs"]["holy"] == 88

    loaded = service.get_user_profile(guild_id=1, user_id=42)
    assert loaded["item_specs"]["2H_HOLYSTAFF_HELL"] == 100

    saved = service.save_preset(guild_id=1, user_id=42, name="Hallowfall .3", payload={"typeKey": "2H_HOLYSTAFF_HELL", "tier": 8, "enchant": 3})
    assert saved["name"] == "Hallowfall .3"

    presets = service.list_presets(guild_id=1, user_id=42)
    assert len(presets) == 1
    assert presets[0]["payload"]["enchant"] == 3
