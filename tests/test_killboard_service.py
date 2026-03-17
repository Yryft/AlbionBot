from __future__ import annotations

from pathlib import Path

import asyncio

from albionbot.storage.store import Store
from web.backend.killboard import GameInfoKillboardProvider, KillboardService


class FakeProvider(GameInfoKillboardProvider):
    async def fetch_events_for_tracker(self, tracker, *, limit: int = 10):
        return [
            {
                "EventId": 999001,
                "TimeStamp": 1710000000000,
                "TotalVictimKillFame": 321000,
                "Killer": {"Id": "p1", "Name": "Killer", "AverageItemPower": 1312.4},
                "Victim": {"Id": "p2", "Name": "Victim", "AverageItemPower": 1244.8},
                "Participants": [{"Id": "p3"}, {"Id": "p4"}],
            }
        ]


def test_killboard_tracker_poll_and_event_storage(tmp_path: Path):
    db_path = tmp_path / "bank.sqlite3"
    store = Store(path=str(tmp_path / "state.json"), bank_sqlite_path=str(db_path))
    service = KillboardService(store=store, provider=FakeProvider())

    tracker = service.add_tracker(
        guild_id=123,
        created_by=42,
        albion_server="europe",
        kind="player",
        target_id="player-42",
        target_name="Player42",
        post_channel_id=555,
    )
    assert tracker["kind"] == "player"

    posted = asyncio.run(service.poll_once())
    assert posted >= 1

    events = service.list_events(guild_id=123)
    assert len(events) >= 1
    assert int(events[0]["event_id"]) == 999001
