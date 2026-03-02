from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import HTTPException, Request

from albionbot.config import Config, load_config
from albionbot.storage.store import Store
from albionbot.utils.permissions import (
    PERM_RAID_MANAGER,
    PERM_TICKET_MANAGER,
    has_logical_permission,
)

from .auth import DiscordOAuthService, SessionData, require_session

logger = logging.getLogger(__name__)

PERMISSION_BY_ACTION: Dict[str, str] = {
    "tickets_list": PERM_TICKET_MANAGER,
    "tickets_read": PERM_TICKET_MANAGER,
    "raid_list": PERM_RAID_MANAGER,
    "raid_templates_list": PERM_RAID_MANAGER,
    "raid_open": PERM_RAID_MANAGER,
    "comp_wizard": PERM_RAID_MANAGER,
}

DISCORD_PERM_ADMINISTRATOR = 0x00000008
DISCORD_PERM_MANAGE_GUILD = 0x00000020


@dataclass
class AuthorizationContext:
    session: SessionData
    guild_id: int
    user_id: int
    permission_key: str


@dataclass
class GuildMemberContext:
    session: SessionData
    guild_id: int
    user_id: int
    member_role_ids: List[int]
    is_owner: bool


class DashboardAuthorizationService:
    def __init__(self, store: Store, oauth_service: DiscordOAuthService, cfg: Optional[Config] = None):
        self.store = store
        self.oauth_service = oauth_service
        self.cfg = cfg or load_config()


    def ensure_guild_member(self, request: Request, guild_id: Optional[int] = None) -> GuildMemberContext:
        session = require_session(request, self.oauth_service)
        resolved_guild_id = self._resolve_guild_id(session, guild_id)
        user_id = int(session.user.get("id", "0") or "0")
        user_guild = self._find_user_guild(session, resolved_guild_id)
        if user_guild is None:
            raise HTTPException(status_code=403, detail="Utilisateur non membre de la guild")
        if resolved_guild_id not in self.store.guild_permissions and resolved_guild_id not in self.store.ticket_configs:
            raise HTTPException(status_code=403, detail="Guild non gérée par le bot")
        is_owner = bool(user_guild.get("owner", False))
        member_role_ids: List[int] = []
        try:
            member = self.oauth_service.fetch_guild_member(session.access_token, resolved_guild_id)
            member_role_ids = [int(rid) for rid in member.get("roles", [])]
        except HTTPException:
            if not is_owner:
                raise
        return GuildMemberContext(
            session=session,
            guild_id=resolved_guild_id,
            user_id=user_id,
            member_role_ids=member_role_ids,
            is_owner=is_owner,
        )

    def ensure_action_allowed(self, request: Request, action: str, guild_id: Optional[int] = None) -> AuthorizationContext:
        session = require_session(request, self.oauth_service)
        resolved_guild_id = self._resolve_guild_id(session, guild_id)
        permission_key = PERMISSION_BY_ACTION.get(action)
        if permission_key is None:
            raise HTTPException(status_code=500, detail=f"Action inconnue: {action}")

        user_id = int(session.user.get("id", "0") or "0")
        user_guild = self._find_user_guild(session, resolved_guild_id)
        if user_guild is None:
            self._log_decision(False, action, resolved_guild_id, user_id, permission_key, "not_in_guild")
            raise HTTPException(status_code=403, detail="Utilisateur non membre de la guild")

        if resolved_guild_id not in self.store.guild_permissions and resolved_guild_id not in self.store.ticket_configs:
            self._log_decision(False, action, resolved_guild_id, user_id, permission_key, "guild_not_managed")
            raise HTTPException(status_code=403, detail="Guild non gérée par le bot")

        member = self.oauth_service.fetch_guild_member(session.access_token, resolved_guild_id)
        member_role_ids = [int(rid) for rid in member.get("roles", [])]
        permission_bits = int(member.get("permissions", user_guild.get("permissions", "0")) or "0")
        is_admin = bool(permission_bits & DISCORD_PERM_ADMINISTRATOR) or bool(user_guild.get("owner", False))
        can_manage_guild = bool(permission_bits & DISCORD_PERM_MANAGE_GUILD)

        allowed = has_logical_permission(
            self.cfg,
            self.store,
            resolved_guild_id,
            permission_key,
            member_role_ids,
            is_admin=is_admin,
            can_manage_guild=can_manage_guild,
        )
        if not allowed:
            self._log_decision(False, action, resolved_guild_id, user_id, permission_key, "missing_permission")
            raise HTTPException(status_code=403, detail="Permission insuffisante")

        self._log_decision(True, action, resolved_guild_id, user_id, permission_key, "allowed")
        return AuthorizationContext(
            session=session,
            guild_id=resolved_guild_id,
            user_id=user_id,
            permission_key=permission_key,
        )

    @staticmethod
    def _find_user_guild(session: SessionData, guild_id: int) -> Optional[dict]:
        return next((g for g in session.guilds if int(g.get("id", 0)) == guild_id), None)

    @staticmethod
    def _resolve_guild_id(session: SessionData, guild_id: Optional[int]) -> int:
        if guild_id is not None:
            return int(guild_id)
        if session.selected_guild_id is not None:
            return int(session.selected_guild_id)
        raise HTTPException(status_code=400, detail="Aucune guild sélectionnée")

    @staticmethod
    def _log_decision(allowed: bool, action: str, guild_id: int, user_id: int, permission_key: str, reason: str) -> None:
        logger.info(
            "dashboard_authorization action=%s guild_id=%s user_id=%s permission=%s allowed=%s reason=%s",
            action,
            guild_id,
            user_id,
            permission_key,
            allowed,
            reason,
        )
