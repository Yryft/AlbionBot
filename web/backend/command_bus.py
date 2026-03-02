from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Generic, Optional, Protocol, TypeVar

from albionbot.modules import bank as bank_module
from albionbot.modules import raids as raids_module
from albionbot.modules import tickets as tickets_module

log = logging.getLogger(__name__)

TResult = TypeVar("TResult")


class DomainError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ValidationError(DomainError):
    pass


class RateLimitError(DomainError):
    pass


@dataclass(frozen=True)
class CommandContext:
    guild_id: int
    user_id: int
    request_id: str


class Command(Protocol, Generic[TResult]):
    context: CommandContext

    def validate(self) -> None:
        ...


class CommandHandler(Protocol, Generic[TResult]):
    def handle(self, command: Command[TResult]) -> TResult:
        ...


class RateLimiter:
    def __init__(self, max_requests: int = 5, window_seconds: int = 30):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: Dict[tuple[int, int], list[int]] = {}
        self._lock = Lock()

    def check(self, user_id: int, guild_id: int) -> None:
        now = int(time.time())
        key = (user_id, guild_id)
        with self._lock:
            values = [ts for ts in self._events.get(key, []) if now - ts < self.window_seconds]
            if len(values) >= self.max_requests:
                raise RateLimitError(
                    code="rate_limited",
                    message="Trop de commandes sur la fenêtre courante.",
                    details={"retry_after_seconds": self.window_seconds},
                )
            values.append(now)
            self._events[key] = values


class AuditLogger:
    def __init__(self, path: str = "data/dashboard_audit.log"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def write(self, entry: Dict[str, Any]) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


class CommandBus:
    def __init__(self, rate_limiter: RateLimiter, audit_logger: AuditLogger):
        self.rate_limiter = rate_limiter
        self.audit_logger = audit_logger
        self._idempotent_results: Dict[str, Any] = {}
        self._lock = Lock()

    def dispatch(self, command: Command[TResult], handler: CommandHandler[TResult], action: str) -> TResult:
        started_at = int(time.time())
        command.validate()
        self.rate_limiter.check(user_id=command.context.user_id, guild_id=command.context.guild_id)

        with self._lock:
            if command.context.request_id in self._idempotent_results:
                result = self._idempotent_results[command.context.request_id]
                self._audit(command, action, started_at, "idempotent_hit", True)
                return result

        try:
            result = handler.handle(command)
            with self._lock:
                self._idempotent_results[command.context.request_id] = result
            self._audit(command, action, started_at, "ok", True)
            return result
        except DomainError:
            self._audit(command, action, started_at, "domain_error", False)
            raise
        except Exception as exc:  # pragma: no cover
            log.exception("command_bus_unhandled_exception action=%s", action)
            self._audit(command, action, started_at, "internal_error", False)
            raise DomainError(code="internal_error", message="Erreur interne.") from exc

    def _audit(self, command: Command[TResult], action: str, started_at: int, result: str, success: bool) -> None:
        self.audit_logger.write(
            {
                "timestamp": int(time.time()),
                "started_at": started_at,
                "user_id": command.context.user_id,
                "guild_id": command.context.guild_id,
                "request_id": command.context.request_id,
                "action": action,
                "result": result,
                "success": success,
            }
        )


@dataclass(frozen=True)
class OpenRaidFromTemplate:
    context: CommandContext
    template_id: str
    title: str
    description: str
    extra_message: str
    start_at: int
    prep_minutes: int
    cleanup_minutes: int
    channel_id: int
    voice_channel_id: Optional[int] = None

    def validate(self) -> None:
        if self.context.guild_id <= 0:
            raise ValidationError(code="invalid_guild_id", message="guild_id invalide")
        if not self.template_id.strip():
            raise ValidationError(code="invalid_template_id", message="template_id requis")
        if self.start_at <= int(time.time()):
            raise ValidationError(code="invalid_start_at", message="start_at doit être dans le futur")
        if not (0 <= self.prep_minutes <= 240):
            raise ValidationError(code="invalid_prep_minutes", message="prep_minutes invalide")
        if not (0 <= self.cleanup_minutes <= 240):
            raise ValidationError(code="invalid_cleanup_minutes", message="cleanup_minutes invalide")
        if not self.title.strip():
            raise ValidationError(code="invalid_title", message="title requis")
        if self.channel_id <= 0:
            raise ValidationError(code="invalid_channel_id", message="channel_id requis")
        if self.voice_channel_id is not None and self.voice_channel_id <= 0:
            raise ValidationError(code="invalid_voice_channel_id", message="voice_channel_id invalide")


@dataclass(frozen=True)
class StartCompWizardFlow:
    context: CommandContext
    template_id: str
    description: str
    content_type: str
    raid_required_role_ids: list[int]
    spec: str

    def validate(self) -> None:
        if self.context.guild_id <= 0:
            raise ValidationError(code="invalid_guild_id", message="guild_id invalide")
        if not self.template_id.strip():
            raise ValidationError(code="invalid_template_id", message="template_id requis")
        if self.content_type not in {"ava_raid", "pvp", "pve"}:
            raise ValidationError(code="invalid_content_type", message="content_type invalide")
        if not self.spec.strip():
            raise ValidationError(code="invalid_spec", message="spec requis")


# Explicit imports to signal command bus coupling with existing module boundaries.
RAIDS_MODULE_NAME = raids_module.__name__
TICKETS_MODULE_NAME = tickets_module.__name__
BANK_MODULE_NAME = bank_module.__name__
