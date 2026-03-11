from web.backend.domain.crafting.simulator import (
    CraftSimulationError,
    CraftSimulationInput,
    FocusYieldConfig,
    calculate_focus_costs,
    calculate_focus_efficiency_from_fce,
    simulate_crafting,
)


def test_focus_efficiency_from_fce_curve():
    assert round(calculate_focus_efficiency_from_fce(0), 4) == 0.0
    assert round(calculate_focus_efficiency_from_fce(10000), 4) == 0.5


def test_focus_cost_uses_exponential_fce_model():
    focus_per_item, total = calculate_focus_costs(quantity=1, base_focus_cost=1000, fce=10000)
    assert focus_per_item == 500
    assert total == 500


def test_simulation_uses_fce_and_intermediate_focus():
    result = simulate_crafting(
        simulation_input=CraftSimulationInput(
            item_id="T4_2H_HOLYSTAFF",
            quantity=10,
            category_mastery_level=100,
            category_specializations={},
            item_specializations={"T4_2H_HOLYSTAFF": 100, "T4_PLANK": 50},
            available_focus=5,
            base_focus_cost_by_item_id={"T4_2H_HOLYSTAFF": 1000, "T4_PLANK": 640},
            item_category_by_item_id={"T4_2H_HOLYSTAFF": "holy_staff", "T4_PLANK": "holy_staff", "T4_LOG": "material"},
            fce_by_item_id={"T4_2H_HOLYSTAFF": 10000, "T4_PLANK": 5000},
            use_focus=True,
            yields=FocusYieldConfig(
                base_return_rate=0.152,
                hideout_return_rate_bonus=0.28,
                focus_return_rate_bonus=0.25,
            ),
        ),
        recipe=[{"item_id": "T4_PLANK", "quantity": 2}],
        recipes_by_item_id={"T4_PLANK": [{"item_id": "T4_LOG", "quantity": 2}]},
        craftable_by_item_id={"T4_PLANK": True, "T4_LOG": False},
        names_by_item_id={"T4_PLANK": "Plank", "T4_LOG": "Log"},
        icons_by_item_id={},
    )
    assert result.focus_per_item == 500
    assert result.total_focus > 5000


def test_invalid_level_raises_for_category_mastery():
    try:
        simulate_crafting(
            simulation_input=CraftSimulationInput(
                item_id="T4_BAG",
                quantity=1,
                category_mastery_level=101,
                category_specializations={},
                item_specializations={"T4_BAG": 0},
                available_focus=0,
                base_focus_cost_by_item_id={"T4_BAG": 100},
                item_category_by_item_id={"T4_BAG": "bag"},
                fce_by_item_id={"T4_BAG": 0},
                use_focus=True,
                yields=FocusYieldConfig(),
            ),
            recipe=[],
            recipes_by_item_id={},
            craftable_by_item_id={},
            names_by_item_id={},
            icons_by_item_id={},
        )
    except CraftSimulationError as exc:
        assert exc.code == "invalid_level"
    else:
        assert False
