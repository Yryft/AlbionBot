import os
import json
import time
import asyncio
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Literal

RaidStatus = Literal["OPEN", "PINGED", "CLOSED"]
BankActionType = Literal["add", "remove", "add_split", "remove_split"]
TicketStatus = Literal["open", "closed", "deleted"]
TicketTargetType = Literal["channel", "thread"]
STATE_DB_KEY = "bot_state_v1"


@dataclass
class CompRole:
    key: str
    label: str
    slots: int
    ip_required: bool = False
    required_role_ids: List[int] = field(default_factory=list)


@dataclass
class CompTemplate:
    name: str
    description: str
    created_by: int
    content_type: Literal["ava_raid", "pvp", "pve"] = "pvp"
    created_at: int = field(default_factory=lambda: int(time.time()))
    raid_required_role_ids: List[int] = field(default_factory=list)
    roles: List[CompRole] = field(default_factory=list)


@dataclass
class Signup:
    user_id: int
    role_key: str
    status: Literal["main", "wait"] = "main"
    ip: Optional[int] = None
    joined_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class RaidEvent:
    raid_id: str
    template_name: str
    title: str
    description: str
    extra_message: str
    start_at: int
    created_by: int
    created_at: int = field(default_factory=lambda: int(time.time()))

    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    thread_id: Optional[int] = None

    voice_channel_id: Optional[int] = None

    signups: Dict[int, Signup] = field(default_factory=dict)
    absent: Set[int] = field(default_factory=set)

    prep_minutes: int = 10
    cleanup_minutes: int = 30

    temp_role_id: Optional[int] = None

    prep_done: bool = False
    ping_done: bool = False
    voice_check_done: bool = False
    cleanup_done: bool = False
    last_voice_present_ids: List[int] = field(default_factory=list)
    dm_notify_users: Set[int] = field(default_factory=set)


@dataclass
class BankAction:
    action_id: str
    guild_id: int
    actor_id: int
    created_at: int
    action_type: BankActionType
    deltas: Dict[int, int]
    note: str = ""
    undone: bool = False
    undone_at: Optional[int] = None


@dataclass
class TicketGuildConfig:
    mode: TicketTargetType = "channel"
    category_id: Optional[int] = None
    parent_channel_id: Optional[int] = None
    support_role_ids: List[int] = field(default_factory=list)


@dataclass
class TicketRecord:
    ticket_id: str
    guild_id: int
    owner_id: int
    status: TicketStatus
    created_at: int = field(default_factory=lambda: int(time.time()))
    closed_at: Optional[int] = None
    deleted_at: Optional[int] = None
    channel_id: Optional[int] = None
    thread_id: Optional[int] = None
    target_type: TicketTargetType = "channel"


