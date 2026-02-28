from typing import List, Optional

import nextcord

from ..config import Config
from ..storage.store import Store

PERM_RAID_MANAGER = "raid_manager"
PERM_BANK_MANAGER = "bank_manager"
PERM_TICKET_MANAGER = "ticket_manager"


def _role_ids_for_permission(cfg: Config, store: Optional[Store], guild_id: int, permission_key: str) -> List[int]:
    role_ids: List[int] = []
    if store is not None:
        role_ids = store.get_permission_role_ids(guild_id, permission_key)
    if role_ids:
        return role_ids

    if permission_key == PERM_RAID_MANAGER and cfg.raid_manager_role_id is not None:
        return [cfg.raid_manager_role_id]
    if permission_key == PERM_BANK_MANAGER and cfg.bank_manager_role_id is not None:
        return [cfg.bank_manager_role_id]
    if permission_key == PERM_SUPPORT_ROLE and cfg.support_role_id is not None:
        return [cfg.support_role_id]
    if permission_key == PERM_TICKET_ADMIN and cfg.ticket_admin_role_id is not None:
        return [cfg.ticket_admin_role_id]
    return []


def is_guild_admin(member: nextcord.Member) -> bool:
    return bool(member.guild_permissions.administrator)


def can_manage_raids(cfg: Config, member: nextcord.Member, store: Optional[Store] = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    if cfg.raid_require_manage_guild and member.guild_permissions.manage_guild:
        return True
    role_ids = _role_ids_for_permission(cfg, store, member.guild.id, PERM_RAID_MANAGER)
    if role_ids:
        member_role_ids = {r.id for r in member.roles}
        return any(rid in member_role_ids for rid in role_ids)
    return False


def can_manage_bank(cfg: Config, member: nextcord.Member, store: Optional[Store] = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    if cfg.bank_require_manage_guild and member.guild_permissions.manage_guild:
        return True
    role_ids = _role_ids_for_permission(cfg, store, member.guild.id, PERM_BANK_MANAGER)
    if role_ids:
        member_role_ids = {r.id for r in member.roles}
        return any(rid in member_role_ids for rid in role_ids)
    return False


def can_manage_tickets(cfg: Config, member: nextcord.Member, store: Optional[Store] = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    role_ids = _role_ids_for_permission(cfg, store, member.guild.id, PERM_TICKET_MANAGER)
    if role_ids:
        member_role_ids = {r.id for r in member.roles}
        return any(rid in member_role_ids for rid in role_ids)
    return can_manage_raids(cfg, member, store)
