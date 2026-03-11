from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FCECoefficients:
    category_mastery: int
    category_specialization: int
    item_specialization: int


class FCECoefficientStore:
    def __init__(self, path: str = "web/backend/data/fce_coefficients.json") -> None:
        self.path = Path(path)
        self._cache: dict = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self._cache = {}
            return
        self._cache = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, category_id: str, item_id: str) -> tuple[FCECoefficients, bool]:
        default = self._to_coeffs((self._cache or {}).get("default") or {})
        category = (self._cache or {}).get(category_id, {}) if isinstance((self._cache or {}).get(category_id, {}), dict) else {}
        if item_id in category and isinstance(category[item_id], dict):
            return self._to_coeffs(category[item_id], default), True
        if "_category" in category and isinstance(category["_category"], dict):
            return self._to_coeffs(category["_category"], default), True
        return default, False

    @staticmethod
    def _to_coeffs(raw: dict, fallback: FCECoefficients | None = None) -> FCECoefficients:
        if fallback is None:
            fallback = FCECoefficients(category_mastery=20, category_specialization=10, item_specialization=20)
        return FCECoefficients(
            category_mastery=int(raw.get("category_mastery", fallback.category_mastery)),
            category_specialization=int(raw.get("category_specialization", fallback.category_specialization)),
            item_specialization=int(raw.get("item_specialization", fallback.item_specialization)),
        )


def compute_fce(
    *,
    category_mastery_level: int,
    category_specialization_level: int,
    item_specialization_level: int,
    coeffs: FCECoefficients,
) -> int:
    return max(
        0,
        (category_mastery_level * coeffs.category_mastery)
        + (category_specialization_level * coeffs.category_specialization)
        + (item_specialization_level * coeffs.item_specialization),
    )
