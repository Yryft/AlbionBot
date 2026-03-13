from __future__ import annotations

import pytest

from web.backend.crafting import CraftingService, compute_focus_cost, compute_rrr_from_lpb


def test_focus_cost_rounding_ceil():
    assert compute_focus_cost(123, 0) == 123
    assert compute_focus_cost(1000, 10000) == 500
    assert compute_focus_cost(1000, 15000) == 354  # ceil(353.55...)


def test_lpb_to_rrr_conversion():
    assert compute_rrr_from_lpb(0) == 0
    assert compute_rrr_from_lpb(1) == pytest.approx(0.5)
    assert compute_rrr_from_lpb(0.24) == pytest.approx(0.193548, rel=1e-5)


def test_multi_recipe_selection_from_index():
    service = CraftingService()
    recipes = service._resolve_recipes("T8_2H_HOLYSTAFF_HELL", enchant=3, item_data={"craftingRequirements": {}})

    assert len(recipes) == 2
    assert {r["recipeId"] for r in recipes} == {"hallowfall-ancient", "hallowfall-runic"}
    assert recipes[0]["ingredients"][0]["effectiveEnchant"] == 3
    assert recipes[0]["ingredients"][-1]["effectiveEnchant"] == 0
