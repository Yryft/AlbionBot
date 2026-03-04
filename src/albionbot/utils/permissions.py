from typing import Iterable, List, Optional

import nextcord

from ..config import Config
from ..storage.store import Store

PERM_RAID_MANAGER = "raid_manager"
PERM_BANK_MANAGER = "bank_manager"
PERM_TICKET_MANAGER = "ticket_manager"


MANAGER_PERMISSIONS = {
    PERM_RAID_MANAGER,
    PERM_BANK_MANAGER,
    PERM_TICKET_MANAGER,
}


def role_ids_for_permission(cfg: Config, store: Optional[Store], guild_id: int, permission_key: str) -> List[int]:
    role_ids: List[int] = []
    if store is not None:
        role_ids = store.get_permission_role_ids(guild_id, permission_key)
    if role_ids:
        return role_ids

    if permission_key == PERM_RAID_MANAGER and cfg.raid_manager_role_id is not None:
        return [cfg.raid_manager_role_id]
    if permission_key == PERM_BANK_MANAGER and cfg.bank_manager_role_id is not None:
        return [cfg.bank_manager_role_id]
    # Backward compatibility: older deployments may still define ticket role IDs
    # through SUPPORT_ROLE_ID / TICKET_ADMIN_ROLE_ID env vars.
    if permission_key == PERM_TICKET_MANAGER:
        role_ids: List[int] = []
        if cfg.support_role_id is not None:
            role_ids.append(cfg.support_role_id)
        if cfg.ticket_admin_role_id is not None:
            role_ids.append(cfg.ticket_admin_role_id)
        if role_ids:
            return role_ids
    return []


def has_logical_permission(
    cfg: Config,
    store: Optional[Store],
    guild_id: int,
    permission_key: str,
    role_ids: Iterable[int],
    *,
    user_id: Optional[int] = None,
    is_admin: bool,
    can_manage_guild: bool = False,
) -> bool:
    if permission_key not in MANAGER_PERMISSIONS:
        return False
    if is_admin:
        return True
    if permission_key == PERM_RAID_MANAGER and cfg.raid_require_manage_guild and can_manage_guild:
        return True
    if permission_key == PERM_BANK_MANAGER and cfg.bank_require_manage_guild and can_manage_guild:
        return True
    allowed_role_ids = role_ids_for_permission(cfg, store, guild_id, permission_key)
    allowed_user_ids = store.get_permission_user_ids(guild_id, permission_key) if store is not None else []
    if user_id is not None and int(user_id) in set(allowed_user_ids):
        return True
    if not allowed_role_ids:
        return permission_key == PERM_TICKET_MANAGER and has_logical_permission(
            cfg,
            store,
            guild_id,
            PERM_RAID_MANAGER,
            role_ids,
            user_id=user_id,
            is_admin=is_admin,
            can_manage_guild=can_manage_guild,
        )
    return bool(set(map(int, role_ids)).intersection(allowed_role_ids))


def is_guild_admin(member: nextcord.Member) -> bool:
    return bool(member.guild_permissions.administrator)


def can_manage_raids(cfg: Config, member: nextcord.Member, store: Optional[Store] = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    if cfg.raid_require_manage_guild and member.guild_permissions.manage_guild:
        return True
    return has_logical_permission(
        cfg,
        store,
        member.guild.id,
        PERM_RAID_MANAGER,
        (r.id for r in member.roles),
        user_id=member.id,
        is_admin=bool(member.guild_permissions.administrator),
        can_manage_guild=bool(member.guild_permissions.manage_guild),
    )


def can_manage_bank(cfg: Config, member: nextcord.Member, store: Optional[Store] = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    if cfg.bank_require_manage_guild and member.guild_permissions.manage_guild:
        return True
    return has_logical_permission(
        cfg,
        store,
        member.guild.id,
        PERM_BANK_MANAGER,
        (r.id for r in member.roles),
        user_id=member.id,
        is_admin=bool(member.guild_permissions.administrator),
        can_manage_guild=bool(member.guild_permissions.manage_guild),
    )


def can_manage_tickets(cfg: Config, member: nextcord.Member, store: Optional[Store] = None) -> bool:
    if member.guild_permissions.administrator:
        return True
    return has_logical_permission(
        cfg,
        store,
        member.guild.id,
        PERM_TICKET_MANAGER,
        (r.id for r in member.roles),
        user_id=member.id,
        is_admin=bool(member.guild_permissions.administrator),
        can_manage_guild=bool(member.guild_permissions.manage_guild),
    )
