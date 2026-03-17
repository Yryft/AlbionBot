from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from albionbot.storage.store import Store

from .gameinfo_client import GAMEINFO_BASE_URLS, GameInfoClient, GameInfoError, GameInfoNotFoundError

DATA_DIR = Path(__file__).resolve().parent / "data" / "crafting"


def load_json_file(filename: str, fallback: Any) -> Any:
    path = DATA_DIR / filename
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def compute_focus_cost(base_focus_cost: int, fce_total: int) -> int:
    return int(math.ceil(max(0, int(base_focus_cost)) * (0.5 ** (max(0, int(fce_total)) / 10000.0))))


def compute_rrr_from_lpb(lpb: float) -> float:
    lpb_value = max(0.0, float(lpb))
    return lpb_value / (1.0 + lpb_value)


@dataclass
class ItemSelection:
    type_key: str
    tier: int
    enchant: int


class CraftingService:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store
        self.recipes_index = load_json_file("recipes_index.json", {})
        self.items_catalog = load_json_file("items_catalog.json", [])
        self.coefficients = load_json_file("coefficients.json", {})
        self.crafting_modifiers = load_json_file("craftingmodifiers.json", {})
        self.hideout_rates = load_json_file("hideout_return_rates.json", {})
        self._gameinfo_clients = [GameInfoClient(base_url=key) for key in ("gameinfo", "gameinfo-ams", "gameinfo-sgp")]

    def list_craftable_items(self) -> list[dict[str, Any]]:
        return list(self.items_catalog)

    def resolve_runtime_item_id(self, type_key: str, tier: int) -> str:
        prefix = f"T{max(4, min(8, int(tier)))}_"
        return f"{prefix}{type_key}"

    async def get_item_data(self, item_id: str) -> dict[str, Any]:
        path = f"/api/gameinfo/items/{item_id}/data"
        last_error: Exception | None = None
        for client in self._gameinfo_clients:
            try:
                payload = await client.get_json(path)
                if isinstance(payload, dict):
                    return payload
            except GameInfoNotFoundError:
                raise
            except GameInfoError as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise GameInfoError("unavailable", "GameInfo indisponible")

    def _resolve_focus_base(self, item_data: dict[str, Any], enchant: int) -> int:
        crafting_requirements = item_data.get("craftingRequirements", {}) if isinstance(item_data, dict) else {}
        base_focus = int(crafting_requirements.get("craftingFocus") or 0)
        for enchant_entry in item_data.get("enchantments", []) or []:
            if int(enchant_entry.get("enchantmentLevel") or 0) == enchant:
                enchant_req = enchant_entry.get("craftingRequirements", {})
                return int(enchant_req.get("craftingFocus") or base_focus)
        return base_focus

    def _resolve_recipes(self, item_id: str, enchant: int, item_data: dict[str, Any]) -> list[dict[str, Any]]:
        recipes = self.recipes_index.get(item_id, [])
        if recipes:
            out: list[dict[str, Any]] = []
            for idx, recipe in enumerate(recipes):
                out.append(
                    {
                        "variantKey": recipe.get("variantKey") or f"v{idx+1}",
                        "recipeId": recipe.get("recipeId") or f"{item_id}-r{idx+1}",
                        "name": recipe.get("name") or f"Recette {idx+1}",
                        "baseFocusCost": int(recipe.get("baseFocusCost") or 0),
                        "craftTime": int(recipe.get("craftTime") or 0),
                        "source": recipe.get("source") or "local-index",
                        "ingredients": [
                            {
                                "itemId": ingredient.get("itemId"),
                                "count": int(ingredient.get("count") or 0),
                                "enchantScaled": bool(ingredient.get("enchantScaled", False)),
                                "effectiveEnchant": enchant if ingredient.get("enchantScaled") else 0,
                            }
                            for ingredient in recipe.get("ingredients", [])
                        ],
                    }
                )
            return out

        crafting_requirements = item_data.get("craftingRequirements", {}) if isinstance(item_data, dict) else {}
        return [
            {
                "variantKey": "default",
                "recipeId": f"{item_id}:default",
                "name": "Recette GameInfo",
                "baseFocusCost": int(crafting_requirements.get("craftingFocus") or 0),
                "craftTime": 0,
                "source": "gameinfo",
                "ingredients": [
                    {
                        "itemId": ingredient.get("uniqueName"),
                        "count": int(ingredient.get("count") or 0),
                        "enchantScaled": bool(ingredient.get("enchant") is True),
                        "effectiveEnchant": enchant if ingredient.get("enchant") is True else 0,
                    }
                    for ingredient in crafting_requirements.get("craftResourceList", [])
                ],
            }
        ]

    def _build_lpb(self, location: dict[str, Any]) -> float:
        kind = str(location.get("kind") or "city")
        key = str(location.get("key") or "").lower()
        with_focus = bool(location.get("withFocus", False))
        with_daily = bool(location.get("withDailyBonus", False))
        source_table = self.crafting_modifiers.get(kind, {}) if isinstance(self.crafting_modifiers, dict) else {}
        lpb = float(source_table.get(key, source_table.get("default", 0.0)))
        if with_focus:
            lpb += float(self.crafting_modifiers.get("focusBonus", 0.0))
        if with_daily:
            lpb += float(self.crafting_modifiers.get("dailyBonus", 0.0))
        if kind == "hideout":
            hideout_level = str(location.get("hideoutLevel") or "1")
            map_quality = str(location.get("mapQuality") or "normal")
            lpb += float(self.hideout_rates.get(hideout_level, {}).get(map_quality, 0.0))
        return lpb

    def compute_fce_total(self, item_id: str, spec_profile: dict[str, int], category_id: str) -> int:
        default_coeff = self.coefficients.get("default", {})
        category_coeff = self.coefficients.get("categories", {}).get(category_id, {})
        item_coeff = self.coefficients.get("items", {}).get(item_id, {})
        return int(
            int(spec_profile.get("group", 0)) * int(default_coeff.get("groupPerLevel", 0))
            + int(spec_profile.get("category", 0)) * int(category_coeff.get("categoryPerLevel", default_coeff.get("categoryPerLevel", 0)))
            + int(spec_profile.get("item", 0)) * int(item_coeff.get("itemPerLevel", default_coeff.get("itemPerLevel", 250)))
            + int(spec_profile.get("others", 0)) * int(category_coeff.get("otherItemPerLevel", default_coeff.get("otherItemPerLevel", 0)))
        )

    async def build_item_payload(self, type_key: str, tier: int, enchant: int, spec_profile: dict[str, int] | None = None, location: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime_item_id = self.resolve_runtime_item_id(type_key, tier)
        item_data = await self.get_item_data(runtime_item_id)
        category_id = str(item_data.get("categoryId") or "")
        base_focus = self._resolve_focus_base(item_data, enchant)
        fce_total = self.compute_fce_total(item_id=runtime_item_id, spec_profile=(spec_profile or {}), category_id=category_id)
        focus_cost = compute_focus_cost(base_focus, fce_total)
        recipes = self._resolve_recipes(item_id=runtime_item_id, enchant=enchant, item_data=item_data)
        lpb = self._build_lpb(location or {})
        return {
            "item": {
                "id": runtime_item_id,
                "typeKey": type_key,
                "name": item_data.get("localizedNames", {}).get("EN-US") or runtime_item_id,
                "tier": tier,
                "enchant": enchant,
            },
            "categoryId": category_id,
            "iconUrl": f"{GAMEINFO_BASE_URLS['gameinfo']}/api/gameinfo/items/{runtime_item_id}.png",
            "baseFocusCost": base_focus,
            "fceTotal": fce_total,
            "focusCost": focus_cost,
            "recipes": recipes,
            "rrrByLocation": {"lpb": lpb, "rrr": compute_rrr_from_lpb(lpb)},
        }

    # persistence helpers
    def get_user_profile(self, guild_id: int, user_id: int) -> dict[str, Any]:
        if self.store and self.store.bank_db:
            return self.store.bank_db.get_craft_profile(guild_id, user_id)
        return {"category_specs": {}, "item_specs": {}, "preferences": {}}

    def set_user_profile(self, guild_id: int, user_id: int, category_specs: dict[str, Any], item_specs: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
        if self.store and self.store.bank_db:
            self.store.bank_db.upsert_craft_profile(guild_id, user_id, category_specs, item_specs, preferences)
        return {"category_specs": category_specs, "item_specs": item_specs, "preferences": preferences}

    def list_presets(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        if self.store and self.store.bank_db:
            return self.store.bank_db.list_craft_presets(guild_id, user_id)
        return []

    def save_preset(self, guild_id: int, user_id: int, name: str, payload: dict[str, Any], preset_id: str | None = None) -> dict[str, Any]:
        resolved_id = preset_id or str(uuid.uuid4())
        if self.store and self.store.bank_db:
            self.store.bank_db.upsert_craft_preset(resolved_id, guild_id, user_id, name, payload)
        return {"preset_id": resolved_id, "name": name, "payload": payload, "updated_at": int(time.time())}
