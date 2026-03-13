from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gameinfo_client import (
    GAMEINFO_BASE_URLS,
    GameInfoClient,
    GameInfoError,
    GameInfoNotFoundError,
)

DATA_DIR = Path(__file__).resolve().parent / "data" / "crafting"


def load_json_file(filename: str, fallback: Any) -> Any:
    path = DATA_DIR / filename
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def compute_focus_cost(base_focus_cost: int, fce_total: int) -> int:
    base = max(0, int(base_focus_cost))
    fce = max(0, int(fce_total))
    value = base * (0.5 ** (fce / 10000.0))
    return int(math.ceil(value))


def compute_rrr_from_lpb(lpb: float) -> float:
    lpb_value = max(0.0, float(lpb))
    return lpb_value / (1.0 + lpb_value)


@dataclass
class RecipeEntry:
    recipe_id: str
    ingredients: list[dict[str, Any]]


class CraftingService:
    def __init__(self) -> None:
        self.recipes_index = load_json_file("recipes_index.json", {})
        self.items_catalog = load_json_file("items_catalog.json", [])
        self.coefficients = load_json_file("coefficients.json", {})
        self.crafting_modifiers = load_json_file("craftingmodifiers.json", {})
        self.world_map = load_json_file("world.json", {})
        self.hideout_rates = load_json_file("hideout_return_rates.json", {})
        self._gameinfo_clients = [GameInfoClient(base_url=key) for key in ("gameinfo", "gameinfo-ams", "gameinfo-sgp")]

    def list_craftable_items(self) -> list[dict[str, Any]]:
        return list(self.items_catalog)

    def list_category_types(self, category_id: str) -> list[dict[str, Any]]:
        return [entry for entry in self.items_catalog if str(entry.get("categoryId", "")).lower() == category_id.lower()]

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
                continue
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
            return [
                {
                    "recipeId": recipe.get("recipeId", f"{item_id}-r{idx+1}"),
                    "name": recipe.get("name") or f"Recette {idx+1}",
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
                for idx, recipe in enumerate(recipes)
            ]

        crafting_requirements = item_data.get("craftingRequirements", {}) if isinstance(item_data, dict) else {}
        return [
            {
                "recipeId": f"{item_id}:default",
                "name": "Recette GameInfo",
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
        category_bonus = float(location.get("categoryBonus") or 0.0)
        with_focus = bool(location.get("withFocus", False))
        with_daily = bool(location.get("withDailyBonus", False))

        source_table = self.crafting_modifiers.get(kind, {}) if isinstance(self.crafting_modifiers, dict) else {}
        base_bonus = float(source_table.get(key, source_table.get("default", 0.0)))
        lpb = base_bonus + category_bonus
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

        group_level = int(spec_profile.get("group", 0))
        category_level = int(spec_profile.get("category", 0))
        item_level = int(spec_profile.get(item_id, spec_profile.get("item", 0)))
        other_avg_level = int(spec_profile.get("others", 0))

        return int(
            group_level * int(default_coeff.get("groupPerLevel", 0))
            + category_level * int(category_coeff.get("categoryPerLevel", default_coeff.get("categoryPerLevel", 0)))
            + item_level * int(item_coeff.get("itemPerLevel", default_coeff.get("itemPerLevel", 250)))
            + other_avg_level * int(category_coeff.get("otherItemPerLevel", default_coeff.get("otherItemPerLevel", 0)))
        )

    async def build_item_payload(
        self,
        item_id: str,
        tier: int,
        enchant: int,
        spec_profile: dict[str, int] | None = None,
        location: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item_data = await self.get_item_data(item_id)
        category_id = str(item_data.get("categoryId") or "")
        base_focus = self._resolve_focus_base(item_data, enchant)
        profile = spec_profile or {}
        fce_total = self.compute_fce_total(item_id=item_id, spec_profile=profile, category_id=category_id)
        focus_cost = compute_focus_cost(base_focus, fce_total)

        recipes = self._resolve_recipes(item_id=item_id, enchant=enchant, item_data=item_data)

        lpb = self._build_lpb(location or {})
        rrr = compute_rrr_from_lpb(lpb)

        return {
            "item": {
                "id": item_id,
                "name": item_data.get("localizedNames", {}).get("EN-US") or item_data.get("uniqueName") or item_id,
                "tier": tier,
                "enchant": enchant,
            },
            "categoryId": category_id,
            "iconUrl": f"{GAMEINFO_BASE_URLS['gameinfo']}/api/gameinfo/items/{item_id}.png",
            "baseFocusCost": base_focus,
            "fceTotal": fce_total,
            "focusCost": focus_cost,
            "recipes": recipes,
            "rrrByLocation": {
                "lpb": lpb,
                "rrr": rrr,
            },
        }
