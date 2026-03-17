from __future__ import annotations

import io
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from albionbot.storage.store import Store

from .gameinfo_client import GAMEINFO_BASE_URLS

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None


@dataclass
class KillboardTracker:
    tracker_id: str
    guild_id: int
    albion_server: str
    kind: str
    target_id: str
    target_name: str
    post_channel_id: int | None
    enabled: bool


class GameInfoKillboardProvider:
    def __init__(self, timeout_s: float = 8.0) -> None:
        self.timeout_s = timeout_s

    async def fetch_events_for_tracker(self, tracker: KillboardTracker, *, limit: int = 10) -> list[dict[str, Any]]:
        base = GAMEINFO_BASE_URLS.get(self._server_to_host(tracker.albion_server), GAMEINFO_BASE_URLS["gameinfo"])
        path = (
            f"/api/gameinfo/guilds/{tracker.target_id}/kills?limit={limit}"
            if tracker.kind == "guild"
            else f"/api/gameinfo/players/{tracker.target_id}/kills?limit={limit}"
        )
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.get(f"{base}{path}")
            resp.raise_for_status()
            payload = resp.json()
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _server_to_host(server: str) -> str:
        server = (server or "europe").lower()
        if server.startswith("amer"):
            return "gameinfo-ams"
        if server.startswith("asia"):
            return "gameinfo-sgp"
        return "gameinfo"


class KillboardRenderService:
    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or (Path(__file__).resolve().parent / "data" / "killboard_images")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render_event_image(self, event: dict[str, Any]) -> str:
        event_id = int(event.get("EventId") or event.get("event_id") or 0)
        out = self.output_dir / f"kill_{event_id}_{uuid.uuid4().hex[:8]}.png"
        if Image is None or ImageDraw is None:
            out.write_bytes(str(event).encode("utf-8"))
            return str(out)

        image = Image.new("RGB", (1200, 630), color=(20, 24, 34))
        draw = ImageDraw.Draw(image)
        killer = ((event.get("Killer") or {}).get("Name") or event.get("killer_name") or "Unknown")
        victim = ((event.get("Victim") or {}).get("Name") or event.get("victim_name") or "Unknown")
        fame = int(event.get("TotalVictimKillFame") or event.get("kill_fame") or 0)
        draw.text((40, 40), f"KILLBOARD EVENT #{event_id}", fill=(240, 240, 255))
        draw.text((40, 120), f"{killer}  VS  {victim}", fill=(255, 220, 120))
        draw.text((40, 180), f"Kill Fame: {fame:,}", fill=(200, 220, 255))
        draw.text((40, 240), f"Assists: {len(event.get('Participants', []) or [])}", fill=(200, 220, 255))
        image.save(out, format="PNG", optimize=True)
        return str(out)


class KillboardService:
    def __init__(self, store: Store, provider: GameInfoKillboardProvider | None = None, renderer: KillboardRenderService | None = None) -> None:
        self.store = store
        self.provider = provider or GameInfoKillboardProvider()
        self.renderer = renderer or KillboardRenderService()

    def list_trackers(self, guild_id: int) -> list[dict[str, Any]]:
        if not self.store.bank_db:
            return []
        return self.store.bank_db.list_killboard_trackers(guild_id)

    def add_tracker(
        self,
        guild_id: int,
        created_by: int,
        albion_server: str,
        kind: str,
        target_id: str,
        target_name: str,
        post_channel_id: int | None,
    ) -> dict[str, Any]:
        if not self.store.bank_db:
            raise RuntimeError("Database unavailable")
        tracker = {
            "tracker_id": str(uuid.uuid4()),
            "guild_id": int(guild_id),
            "albion_server": albion_server,
            "kind": kind,
            "target_id": target_id,
            "target_name": target_name,
            "post_channel_id": post_channel_id,
            "enabled": True,
            "created_by": int(created_by),
        }
        self.store.bank_db.upsert_killboard_tracker(tracker)
        return tracker

    def delete_tracker(self, tracker_id: str) -> None:
        if not self.store.bank_db:
            raise RuntimeError("Database unavailable")
        self.store.bank_db.delete_killboard_tracker(tracker_id)

    async def poll_once(self) -> int:
        if not self.store.bank_db:
            return 0
        posted = 0
        for tracker_row in self.store.bank_db.list_all_killboard_trackers():
                if not bool(int(tracker_row.get("enabled", 1))):
                    continue
                tracker = KillboardTracker(
                    tracker_id=str(tracker_row["tracker_id"]),
                    guild_id=int(tracker_row["guild_id"]),
                    albion_server=str(tracker_row["albion_server"]),
                    kind=str(tracker_row["kind"]),
                    target_id=str(tracker_row["target_id"]),
                    target_name=str(tracker_row.get("target_name") or ""),
                    post_channel_id=int(tracker_row["post_channel_id"]) if tracker_row.get("post_channel_id") else None,
                    enabled=bool(int(tracker_row.get("enabled", 1))),
                )
                events = await self.provider.fetch_events_for_tracker(tracker, limit=8)
                for event in events:
                    event_id = int(event.get("EventId") or 0)
                    if event_id <= 0:
                        continue
                    image_path = self.renderer.render_event_image(event)
                    normalized = {
                        "albion_server": tracker.albion_server,
                        "event_id": event_id,
                        "occurred_at": int((event.get("TimeStamp") or int(time.time() * 1000)) / 1000),
                        "killer_id": str((event.get("Killer") or {}).get("Id") or ""),
                        "killer_name": str((event.get("Killer") or {}).get("Name") or ""),
                        "killer_guild_id": str((event.get("Killer") or {}).get("GuildId") or ""),
                        "victim_id": str((event.get("Victim") or {}).get("Id") or ""),
                        "victim_name": str((event.get("Victim") or {}).get("Name") or ""),
                        "victim_guild_id": str((event.get("Victim") or {}).get("GuildId") or ""),
                        "killer_average_ip": (event.get("Killer") or {}).get("AverageItemPower"),
                        "victim_average_ip": (event.get("Victim") or {}).get("AverageItemPower"),
                        "assist_count": len(event.get("Participants", []) or []),
                        "kill_fame": int(event.get("TotalVictimKillFame") or 0),
                        "estimated_value": None,
                        "payload": event,
                        "image_path": image_path,
                    }
                    self.store.bank_db.upsert_killboard_event(normalized)
                    if tracker.post_channel_id:
                        self.store.bank_db.mark_killboard_posted(tracker.albion_server, event_id, tracker.guild_id, tracker.post_channel_id, None)
                        posted += 1
        return posted

    def list_events(self, guild_id: int, limit: int = 50) -> list[dict[str, Any]]:
        if not self.store.bank_db:
            return []
        return self.store.bank_db.list_killboard_events(guild_id, limit=limit)
