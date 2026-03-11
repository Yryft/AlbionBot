from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

import httpx


GAMEINFO_BASE_URLS: dict[str, str] = {
    "gameinfo-ams": "https://gameinfo-ams.albiononline.com",
    "gameinfo": "https://gameinfo.albiononline.com",
    "gameinfo-sgp": "https://gameinfo-sgp.albiononline.com",
}


class GameInfoError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class GameInfoNotFoundError(GameInfoError):
    pass


class GameInfoRateLimitedError(GameInfoError):
    pass


class GameInfoBlockedError(GameInfoError):
    pass


class GameInfoInvalidJsonError(GameInfoError):
    pass


@dataclass
class CacheEntry:
    etag: str | None = None
    last_modified: str | None = None
    payload: Any = None


class GameInfoClient:
    def __init__(
        self,
        base_url: str = "gameinfo",
        timeout_s: float = 8.0,
        max_retries: int = 3,
        max_concurrency: int = 8,
    ) -> None:
        self.base_url = GAMEINFO_BASE_URLS.get(base_url, base_url).rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._cache: dict[str, CacheEntry] = {}
        self._sem = asyncio.Semaphore(max(1, max_concurrency))

    async def get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}
        cached = self._cache.get(url)
        if cached:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified

        last_exc: Exception | None = None
        async with self._sem:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                for attempt in range(self.max_retries + 1):
                    try:
                        response = await client.get(url, headers=headers)
                    except httpx.TimeoutException as exc:
                        last_exc = exc
                        if attempt >= self.max_retries:
                            raise GameInfoError("timeout", "GameInfo timeout") from exc
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    except httpx.TransportError as exc:
                        last_exc = exc
                        if attempt >= self.max_retries:
                            raise GameInfoError("transport_error", "Erreur transport GameInfo") from exc
                        await asyncio.sleep(self._backoff(attempt))
                        continue

                    if response.status_code == 304 and cached is not None:
                        return cached.payload
                    if response.status_code == 404:
                        raise GameInfoNotFoundError("not_found", "Item introuvable", status_code=404)
                    if response.status_code == 429:
                        if attempt >= self.max_retries:
                            raise GameInfoRateLimitedError("rate_limited", "Rate limited", status_code=429)
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    if response.status_code in {502, 503, 504}:
                        if attempt >= self.max_retries:
                            raise GameInfoError("upstream_unavailable", "Upstream indisponible", status_code=response.status_code)
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    if response.status_code >= 500 and "cloudflare" in (response.text or "").lower():
                        raise GameInfoBlockedError("upstream_blocked", "Requête bloquée par Cloudflare", status_code=response.status_code)
                    response.raise_for_status()

                    try:
                        payload = response.json()
                    except (JSONDecodeError, ValueError) as exc:
                        raise GameInfoInvalidJsonError("invalid_json", "JSON invalide", status_code=response.status_code) from exc

                    self._cache[url] = CacheEntry(
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        payload=payload,
                    )
                    return payload
        if last_exc:
            raise GameInfoError("transport_error", "Erreur transport GameInfo") from last_exc
        raise GameInfoError("unknown", "Erreur inconnue GameInfo")

    @staticmethod
    def _backoff(attempt: int) -> float:
        base = 0.25 * (2**attempt)
        return base + random.uniform(0, 0.15)
