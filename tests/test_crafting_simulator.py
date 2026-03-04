from web.backend.domain.crafting.simulator import (
    CraftSimulationError,
    CraftSimulationInput,
    FocusYieldConfig,
    calculate_focus_costs,
    calculate_focus_efficiency,
    simulate_crafting,
)


def test_focus_efficiency_is_capped_at_mastery_max():
    assert calculate_focus_efficiency(100, 100) == 0.5


def test_focus_cost_rounding_for_quantity_one():
    efficiency = calculate_focus_efficiency(1, 1)
    focus_per_item, total = calculate_focus_costs(quantity=1, base_focus_cost=100, focus_efficiency=efficiency)
    assert focus_per_item == 100
    assert total == 100


def test_simulation_handles_insufficient_focus_and_hideout_bonus():
    result = simulate_crafting(
        simulation_input=CraftSimulationInput(
            quantity=10,
            mastery_level=100,
            specialization_level=100,
            available_focus=5,
            base_focus_cost=100,
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
    )
    assert result.focus_per_item == 50
    assert result.total_focus == 500
    assert result.items_craftable_with_available_focus == 0
    assert result.intermediate_materials[0].gross_quantity == 20
    assert result.base_materials[0].gross_quantity == 40
    assert result.applied_yields["total_return_rate"] == 0.682


def test_invalid_level_raises():
    try:
        calculate_focus_efficiency(101, 0)
    except CraftSimulationError as exc:
        assert exc.code == "invalid_level"
    else:  # pragma: no cover - defensive
        assert False, "Expected CraftSimulationError"
