from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict


class CraftSimulationError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class FocusYieldConfig:
    base_return_rate: float = 0.152
    location_return_rate_bonus: float = 0.0
    hideout_return_rate_bonus: float = 0.0
    focus_return_rate_bonus: float = 0.0
    additional_return_rate_bonus: float = 0.0


@dataclass(frozen=True)
class CraftSimulationInput:
    quantity: int
    mastery_level: int
    specialization_level: int
    available_focus: int
    base_focus_cost: int
    use_focus: bool
    yields: FocusYieldConfig


@dataclass(frozen=True)
class MaterialQuantity:
    item_id: str
    item_name: str
    gross_quantity: int
    net_quantity: int


@dataclass(frozen=True)
class CraftSimulationResult:
    focus_efficiency: float
    focus_per_item: int
    total_focus: int
    items_craftable_with_available_focus: int
    applied_yields: dict[str, float]
    base_materials: list[MaterialQuantity]
    intermediate_materials: list[MaterialQuantity]


def calculate_focus_efficiency(mastery_level: int, specialization_level: int) -> float:
    """Retourne une efficacité [0, 0.5].

    Hypothèse: maîtrise et spécialisation réduisent chacune le coût focus,
    jusqu'à 50% de réduction combinée au maximum.
    """
    _validate_level(mastery_level, "mastery_level")
    _validate_level(specialization_level, "specialization_level")
    efficiency = (mastery_level * 0.002) + (specialization_level * 0.003)
    return min(0.5, max(0.0, efficiency))


def calculate_focus_costs(quantity: int, base_focus_cost: int, focus_efficiency: float) -> tuple[int, int]:
    if quantity <= 0:
        raise CraftSimulationError("invalid_quantity", "La quantité doit être strictement positive")
    if base_focus_cost <= 0:
        raise CraftSimulationError("invalid_focus_cost", "Le coût focus de base doit être strictement positif")
    if focus_efficiency < 0 or focus_efficiency > 0.5:
        raise CraftSimulationError("invalid_focus_efficiency", "L'efficacité focus doit être comprise entre 0 et 0.5")

    focus_per_item = max(1, math.ceil(base_focus_cost * (1.0 - focus_efficiency)))
    return focus_per_item, focus_per_item * quantity


def expand_materials(
    recipe: list[dict],
    quantity: int,
    recipes_by_item_id: Dict[str, list[dict]],
    craftable_by_item_id: Dict[str, bool],
    names_by_item_id: Dict[str, str],
) -> tuple[dict[str, int], dict[str, int]]:
    if quantity <= 0:
        raise CraftSimulationError("invalid_quantity", "La quantité doit être strictement positive")

    base_totals: dict[str, int] = {}
    intermediate_totals: dict[str, int] = {}

    def _expand(item_id: str, gross_qty: int) -> None:
        nested_recipe = recipes_by_item_id.get(item_id, [])
        is_craftable = bool(craftable_by_item_id.get(item_id, False))
        if is_craftable and nested_recipe:
            intermediate_totals[item_id] = intermediate_totals.get(item_id, 0) + gross_qty
            for mat in nested_recipe:
                _expand(str(mat["item_id"]), gross_qty * int(mat["quantity"]))
            return
        base_totals[item_id] = base_totals.get(item_id, 0) + gross_qty

    for mat in recipe:
        mat_id = str(mat["item_id"])
        mat_qty = int(mat["quantity"])
        _expand(mat_id, mat_qty * quantity)

    return base_totals, intermediate_totals


def simulate_crafting(
    simulation_input: CraftSimulationInput,
    recipe: list[dict],
    recipes_by_item_id: Dict[str, list[dict]],
    craftable_by_item_id: Dict[str, bool],
    names_by_item_id: Dict[str, str],
) -> CraftSimulationResult:
    _validate_level(simulation_input.mastery_level, "mastery_level")
    _validate_level(simulation_input.specialization_level, "specialization_level")
    if simulation_input.available_focus < 0:
        raise CraftSimulationError("invalid_available_focus", "Le focus disponible ne peut pas être négatif")

    focus_efficiency = calculate_focus_efficiency(
        simulation_input.mastery_level,
        simulation_input.specialization_level,
    )
    focus_per_item, total_focus = calculate_focus_costs(
        simulation_input.quantity,
        simulation_input.base_focus_cost,
        focus_efficiency,
    )

    base_totals, intermediate_totals = expand_materials(
        recipe=recipe,
        quantity=simulation_input.quantity,
        recipes_by_item_id=recipes_by_item_id,
        craftable_by_item_id=craftable_by_item_id,
        names_by_item_id=names_by_item_id,
    )

    total_return_rate = _compute_total_return_rate(simulation_input.yields, simulation_input.use_focus)

    base_materials = _to_material_rows(base_totals, names_by_item_id, total_return_rate)
    intermediate_materials = _to_material_rows(intermediate_totals, names_by_item_id, total_return_rate)

    items_with_focus = simulation_input.quantity if not simulation_input.use_focus else simulation_input.available_focus // focus_per_item

    return CraftSimulationResult(
        focus_efficiency=focus_efficiency,
        focus_per_item=focus_per_item,
        total_focus=total_focus,
        items_craftable_with_available_focus=max(0, items_with_focus),
        applied_yields={
            "base_return_rate": simulation_input.yields.base_return_rate,
            "location_return_rate_bonus": simulation_input.yields.location_return_rate_bonus,
            "hideout_return_rate_bonus": simulation_input.yields.hideout_return_rate_bonus,
            "focus_return_rate_bonus": simulation_input.yields.focus_return_rate_bonus if simulation_input.use_focus else 0.0,
            "additional_return_rate_bonus": simulation_input.yields.additional_return_rate_bonus,
            "total_return_rate": total_return_rate,
        },
        base_materials=base_materials,
        intermediate_materials=intermediate_materials,
    )


def _to_material_rows(totals: dict[str, int], names_by_item_id: Dict[str, str], total_return_rate: float) -> list[MaterialQuantity]:
    rows: list[MaterialQuantity] = []
    for item_id in sorted(totals.keys()):
        gross = totals[item_id]
        net = max(0, math.ceil(gross * (1.0 - total_return_rate)))
        rows.append(
            MaterialQuantity(
                item_id=item_id,
                item_name=names_by_item_id.get(item_id, item_id),
                gross_quantity=gross,
                net_quantity=net,
            )
        )
    return rows


def _compute_total_return_rate(yields: FocusYieldConfig, use_focus: bool) -> float:
    total = yields.base_return_rate + yields.location_return_rate_bonus + yields.hideout_return_rate_bonus + yields.additional_return_rate_bonus
    if use_focus:
        total += yields.focus_return_rate_bonus
    return min(0.95, max(0.0, total))


def _validate_level(value: int, field_name: str) -> None:
    if value < 0 or value > 100:
        raise CraftSimulationError("invalid_level", f"{field_name} doit être borné entre 0 et 100", details={"field": field_name})
