from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

AO_BIN_DUMPS_ITEMS_LIST_URL = "https://raw.githubusercontent.com/broderickhyman/ao-bin-dumps/master/formatted/items.txt"
TOOLS4ALBION_ITEM_DETAILS_URL_TEMPLATE = "https://www.tools4albion.com/api_info.php?item_id={item_id}"


@dataclass(frozen=True)
class CraftItem:
    id: str
    name: str
    tier: int
    enchant: int
    icon: str
    category: str
    craftable: bool


@dataclass(frozen=True)
class CraftRecipeMaterial:
    item_id: str
    item_name: str
    quantity: int


@dataclass(frozen=True)
class CraftItemDetail:
    item: CraftItem
    recipe: list[CraftRecipeMaterial]
    metadata: dict[str, Any]


class AlbionProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AlbionProviderService:
    def __init__(self) -> None:
        self.provider_url = os.getenv("ALBION_PROVIDER_URL", "").strip()
        self.items_list_url = AO_BIN_DUMPS_ITEMS_LIST_URL
        self.item_details_url_template = TOOLS4ALBION_ITEM_DETAILS_URL_TEMPLATE
        self.icon_base_url = os.getenv("ALBION_ICON_BASE_URL", "https://render.albiononline.com/v1/item").strip().rstrip("/")
        self.timeout_s = float(os.getenv("ALBION_PROVIDER_TIMEOUT_SECONDS", "8"))
        self.memory_ttl_s = int(os.getenv("ALBION_CACHE_MEMORY_TTL_SECONDS", "300"))
        self.sync_interval_s = int(os.getenv("ALBION_SYNC_INTERVAL_SECONDS", "1800"))
        self.snapshot_path = Path(os.getenv("ALBION_CACHE_SNAPSHOT_PATH", "data/albion_provider_snapshot.json").strip())

        self._lock = asyncio.Lock()
        self._items_cache: list[dict[str, Any]] = []
        self._recipes_cache: dict[str, list[dict[str, Any]]] = {}
        self._last_refresh_ts = 0.0
        self._last_sync_error: str = ""
        self._load_snapshot()

    @property
    def last_sync_error(self) -> str:
        return self._last_sync_error

    def _load_snapshot(self) -> None:
        if not self.snapshot_path.exists():
            return
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to read Albion snapshot: %s", exc)
            return
        self._items_cache = payload.get("items", [])
        self._recipes_cache = payload.get("recipes", {})
        self._last_refresh_ts = float(payload.get("updated_at", 0.0))

    def _save_snapshot(self) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": self._last_refresh_ts,
            "items": self._items_cache,
            "recipes": self._recipes_cache,
        }
        self.snapshot_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _is_memory_cache_fresh(self) -> bool:
        return (time.time() - self._last_refresh_ts) < self.memory_ttl_s and bool(self._items_cache)

    def _item_icon(self, item_id: str) -> str:
        return f"{self.icon_base_url}/{item_id}.png"

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value: Any, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        raw = str(value).strip().lower()
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        if raw in {"0", "false", "no", "n", "off"}:
            return False
        return default

    def _normalize_item(self, row: dict[str, Any]) -> dict[str, Any]:
        item_id = str(
            row.get("id")
            or row.get("item_id")
            or row.get("ItemTypeId")
            or row.get("UniqueName")
            or ""
        ).strip()
        name = str(
            row.get("name")
            or row.get("localized_name")
            or row.get("item_name")
            or row.get("LocalizedName")
            or row.get("LocalizedNames")
            or item_id
        ).strip()
        tier = self._to_int(row.get("tier") or row.get("Tier") or 0)
        enchant = self._to_int(row.get("enchant") or row.get("EnchantmentLevel") or row.get("enchantment") or 0)
        category = str(row.get("category") or row.get("Category") or "unknown")
        craftable = self._to_bool(row.get("craftable") if "craftable" in row else row.get("Craftable"), default=True)
        if not item_id:
            raise AlbionProviderError("provider_invalid_payload", "Item provider sans identifiant")
        return {
            "id": item_id,
            "name": name,
            "tier": tier,
            "enchant": enchant,
            "icon": row.get("icon") or row.get("Icon") or self._item_icon(item_id),
            "category": category,
            "craftable": craftable,
        }

    def _parse_items_list_text(self, payload: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw_line in payload.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            item_id = line.split(";", 1)[0].split(",", 1)[0].strip().strip('"')
            if not item_id:
                continue
            rows.append(
                {
                    "id": item_id,
                    "name": item_id,
                    "tier": 0,
                    "enchant": 0,
                    "icon": self._item_icon(item_id),
                    "category": "unknown",
                    "craftable": True,
                }
            )
        return rows

    def _normalize_recipe(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        raw_materials = row.get("materials")
        if raw_materials is None:
            raw_materials = row.get("recipe")
        if raw_materials is None:
            raw_materials = row.get("Materials")
        if raw_materials is None:
            raw_materials = row.get("CraftingRequirements")

        mats: list[dict[str, Any]] = []
        if isinstance(raw_materials, list):
            for material in raw_materials:
                if not isinstance(material, dict):
                    continue
                mats.append(
                    {
                        "item_id": str(
                            material.get("item_id")
                            or material.get("id")
                            or material.get("ItemTypeId")
                            or material.get("UniqueName")
                            or ""
                        ).strip(),
                        "item_name": str(
                            material.get("item_name")
                            or material.get("name")
                            or material.get("LocalizedName")
                            or material.get("LocalizedNames")
                            or ""
                        ).strip(),
                        "quantity": self._to_int(
                            material.get("quantity")
                            or material.get("count")
                            or material.get("amount")
                            or material.get("Count")
                            or 0
                        ),
                    }
                )
        return [m for m in mats if m["item_id"] and m["quantity"] > 0]

    async def _fetch_remote_catalog(self) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        if not self.provider_url:
            raise AlbionProviderError("provider_not_configured", "ALBION_PROVIDER_URL manquant")

        endpoint = self.provider_url.rstrip("/")
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.get(endpoint)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise AlbionProviderError("provider_unreachable", "Provider Albion indisponible") from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise AlbionProviderError("provider_invalid_payload", "Payload provider invalide")

        raw_items = payload.get("items", [])
        raw_recipes = payload.get("recipes", {})
        if not isinstance(raw_items, list) or not isinstance(raw_recipes, dict):
            raise AlbionProviderError("provider_invalid_payload", "Structure provider invalide")

        items = [self._normalize_item(item) for item in raw_items if isinstance(item, dict)]
        recipes: dict[str, list[dict[str, Any]]] = {}
        for item_id, recipe in raw_recipes.items():
            normalized = self._normalize_recipe({"materials": recipe}) if isinstance(recipe, list) else self._normalize_recipe(recipe)
            recipes[str(item_id)] = normalized
        return items, recipes

    async def _fetch_items_list(self) -> list[dict[str, Any]]:
        if not self.items_list_url:
            return []
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.get(self.items_list_url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise AlbionProviderError("items_list_unreachable", "Source items indisponible") from exc
        return self._parse_items_list_text(response.text)

    async def _fetch_item_detail(self, item_id: str) -> dict[str, Any] | None:
        if not self.item_details_url_template:
            return None
        endpoint = self.item_details_url_template.format(item_id=item_id)
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            try:
                response = await client.get(endpoint)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise AlbionProviderError("item_detail_unreachable", "Détail item indisponible") from exc

        payload = response.json()
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        raise AlbionProviderError("provider_invalid_payload", "Payload détail item invalide")

    def _normalize_item_detail(self, item_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        item_row = payload.get("item") if isinstance(payload.get("item"), dict) else payload
        recipe_row = payload.get("recipe") or payload.get("materials") or payload.get("CraftingRequirements")
        if isinstance(recipe_row, list):
            recipe = self._normalize_recipe({"materials": recipe_row})
        elif isinstance(recipe_row, dict):
            recipe = self._normalize_recipe(recipe_row)
        else:
            recipe = self._normalize_recipe(payload)
        item = self._normalize_item({**item_row, "id": item_id})
        return item, recipe

    @staticmethod
    def _merge_items(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {str(row.get("id", "")).strip(): row for row in primary if str(row.get("id", "")).strip()}
        for row in secondary:
            item_id = str(row.get("id", "")).strip()
            if not item_id:
                continue
            by_id.setdefault(item_id, row)
        return list(by_id.values())

    async def refresh(self, force: bool = False) -> None:
        async with self._lock:
            if not force and self._is_memory_cache_fresh():
                return

            provider_items: list[dict[str, Any]] = []
            provider_recipes: dict[str, list[dict[str, Any]]] = {}
            errors: list[AlbionProviderError] = []

            if self.provider_url:
                try:
                    provider_items, provider_recipes = await self._fetch_remote_catalog()
                except AlbionProviderError as exc:
                    errors.append(exc)
                    self._last_sync_error = exc.message
                    logger.exception("Albion provider sync failed (%s): %s", exc.code, exc.message)

            items_from_list: list[dict[str, Any]] = []
            if self.items_list_url:
                try:
                    items_from_list = await self._fetch_items_list()
                except AlbionProviderError as exc:
                    errors.append(exc)
                    self._last_sync_error = exc.message
                    logger.exception("Albion items list sync failed (%s): %s", exc.code, exc.message)

            merged_items = self._merge_items(provider_items, items_from_list)
            if not merged_items:
                if self._items_cache:
                    return
                if errors:
                    raise errors[-1]
                raise AlbionProviderError("provider_not_configured", "Aucune source Albion configurée")

            self._items_cache = merged_items
            self._recipes_cache = provider_recipes or self._recipes_cache
            self._last_refresh_ts = time.time()
            self._last_sync_error = ""
            self._save_snapshot()

    async def invalidate(self) -> None:
        async with self._lock:
            self._last_refresh_ts = 0.0

    async def get_catalog_snapshot(self) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        await self.refresh(force=False)
        return list(self._items_cache), dict(self._recipes_cache)

    async def search_items(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        await self.refresh(force=False)
        q = query.strip().lower()
        rows = self._items_cache
        if q:
            rows = [item for item in rows if q in item["name"].lower() or q in item["id"].lower()]
        return rows[: max(1, min(limit, 50))]

    async def get_item_detail(self, item_id: str) -> dict[str, Any]:
        await self.refresh(force=False)
        key = item_id.strip()
        item = next((row for row in self._items_cache if row["id"] == key), None)
        if item is None:
            raise AlbionProviderError("item_not_found", "Item introuvable")

        recipe = self._recipes_cache.get(key, [])
        if not recipe:
            detail_payload = await self._fetch_item_detail(key)
            if detail_payload is not None:
                normalized_item, normalized_recipe = self._normalize_item_detail(key, detail_payload)
                item = normalized_item
                recipe = normalized_recipe
                self._recipes_cache[key] = normalized_recipe
                self._items_cache = self._merge_items([normalized_item], self._items_cache)
                self._save_snapshot()

        return {
            "item": item,
            "recipe": recipe,
            "metadata": {
                "source": "albion_provider",
                "snapshot_age_seconds": max(0, int(time.time() - self._last_refresh_ts)),
                "has_fallback_snapshot": self.snapshot_path.exists(),
                "last_sync_error": self._last_sync_error,
            },
        }
