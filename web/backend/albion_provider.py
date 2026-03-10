from __future__ import annotations

import asyncio
import json
from json import JSONDecodeError
import logging
import os
import time
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from albionbot.storage.store import Store

import httpx

logger = logging.getLogger(__name__)

AO_BIN_DUMPS_ITEMS_LIST_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt"
GAMEINFO_ITEM_DETAILS_URL_TEMPLATE = "https://gameinfo.albiononline.com/api/gameinfo/items/{item_id}/data"
ITEMS_LIST_LINE_PREFIX_PATTERN = re.compile(r"^\s*\d+\s*:\s*")
ITEMS_LIST_TOKEN_PATTERN = re.compile(r'\b((?:T\d+_[A-Z0-9_]+|UNIQUE_[A-Z0-9_]+)(?:@\d+)?)\b')


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
    def __init__(self, store: Store | None = None) -> None:
        self.provider_url = os.getenv("ALBION_PROVIDER_URL", "").strip()
        self.items_list_url = AO_BIN_DUMPS_ITEMS_LIST_URL
        self.item_details_url_template = GAMEINFO_ITEM_DETAILS_URL_TEMPLATE
        self.icon_base_url = os.getenv("ALBION_ICON_BASE_URL", "https://render.albiononline.com/v1/item").strip().rstrip("/")
        self.timeout_s = float(os.getenv("ALBION_PROVIDER_TIMEOUT_SECONDS", "8"))
        self.memory_ttl_s = int(os.getenv("ALBION_CACHE_MEMORY_TTL_SECONDS", "300"))
        self.snapshot_path = Path(os.getenv("ALBION_CACHE_SNAPSHOT_PATH", "data/albion_provider_snapshot.json").strip())
        self.sync_interval_s = int(os.getenv("ALBION_SYNC_INTERVAL_SECONDS", "86400"))
        self.store = store

        self._lock = asyncio.Lock()
        self._items_cache: list[dict[str, Any]] = []
        self._recipes_cache: dict[str, list[dict[str, Any]]] = {}
        self._last_refresh_ts = 0.0
        self._last_sync_error: str = ""
        self._load_snapshot()
        self._load_items_from_db()

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


    def _load_items_from_db(self) -> None:
        if self.store is None:
            return
        rows = self.store.craft_list_all_items(include_inactive=False)
        if rows:
            self._items_cache = [
                {
                    "id": str(row.get("item_id", "")),
                    "name": str(row.get("name", "")),
                    "tier": self._to_int(row.get("tier"), 0),
                    "enchant": self._to_int(row.get("enchant"), 0),
                    "icon": str(row.get("icon", "")),
                    "category": str(row.get("category", "unknown")),
                    "craftable": self._to_bool(row.get("craftable"), default=False),
                }
                for row in rows
            ]

    def get_sync_status(self) -> dict[str, Any]:
        if self.store is None:
            return {"status": "unavailable"}
        row = self.store.craft_get_sync_state()
        if row is None:
            return {"status": "never_synced"}
        return dict(row)

    def _persist_sync_failure(self, source: str, checksum: str, error_message: str) -> None:
        if self.store is None:
            return
        last = self.store.craft_get_sync_state() or {}
        now = int(time.time())
        self.store.craft_upsert_sync_state(
            source=source,
            checksum=checksum,
            status="error",
            items_count=int(last.get("items_count", 0) or 0),
            inserted_count=0,
            updated_count=0,
            deactivated_count=0,
            last_attempt_at=now,
            last_success_at=(int(last["last_success_at"]) if last.get("last_success_at") is not None else None),
            last_error=error_message,
        )

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


    @staticmethod
    def _infer_category_from_item_id(item_id: str) -> str:
        normalized = item_id.upper()
        category_markers = (
            ("holy_staff", "_2H_HOLYSTAFF"),
            ("fire_staff", "_2H_FIRESTAFF"),
            ("frost_staff", "_2H_FROSTSTAFF"),
            ("arcane_staff", "_2H_ARCANESTAFF"),
            ("cursed_staff", "_2H_CURSEDSTAFF"),
            ("nature_staff", "_2H_NATURESTAFF"),
            ("sword", "_2H_CLAYMORE"),
            ("sword", "_2H_DUALSWORD"),
            ("sword", "_2H_CLEAVER_HELL"),
            ("sword", "_MAIN_SWORD"),
        )
        for category, marker in category_markers:
            if marker in normalized:
                return category
        return "unknown"

    @staticmethod
    def _extract_category_marker(category: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(category or "").upper())

    @classmethod
    def item_id_matches_category_marker(cls, item_id: str, category: str) -> bool:
        marker = cls._extract_category_marker(category)
        if not marker:
            return False
        normalized_item_id = str(item_id or "").upper()
        if not normalized_item_id:
            return False
        return (
            f"_{marker}_" in normalized_item_id
            or normalized_item_id.endswith(f"_{marker}")
            or normalized_item_id.endswith(marker)
        )

    def _normalize_category(self, category: str, item_id: str) -> str:
        normalized = str(category or "").strip().lower()
        if normalized and normalized != "unknown":
            return normalized
        inferred = self._infer_category_from_item_id(item_id)
        return inferred

    def _normalize_item(self, row: dict[str, Any]) -> dict[str, Any]:
        raw_item_id = str(
            row.get("id")
            or row.get("item_id")
            or row.get("ItemTypeId")
            or row.get("UniqueName")
            or ""
        ).strip()
        parsed_enchant = self._to_int(row.get("enchant") or row.get("EnchantmentLevel") or row.get("enchantment") or 0)
        item_id, enchant = self.normalize_enchanted_item_id(raw_item_id, parsed_enchant)
        raw_name = (
            row.get("name")
            or row.get("localized_name")
            or row.get("item_name")
            or row.get("LocalizedName")
            or row.get("LocalizedNames")
            or item_id
        )
        name = str(raw_name).strip()
        if not name:
            name = item_id
        tier = self._to_int(row.get("tier") or row.get("Tier") or 0)
        category = self._normalize_category(str(row.get("category") or row.get("Category") or "unknown"), item_id)
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

    @staticmethod
    def split_enchanted_item_id(item_id: str) -> tuple[str, int]:
        raw = str(item_id or "").strip()
        if not raw:
            return "", 0
        if "@" in raw:
            base, _, suffix = raw.rpartition("@")
            try:
                enchant = int(suffix)
            except (TypeError, ValueError):
                return raw, 0
            return base or raw, max(0, enchant)
        return raw, 0

    @classmethod
    def normalize_enchanted_item_id(cls, item_id: str, enchantment_level: int = 0) -> tuple[str, int]:
        base_item_id, suffix_enchant = cls.split_enchanted_item_id(item_id)
        resolved_enchant = max(0, int(enchantment_level if enchantment_level is not None else suffix_enchant))
        if resolved_enchant <= 0:
            return base_item_id, 0
        return f"{base_item_id}@{resolved_enchant}", resolved_enchant

    async def resolve_item_id_for_enchantment(self, item_id: str, enchantment_level: int) -> str:
        normalized_base_item_id, _ = self.normalize_enchanted_item_id(item_id, 0)
        resolved_item_id, _ = self.normalize_enchanted_item_id(normalized_base_item_id, enchantment_level)
        return resolved_item_id

    def _parse_items_list_text(self, payload: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw_line in payload.splitlines():
            cleaned_line = ITEMS_LIST_LINE_PREFIX_PATTERN.sub("", raw_line)
            line = cleaned_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            if line.startswith("{") and line.endswith("}"):
                try:
                    parsed_json = json.loads(line)
                    if isinstance(parsed_json, dict):
                        rows.append(self._normalize_item(parsed_json))
                        continue
                except Exception:
                    pass

            match = ITEMS_LIST_TOKEN_PATTERN.search(line)
            if not match:
                logger.debug("Ignoring invalid items list line: %r", raw_line)
                continue

            item_id = match.group(1)
            _, enchant = self.split_enchanted_item_id(item_id)
            tier_match = re.match(r"^T(\d+)_", item_id)
            tier = self._to_int(tier_match.group(1), 0) if tier_match else 0

            name = item_id
            icon = self._item_icon(item_id)

            tail = line[match.end():].strip()
            if tail.startswith(":"):
                colon_name = tail[1:].strip().strip('"')
                if colon_name and not ITEMS_LIST_TOKEN_PATTERN.search(colon_name):
                    name = colon_name

            parts = [part.strip().strip('"') for part in re.split(r"[;\t,]", line) if part.strip()]
            for part in parts:
                if part == item_id:
                    continue
                if (part.startswith("http://") or part.startswith("https://")) and (".png" in part or ".webp" in part):
                    icon = part
                    continue
                if ITEMS_LIST_TOKEN_PATTERN.search(part):
                    continue
                if part.isdigit():
                    continue
                if part.startswith(":"):
                    part = part[1:].strip()
                if name == item_id and part:
                    name = part

            rows.append(
                {
                    "id": item_id,
                    "name": name,
                    "tier": tier,
                    "enchant": enchant,
                    "icon": icon,
                    "category": self._normalize_category("unknown", item_id),
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
                            or material.get("uniqueName")
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

        try:
            payload = response.json()
        except (JSONDecodeError, ValueError) as exc:
            body = (response.text or "").strip()
            if response.status_code == 404 or not body:
                raise AlbionProviderError("item_not_found", "Item introuvable") from exc
            raise AlbionProviderError("provider_invalid_payload", "Payload détail item invalide") from exc
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        raise AlbionProviderError("provider_invalid_payload", "Payload détail item invalide")

    def _normalize_item_detail(self, item_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        item_row = payload.get("item") if isinstance(payload.get("item"), dict) else payload
        crafting_requirements = payload.get("craftingRequirements")
        if isinstance(crafting_requirements, dict):
            recipe = self._normalize_recipe({"materials": crafting_requirements.get("craftResourceList", [])})
        else:
            recipe_row = payload.get("recipe") or payload.get("materials") or payload.get("CraftingRequirements")
            if isinstance(recipe_row, list):
                recipe = self._normalize_recipe({"materials": recipe_row})
            elif isinstance(recipe_row, dict):
                recipe = self._normalize_recipe(recipe_row)
            else:
                recipe = self._normalize_recipe(payload)

        localized_names = payload.get("localizedNames") if isinstance(payload.get("localizedNames"), dict) else {}
        localized_name = (
            localized_names.get("FR-FR")
            or localized_names.get("EN-US")
            or localized_names.get("DE-DE")
            or ""
        )
        normalized_row = {
            **item_row,
            "id": payload.get("uniqueName") or item_id,
            "name": item_row.get("name") or localized_name,
            "tier": payload.get("tier") if payload.get("tier") is not None else item_row.get("tier"),
            "category": payload.get("categoryId") or item_row.get("category"),
            "icon": self._item_icon(str(payload.get("uniqueName") or item_id).strip()),
            "craftable": payload.get("craftingRequirements") is not None or item_row.get("craftable"),
        }
        item = self._normalize_item(normalized_row)
        return item, recipe


    @classmethod
    def _extract_enchantment_focus_costs(cls, payload: dict[str, Any], item_id: str) -> dict[int, int]:
        enchantment_focus_costs: dict[int, int] = {}
        _, requested_enchant = cls.split_enchanted_item_id(item_id)

        crafting_requirements = payload.get("craftingRequirements")
        if isinstance(crafting_requirements, dict):
            try:
                base_focus = int(crafting_requirements.get("craftingFocus"))
            except (TypeError, ValueError):
                base_focus = 0
            if base_focus > 0:
                enchantment_focus_costs[0] = base_focus

        enchantments_payload = payload.get("enchantments")
        enchantments_rows = enchantments_payload.get("enchantments") if isinstance(enchantments_payload, dict) else []
        if isinstance(enchantments_rows, list):
            for row in enchantments_rows:
                if not isinstance(row, dict):
                    continue
                try:
                    enchantment_level = int(row.get("enchantmentLevel"))
                except (TypeError, ValueError):
                    continue
                req = row.get("craftingRequirements") if isinstance(row.get("craftingRequirements"), dict) else {}
                try:
                    focus_cost = int(req.get("craftingFocus"))
                except (TypeError, ValueError):
                    focus_cost = 0
                if focus_cost > 0 and enchantment_level >= 0:
                    enchantment_focus_costs[enchantment_level] = focus_cost

        if requested_enchant > 0 and requested_enchant in enchantment_focus_costs:
            return {requested_enchant: enchantment_focus_costs[requested_enchant], **enchantment_focus_costs}
        return enchantment_focus_costs

    @classmethod
    def _extract_base_focus_cost(cls, payload: dict[str, Any], item_id: str) -> int | None:
        enchantment_focus_costs = cls._extract_enchantment_focus_costs(payload, item_id)
        _, requested_enchant = cls.split_enchanted_item_id(item_id)
        if requested_enchant in enchantment_focus_costs:
            return enchantment_focus_costs[requested_enchant]
        if 0 in enchantment_focus_costs:
            return enchantment_focus_costs[0]
        candidates = (
            payload.get("base_focus_cost"),
            payload.get("BaseFocusCost"),
            payload.get("focus_cost"),
            payload.get("FocusCost"),
            payload.get("focus"),
            payload.get("item", {}).get("base_focus_cost") if isinstance(payload.get("item"), dict) else None,
            payload.get("item", {}).get("FocusCost") if isinstance(payload.get("item"), dict) else None,
        )
        for value in candidates:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return None

    def _resolve_focus_cost_metadata(self, item: dict[str, Any]) -> tuple[int | None, str]:
        if self.store is None:
            return None, "unavailable"
        row = self.store.craft_get_focus_cost(str(item.get("id", "")))
        if row is None:
            return None, "missing"
        try:
            return int(row.get("base_focus_cost")), str(row.get("source") or "manual")
        except (TypeError, ValueError):
            return None, "invalid"

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
            attempt_at = int(time.time())

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
            source = self.items_list_url or self.provider_url or "unknown"
            checksum = hashlib.sha256(json.dumps(merged_items, sort_keys=True).encode("utf-8")).hexdigest()
            if not merged_items:
                self._load_items_from_db()
                if self._items_cache:
                    if errors:
                        self._persist_sync_failure(source=source, checksum=checksum, error_message=errors[-1].message)
                    return
                if errors:
                    self._persist_sync_failure(source=source, checksum=checksum, error_message=errors[-1].message)
                    raise errors[-1]
                raise AlbionProviderError("provider_not_configured", "Aucune source Albion configurée")

            self._items_cache = merged_items
            self._recipes_cache = provider_recipes or self._recipes_cache
            self._last_refresh_ts = time.time()
            self._last_sync_error = ""
            self._save_snapshot()

            if self.store is not None:
                diff = self.store.craft_upsert_items_index(items=merged_items, source=source, checksum=checksum, synced_at=attempt_at)
                self.store.craft_upsert_sync_state(
                    source=source,
                    checksum=checksum,
                    status="ok",
                    items_count=diff["items_count"],
                    inserted_count=diff["inserted_count"],
                    updated_count=diff["updated_count"],
                    deactivated_count=diff["deactivated_count"],
                    last_attempt_at=attempt_at,
                    last_success_at=attempt_at,
                    last_error="",
                )

    async def invalidate(self) -> None:
        async with self._lock:
            self._last_refresh_ts = 0.0

    async def get_catalog_snapshot(self) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        await self.refresh(force=False)
        if self.store is not None:
            rows = self.store.craft_list_all_items(include_inactive=False)
            if rows:
                items = [
                    {
                        "id": str(row.get("item_id", "")),
                        "name": str(row.get("name", "")),
                        "tier": self._to_int(row.get("tier"), 0),
                        "enchant": self._to_int(row.get("enchant"), 0),
                        "icon": str(row.get("icon", "")),
                        "category": str(row.get("category", "unknown")),
                        "craftable": self._to_bool(row.get("craftable"), default=False),
                    }
                    for row in rows
                ]
                self._items_cache = items
        return list(self._items_cache), dict(self._recipes_cache)

    async def search_items(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        await self.refresh(force=False)
        if self.store is not None:
            rows = self.store.craft_search_items(query=query, limit=limit, include_inactive=False)
            if rows:
                return [
                    {
                        "id": str(row.get("item_id", "")),
                        "name": str(row.get("name", "")),
                        "tier": self._to_int(row.get("tier"), 0),
                        "enchant": self._to_int(row.get("enchant"), 0),
                        "icon": str(row.get("icon", "")),
                        "category": str(row.get("category", "unknown")),
                        "craftable": self._to_bool(row.get("craftable"), default=False),
                    }
                    for row in rows
                ]
        q = query.strip().lower()
        rows = self._items_cache
        if q:
            rows = [item for item in rows if q in item["name"].lower() or q in item["id"].lower()]
        return rows[: max(1, min(limit, 50))]

    async def get_item_detail(self, item_id: str) -> dict[str, Any]:
        await self.refresh(force=False)
        key = item_id.strip()
        item = next((row for row in self._items_cache if row["id"] == key), None)
        if item is None and self.store is not None:
            stored_item = self.store.craft_get_item(key)
            if stored_item is not None and bool(stored_item.get("active", True)):
                item = {"id": str(stored_item.get("item_id", "")), "name": str(stored_item.get("name", "")), "tier": self._to_int(stored_item.get("tier"), 0), "enchant": self._to_int(stored_item.get("enchant"), 0), "icon": str(stored_item.get("icon", "")), "category": str(stored_item.get("category", "unknown")), "craftable": self._to_bool(stored_item.get("craftable"), default=False)}
        if item is None:
            raise AlbionProviderError("item_not_found", "Item introuvable")

        recipe = self._recipes_cache.get(key, [])
        enchantment_focus_costs: dict[int, int] = {}
        if not recipe:
            detail_payload = await self._fetch_item_detail(key)
            if detail_payload is not None:
                normalized_item, normalized_recipe = self._normalize_item_detail(key, detail_payload)
                item = normalized_item
                recipe = normalized_recipe
                self._recipes_cache[key] = normalized_recipe
                self._items_cache = self._merge_items([normalized_item], self._items_cache)
                self._save_snapshot()
                enchantment_focus_costs = self._extract_enchantment_focus_costs(detail_payload, key)
                extracted_focus_cost = self._extract_base_focus_cost(detail_payload, key)
                if extracted_focus_cost is not None and self.store is not None:
                    self.store.craft_upsert_focus_cost(
                        item_id=key,
                        base_focus_cost=extracted_focus_cost,
                        tier=self._to_int(item.get("tier"), 0),
                        enchant=self._to_int(item.get("enchant"), 0),
                        source="albion_provider",
                    )

        base_focus_cost, base_focus_cost_source = self._resolve_focus_cost_metadata(item)

        return {
            "item": item,
            "recipe": recipe,
            "metadata": {
                "source": "albion_provider",
                "snapshot_age_seconds": max(0, int(time.time() - self._last_refresh_ts)),
                "has_fallback_snapshot": self.snapshot_path.exists(),
                "last_sync_error": self._last_sync_error,
                "sync_status": self.get_sync_status(),
                "base_focus_cost": base_focus_cost,
                "base_focus_cost_source": base_focus_cost_source,
                "base_focus_cost_by_enchant": enchantment_focus_costs,
            },
        }