class Store:
    def __init__(self, path: str, bank_action_log_limit: int = 500, bank_database_url: str = "", bank_sqlite_path: str = "data/bank.sqlite3"):
        self.path = path
        self.bank_action_log_limit = bank_action_log_limit
        self.lock = asyncio.Lock()

        self.bank_db = None
        self._bank_migrated_from_json = False
        self._state_migrated_from_json = False
        try:
            from .bank_db import BankDB, BankDBConfig
            self.bank_db = BankDB(BankDBConfig(
                database_url=(bank_database_url or "").strip(),
                sqlite_path=(bank_sqlite_path or "data/bank.sqlite3").strip(),
                action_log_limit=bank_action_log_limit,
            ))
        except Exception:
            if (bank_database_url or "").strip():
                raise
            self.bank_db = None

        self.templates: Dict[str, CompTemplate] = {}
        self.raids: Dict[str, RaidEvent] = {}
        self.guild_permissions: Dict[int, Dict[str, List[int]]] = {}
        self.ticket_configs: Dict[int, TicketGuildConfig] = {}
        self.tickets: Dict[str, TicketRecord] = {}

        self.bank_balances: Dict[int, Dict[int, int]] = {}
        self.bank_actions: Dict[int, List[BankAction]] = {}

        self.load()
        if self.bank_db and (self._bank_migrated_from_json or self._state_migrated_from_json):
            self.save()

    def _safe_read_json_file(self) -> Dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_templates_and_raids(self, raw: Dict) -> None:
        self.templates = {}
        for name, t in raw.get("templates", {}).items():
            roles: List[CompRole] = []
            for r in t.get("roles", []):
                roles.append(CompRole(
                    key=r["key"],
                    label=r["label"],
                    slots=int(r["slots"]),
                    ip_required=bool(r.get("ip_required", False)),
                    required_role_ids=list(map(int, r.get("required_role_ids", []))),
                ))
            self.templates[name] = CompTemplate(
                name=t["name"],
                description=t.get("description", ""),
                created_by=int(t["created_by"]),
                content_type=t.get("content_type", "pvp"),
                created_at=int(t.get("created_at", int(time.time()))),
                raid_required_role_ids=list(map(int, t.get("raid_required_role_ids", []))),
                roles=roles,
            )

        self.raids = {}
        for rid, r in raw.get("raids", {}).items():
            signups: Dict[int, Signup] = {}
            for uid_str, s in r.get("signups", {}).items():
                uid = int(uid_str)
                signups[uid] = Signup(
                    user_id=uid,
                    role_key=s["role_key"],
                    status=s.get("status", "main"),
                    ip=s.get("ip"),
                    joined_at=int(s.get("joined_at", int(time.time()))),
                )

            self.raids[rid] = RaidEvent(
                raid_id=r["raid_id"],
                template_name=r["template_name"],
                title=r["title"],
                description=r.get("description", ""),
                extra_message=r.get("extra_message", ""),
                start_at=int(r["start_at"]),
                created_by=int(r["created_by"]),
                created_at=int(r.get("created_at", int(time.time()))),
                channel_id=r.get("channel_id"),
                message_id=r.get("message_id"),
                thread_id=r.get("thread_id"),
                voice_channel_id=r.get("voice_channel_id"),
                signups=signups,
                absent=set(map(int, r.get("absent", []))),
                prep_minutes=int(r.get("prep_minutes", 10)),
                cleanup_minutes=int(r.get("cleanup_minutes", 30)),
                temp_role_id=r.get("temp_role_id"),
                prep_done=bool(r.get("prep_done", False)),
                ping_done=bool(r.get("ping_done", False)),
                voice_check_done=bool(r.get("voice_check_done", False)),
                cleanup_done=bool(r.get("cleanup_done", False)),
                last_voice_present_ids=list(map(int, r.get("last_voice_present_ids", []))),
                dm_notify_users=set(map(int, r.get("dm_notify_users", []))),
            )

        self.guild_permissions = {}
        for gid_str, perm_map in raw.get("guild_permissions", {}).items():
            gid = int(gid_str)
            if not isinstance(perm_map, dict):
                continue
            out_map: Dict[str, List[int]] = {}
            for perm_key, role_ids in perm_map.items():
                out_map[str(perm_key)] = list(map(int, role_ids or []))
            self.guild_permissions[gid] = out_map

        self.ticket_configs = {}
        for gid_str, cfg in raw.get("ticket_configs", {}).items():
            gid = int(gid_str)
            if not isinstance(cfg, dict):
                continue
            mode = cfg.get("mode", "channel")
            if mode not in {"channel", "thread"}:
                mode = "channel"
            self.ticket_configs[gid] = TicketGuildConfig(
                mode=mode,
                category_id=cfg.get("category_id"),
                parent_channel_id=cfg.get("parent_channel_id"),
                support_role_ids=list(map(int, cfg.get("support_role_ids", []))),
            )

        self.tickets = {}
        for tid, t in raw.get("tickets", {}).items():
            if not isinstance(t, dict):
                continue
            status = t.get("status", "open")
            if status not in {"open", "closed", "deleted"}:
                status = "open"
            target_type = t.get("target_type", "channel")
            if target_type not in {"channel", "thread"}:
                target_type = "channel"
            self.tickets[tid] = TicketRecord(
                ticket_id=t.get("ticket_id", tid),
                guild_id=int(t["guild_id"]),
                owner_id=int(t["owner_id"]),
                status=status,
                created_at=int(t.get("created_at", int(time.time()))),
                closed_at=t.get("closed_at"),
                deleted_at=t.get("deleted_at"),
                channel_id=t.get("channel_id"),
                thread_id=t.get("thread_id"),
                target_type=target_type,
            )

    def _load_bank_legacy_from_raw(self, raw: Dict) -> None:
        self.bank_balances = {}
        self.bank_actions = {}

        for gid_str, d in raw.get("bank_balances", {}).items():
            gid = int(gid_str)
            self.bank_balances[gid] = {int(uid): int(bal) for uid, bal in d.items()}

        for gid_str, lst in raw.get("bank_actions", {}).items():
            gid = int(gid_str)
            actions: List[BankAction] = []
            for a in lst:
                actions.append(BankAction(
                    action_id=a["action_id"],
                    guild_id=int(a["guild_id"]),
                    actor_id=int(a["actor_id"]),
                    created_at=int(a["created_at"]),
                    action_type=a["action_type"],
                    deltas={int(uid): int(delta) for uid, delta in a["deltas"].items()},
                    note=a.get("note", ""),
                    undone=bool(a.get("undone", False)),
                    undone_at=a.get("undone_at"),
                ))
            self.bank_actions[gid] = actions

    def _serialize_runtime_state(self) -> Dict:
        raw = {"templates": {}, "raids": {}, "guild_permissions": {}, "ticket_configs": {}, "tickets": {}}
        for name, t in self.templates.items():
            raw["templates"][name] = {
                "name": t.name,
                "description": t.description,
                "created_by": t.created_by,
                "content_type": t.content_type,
                "created_at": t.created_at,
                "raid_required_role_ids": t.raid_required_role_ids,
                "roles": [asdict(r) for r in t.roles],
            }

        for rid, r in self.raids.items():
            raw["raids"][rid] = {
                "raid_id": r.raid_id,
                "template_name": r.template_name,
                "title": r.title,
                "description": r.description,
                "extra_message": r.extra_message,
                "start_at": r.start_at,
                "created_by": r.created_by,
                "created_at": r.created_at,
                "channel_id": r.channel_id,
                "message_id": r.message_id,
                "thread_id": r.thread_id,
                "voice_channel_id": r.voice_channel_id,
                "signups": {str(uid): asdict(s) for uid, s in r.signups.items()},
                "absent": list(r.absent),
                "prep_minutes": r.prep_minutes,
                "cleanup_minutes": r.cleanup_minutes,
                "temp_role_id": r.temp_role_id,
                "prep_done": r.prep_done,
                "ping_done": r.ping_done,
                "voice_check_done": r.voice_check_done,
                "cleanup_done": r.cleanup_done,
                "last_voice_present_ids": list(r.last_voice_present_ids),
                "dm_notify_users": list(r.dm_notify_users),
            }

        for gid, perm_map in self.guild_permissions.items():
            raw["guild_permissions"][str(gid)] = {k: list(map(int, v)) for k, v in perm_map.items()}

        for gid, cfg in self.ticket_configs.items():
            raw["ticket_configs"][str(gid)] = asdict(cfg)

        for tid, ticket in self.tickets.items():
            raw["tickets"][tid] = asdict(ticket)
        return raw

    def get_permission_role_ids(self, guild_id: int, permission_key: str) -> List[int]:
        return list(self.guild_permissions.get(guild_id, {}).get(permission_key, []))

    def set_permission_role_ids(self, guild_id: int, permission_key: str, role_ids: List[int]) -> None:
        if guild_id not in self.guild_permissions:
            self.guild_permissions[guild_id] = {}
        self.guild_permissions[guild_id][permission_key] = list(map(int, role_ids))

    def get_ticket_config(self, guild_id: int) -> TicketGuildConfig:
        return self.ticket_configs.get(guild_id, TicketGuildConfig())

    def set_ticket_config(self, guild_id: int, cfg: TicketGuildConfig) -> None:
        self.ticket_configs[guild_id] = cfg

    def load(self) -> None:
        file_raw = self._safe_read_json_file()
        raw_for_state = file_raw

        if self.bank_db is not None:
            db_blob = self.bank_db.get_state_blob(STATE_DB_KEY)
            if db_blob:
                try:
                    raw_for_state = json.loads(db_blob)
                except Exception:
                    raw_for_state = file_raw
            elif file_raw.get("templates") or file_raw.get("raids"):
                self._state_migrated_from_json = True

        self._load_templates_and_raids(raw_for_state)
        self._load_bank_legacy_from_raw(file_raw)

        if self.bank_db is not None:
            if self.bank_db.is_empty() and (self.bank_balances or self.bank_actions):
                try:
                    self.bank_db.import_from_json(self.bank_balances, self.bank_actions)
                    self._bank_migrated_from_json = True
                except Exception:
                    pass
            self.bank_balances = {}
            self.bank_actions = {}

    def save(self) -> None:
        raw = self._serialize_runtime_state()

        if self.bank_db is not None:
            raw["bank_storage"] = "sql"
            self.bank_db.set_state_blob(STATE_DB_KEY, json.dumps(raw, ensure_ascii=False))
        else:
            raw["bank_balances"] = {}
            raw["bank_actions"] = {}
            for gid, d in self.bank_balances.items():
                raw["bank_balances"][str(gid)] = {str(uid): bal for uid, bal in d.items()}
            for gid, actions in self.bank_actions.items():
                raw["bank_actions"][str(gid)] = []
                for a in actions[-self.bank_action_log_limit:]:
                    raw["bank_actions"][str(gid)].append({
                        "action_id": a.action_id,
                        "guild_id": a.guild_id,
                        "actor_id": a.actor_id,
                        "created_at": a.created_at,
                        "action_type": a.action_type,
                        "deltas": {str(uid): delta for uid, delta in a.deltas.items()},
                        "note": a.note,
                        "undone": a.undone,
                        "undone_at": a.undone_at,
                    })

        base_dir = os.path.dirname(self.path) or "."
        os.makedirs(base_dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # Bank helpers
    def bank_get_balance(self, guild_id: int, user_id: int) -> int:
        if self.bank_db is not None:
            return self.bank_db.get_balance(guild_id, user_id)
        return self.bank_balances.get(guild_id, {}).get(user_id, 0)

    def bank_set_balance(self, guild_id: int, user_id: int, bal: int) -> None:
        if self.bank_db is not None:
            self.bank_db.set_balance(guild_id, user_id, bal)
            return
        if guild_id not in self.bank_balances:
            self.bank_balances[guild_id] = {}
        self.bank_balances[guild_id][user_id] = bal

    def bank_append_action(self, action: BankAction) -> None:
        if self.bank_db is not None:
            self.bank_db.append_action(action)
            return
        if action.guild_id not in self.bank_actions:
            self.bank_actions[action.guild_id] = []
        self.bank_actions[action.guild_id].append(action)
        if len(self.bank_actions[action.guild_id]) > self.bank_action_log_limit:
            self.bank_actions[action.guild_id] = self.bank_actions[action.guild_id][-self.bank_action_log_limit:]

    def bank_find_last_action_for_actor(self, guild_id: int, actor_id: int) -> Optional[BankAction]:
        if self.bank_db is not None:
            return self.bank_db.find_last_action_for_actor(guild_id, actor_id)
        actions = self.bank_actions.get(guild_id, [])
        for a in reversed(actions):
            if a.actor_id == actor_id and not a.undone:
                return a
        return None

    def bank_mark_action_undone(self, action_id: str, undone_at: int) -> None:
        if self.bank_db is not None:
            self.bank_db.mark_action_undone(action_id, undone_at)
            return
        for actions in self.bank_actions.values():
            for a in actions:
                if a.action_id == action_id:
                    a.undone = True
                    a.undone_at = int(undone_at)
                    return
