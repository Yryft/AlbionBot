from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass

from web.backend.command_bus import (
    AuditLogger,
    CommandBus,
    CommandContext,
    DomainError,
    OpenRaidFromTemplate,
    RateLimiter,
)


@dataclass
class DummyHandler:
    calls: int = 0

    def handle(self, command):
        self.calls += 1
        return {"request_id": command.context.request_id}


@dataclass
class ErrorHandler:
    def handle(self, command):
        raise DomainError(code="boom", message="boom")


def test_command_bus_is_idempotent_and_audited():
    with tempfile.TemporaryDirectory() as tmp:
        bus = CommandBus(RateLimiter(max_requests=10, window_seconds=60), AuditLogger(f"{tmp}/audit.log"))
        cmd = OpenRaidFromTemplate(
            context=CommandContext(guild_id=1, user_id=10, request_id="req-1"),
            template_id="tpl",
            title="Raid",
            description="",
            extra_message="",
            start_at=int(time.time()) + 3600,
            prep_minutes=10,
            cleanup_minutes=10,
        )
        handler = DummyHandler()

        first = bus.dispatch(cmd, handler, action="open")
        second = bus.dispatch(cmd, handler, action="open")

        assert first == second
        assert handler.calls == 1


def test_rate_limit_is_enforced():
    with tempfile.TemporaryDirectory() as tmp:
        bus = CommandBus(RateLimiter(max_requests=1, window_seconds=60), AuditLogger(f"{tmp}/audit.log"))
        handler = DummyHandler()
        cmd1 = OpenRaidFromTemplate(
            context=CommandContext(guild_id=1, user_id=10, request_id="req-1"),
            template_id="tpl",
            title="Raid",
            description="",
            extra_message="",
            start_at=int(time.time()) + 3600,
            prep_minutes=10,
            cleanup_minutes=10,
        )
        cmd2 = OpenRaidFromTemplate(
            context=CommandContext(guild_id=1, user_id=10, request_id="req-2"),
            template_id="tpl",
            title="Raid",
            description="",
            extra_message="",
            start_at=int(time.time()) + 3600,
            prep_minutes=10,
            cleanup_minutes=10,
        )

        bus.dispatch(cmd1, handler, action="open")

        try:
            bus.dispatch(cmd2, handler, action="open")
            assert False, "expected rate limit"
        except DomainError as exc:
            assert exc.code == "rate_limited"


def test_validation_failure():
    with tempfile.TemporaryDirectory() as tmp:
        bus = CommandBus(RateLimiter(max_requests=10, window_seconds=60), AuditLogger(f"{tmp}/audit.log"))
        cmd = OpenRaidFromTemplate(
            context=CommandContext(guild_id=0, user_id=10, request_id="req-1"),
            template_id="tpl",
            title="Raid",
            description="",
            extra_message="",
            start_at=int(time.time()) + 3600,
            prep_minutes=10,
            cleanup_minutes=10,
        )
        try:
            bus.dispatch(cmd, ErrorHandler(), action="open")
            assert False, "expected validation"
        except DomainError as exc:
            assert exc.code == "invalid_guild_id"
