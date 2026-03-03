from __future__ import annotations

import asyncio
import time
from types import MethodType

import albionbot.modules.raids as raids_module
from albionbot.modules.raids import RaidModule
from albionbot.storage.store import CompRole, CompTemplate, RaidCommand, RaidEvent, Store
from web.backend.command_bus import CommandContext, OpenRaidFromTemplate
from web.backend.services import DashboardService, OpenRaidFromTemplateHandler


def _build_store(tmp_path) -> Store:
    store = Store(path=str(tmp_path / "state.json"), bank_database_url="", bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    store.templates["zvz"] = CompTemplate(
        name="zvz",
        description="template",
        created_by=1,
        roles=[CompRole(key="dps", label="DPS", slots=5)],
    )
    return store


def test_open_raid_creates_pending_command_and_exposes_status(tmp_path):
    store = _build_store(tmp_path)
    service = DashboardService(store)
    handler = OpenRaidFromTemplateHandler(service)
    command = OpenRaidFromTemplate(
        context=CommandContext(guild_id=1, user_id=42, request_id="req-1"),
        template_id="zvz",
        title="Prime",
        description="desc",
        extra_message="",
        start_at=int(time.time()) + 3600,
        prep_minutes=10,
        cleanup_minutes=30,
        channel_id=123,
        voice_channel_id=None,
    )

    raid = handler.handle(command)

    command_id = f"open_raid_from_template:{raid.raid_id}"
    persisted = store.raid_commands.get(command_id)
    assert persisted is not None
    assert persisted.status == "pending"
    assert raid.publish_status == "pending"


def test_queue_retry_backoff_and_idempotence(tmp_path):
    store = _build_store(tmp_path)
    raid = RaidEvent(
        raid_id="raid-1",
        template_name="zvz",
        title="Prime",
        description="",
        extra_message="",
        start_at=int(time.time()) + 3600,
        created_by=1,
        channel_id=123,
    )
    store.raids[raid.raid_id] = raid
    store.raid_commands["open_raid_from_template:raid-1"] = RaidCommand(
        command_id="open_raid_from_template:raid-1",
        command_type="open_raid_from_template",
        raid_id=raid.raid_id,
        status="pending",
        attempts=0,
        next_attempt_at=0,
    )

    module = RaidModule.__new__(RaidModule)
    module.store = store

    calls = {"n": 0}

    async def fake_publish(self, raid_id: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "discord timeout"
        store.raids[raid_id].message_id = 999
        return True, ""

    module.publish_raid_if_needed = MethodType(fake_publish, module)

    asyncio.run(module._consume_raid_command_queue())
    cmd = store.raid_commands["open_raid_from_template:raid-1"]
    assert cmd.status == "failed"
    assert cmd.attempts == 1
    assert cmd.next_attempt_at > 0

    # force retry window elapsed
    cmd.next_attempt_at = 0
    asyncio.run(module._consume_raid_command_queue())
    assert calls["n"] == 2
    assert cmd.status == "delivered"
    assert cmd.attempts == 2

    # delivered command should not be retried
    asyncio.run(module._consume_raid_command_queue())
    assert calls["n"] == 2


def test_publish_queue_adds_ava_raid_leader_signup(tmp_path, monkeypatch):
    store = Store(path=str(tmp_path / "state.json"), bank_database_url="", bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    store.templates["ava"] = CompTemplate(
        name="ava",
        description="template",
        created_by=1,
        content_type="ava_raid",
        roles=[CompRole(key="raid_leader", label="Raid Leader", slots=1)],
    )
    raid = RaidEvent(
        raid_id="raid-ava",
        template_name="ava",
        title="AVA",
        description="",
        extra_message="",
        start_at=int(time.time()) + 3600,
        created_by=42,
        channel_id=123,
    )
    store.raids[raid.raid_id] = raid

    class FakeThread:
        id = 456

        async def send(self, *_args, **_kwargs):
            return None

    class FakeMessage:
        id = 789

        def __init__(self, channel_id: int):
            self.channel = type("Chan", (), {"id": channel_id})()

        async def create_thread(self, **_kwargs):
            return FakeThread()

    class FakeTextChannel:
        def __init__(self):
            self.guild = object()
            self.id = 123

        async def send(self, **_kwargs):
            return FakeMessage(self.id)

    monkeypatch.setattr(raids_module.nextcord, "TextChannel", FakeTextChannel)
    monkeypatch.setattr(raids_module.nextcord, "Thread", FakeThread)

    class FakeBot:
        async def fetch_channel(self, _channel_id: int):
            return FakeTextChannel()

        def add_view(self, *_args, **_kwargs):
            return None

    module = RaidModule.__new__(RaidModule)
    module.store = store
    module.bot = FakeBot()
    module.build_view = lambda *_args, **_kwargs: object()

    async def _run():
        ok, err = await module.publish_raid_if_needed("raid-ava")
        assert ok is True
        assert err == ""

    asyncio.run(_run())
    assert raid.signups[42].role_key == "raid_leader"
    assert raid.signups[42].status == "main"
