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
            item_id="T4_2H_HOLYSTAFF",
            quantity=10,
            category_mastery_level=100,
            item_specializations={"T4_2H_HOLYSTAFF": 100, "T4_PLANK": 50},
            available_focus=5,
            base_focus_cost_by_item_id={"T4_2H_HOLYSTAFF": 100, "T4_PLANK": 60},
            item_category_by_item_id={"T4_2H_HOLYSTAFF": "holy_staff", "T4_PLANK": "holy_staff", "T4_LOG": "material"},
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
    # 500 sur l'item cible + 780 pour les 20 planks intermédiaires (efficacité 35%)
    assert result.total_focus == 1280
    assert result.items_craftable_with_available_focus == 0
    assert result.intermediate_materials[0].gross_quantity == 20
    assert result.base_materials[0].gross_quantity == 40
    assert result.applied_yields["total_return_rate"] == 0.682


def test_simulation_with_incomplete_specialization_tree_defaults_to_zero():
    result = simulate_crafting(
        simulation_input=CraftSimulationInput(
            item_id="T4_2H_HOLYSTAFF",
            quantity=2,
            category_mastery_level=50,
            item_specializations={"T4_2H_HOLYSTAFF": 10},
            available_focus=9999,
            base_focus_cost_by_item_id={"T4_2H_HOLYSTAFF": 100, "T4_PLANK": 40},
            item_category_by_item_id={"T4_2H_HOLYSTAFF": "holy_staff", "T4_PLANK": "material", "T4_LOG": "material"},
            use_focus=True,
            yields=FocusYieldConfig(),
        ),
        recipe=[{"item_id": "T4_PLANK", "quantity": 2}],
        recipes_by_item_id={"T4_PLANK": [{"item_id": "T4_LOG", "quantity": 2}]},
        craftable_by_item_id={"T4_PLANK": True, "T4_LOG": False},
        names_by_item_id={"T4_PLANK": "Plank", "T4_LOG": "Log"},
    )
    assert result.focus_per_item == 87
    # Intermédiaire hors catégorie => maîtrise catégorie = 0 et spé absente => 40*4
    assert result.total_focus == (87 * 2) + (40 * 4)


def test_invalid_level_raises_for_category_mastery():
    try:
        simulate_crafting(
            simulation_input=CraftSimulationInput(
                item_id="T4_BAG",
                quantity=1,
                category_mastery_level=101,
                item_specializations={"T4_BAG": 0},
                available_focus=0,
                base_focus_cost_by_item_id={"T4_BAG": 100},
                item_category_by_item_id={"T4_BAG": "bag"},
                use_focus=True,
                yields=FocusYieldConfig(),
            ),
            recipe=[],
            recipes_by_item_id={},
            craftable_by_item_id={},
            names_by_item_id={},
        )
    except CraftSimulationError as exc:
        assert exc.code == "invalid_level"
    else:  # pragma: no cover - defensive
        assert False, "Expected CraftSimulationError"


def test_level_bounds_accept_zero_and_hundred():
    low = simulate_crafting(
        simulation_input=CraftSimulationInput(
            item_id="T4_BAG",
            quantity=1,
            category_mastery_level=0,
            item_specializations={"T4_BAG": 0},
            available_focus=100,
            base_focus_cost_by_item_id={"T4_BAG": 100},
            item_category_by_item_id={"T4_BAG": "bag"},
            use_focus=True,
            yields=FocusYieldConfig(),
        ),
        recipe=[],
        recipes_by_item_id={},
        craftable_by_item_id={},
        names_by_item_id={},
    )
    high = simulate_crafting(
        simulation_input=CraftSimulationInput(
            item_id="T4_BAG",
            quantity=1,
            category_mastery_level=100,
            item_specializations={"T4_BAG": 100},
            available_focus=100,
            base_focus_cost_by_item_id={"T4_BAG": 100},
            item_category_by_item_id={"T4_BAG": "bag"},
            use_focus=True,
            yields=FocusYieldConfig(),
        ),
        recipe=[],
        recipes_by_item_id={},
        craftable_by_item_id={},
        names_by_item_id={},
    )
    assert low.focus_per_item == 100
    assert high.focus_per_item == 50
