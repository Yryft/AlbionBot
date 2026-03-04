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

    def _normalize_item(self, row: dict[str, Any]) -> dict[str, Any]:
        item_id = str(row.get("id") or row.get("item_id") or "").strip()
        name = str(row.get("name") or row.get("localized_name") or item_id).strip()
        tier = int(row.get("tier") or 0)
        enchant = int(row.get("enchant") or 0)
        category = str(row.get("category") or "unknown")
        craftable = bool(row.get("craftable", True))
        if not item_id:
            raise AlbionProviderError("provider_invalid_payload", "Item provider sans identifiant")
        return {
            "id": item_id,
            "name": name,
            "tier": tier,
            "enchant": enchant,
            "icon": row.get("icon") or self._item_icon(item_id),
            "category": category,
            "craftable": craftable,
        }

    def _normalize_recipe(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        mats: list[dict[str, Any]] = []
        for material in row.get("materials", []):
            mats.append(
                {
                    "item_id": str(material.get("item_id") or material.get("id") or "").strip(),
                    "item_name": str(material.get("item_name") or material.get("name") or "").strip(),
                    "quantity": int(material.get("quantity") or 0),
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

        items = [self._normalize_item(item) for item in raw_items]
        recipes: dict[str, list[dict[str, Any]]] = {}
        for item_id, recipe in raw_recipes.items():
            normalized = self._normalize_recipe({"materials": recipe}) if isinstance(recipe, list) else self._normalize_recipe(recipe)
            recipes[str(item_id)] = normalized
        return items, recipes

    async def refresh(self, force: bool = False) -> None:
        async with self._lock:
            if not force and self._is_memory_cache_fresh():
                return
            try:
                items, recipes = await self._fetch_remote_catalog()
            except AlbionProviderError as exc:
                self._last_sync_error = exc.message
                logger.exception("Albion provider sync failed (%s): %s", exc.code, exc.message)
                if self._items_cache:
                    return
                raise
            self._items_cache = items
            self._recipes_cache = recipes
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
        return {
            "item": item,
            "recipe": self._recipes_cache.get(key, []),
            "metadata": {
                "source": "albion_provider",
                "snapshot_age_seconds": max(0, int(time.time() - self._last_refresh_ts)),
                "has_fallback_snapshot": self.snapshot_path.exists(),
                "last_sync_error": self._last_sync_error,
            },
        }
