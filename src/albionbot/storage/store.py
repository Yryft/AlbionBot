import os
import json
import time
import asyncio
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Literal

RaidStatus = Literal["OPEN", "PINGED", "CLOSED"]
BankActionType = Literal["add", "remove", "add_split", "remove_split"]
TicketCreationMode = Literal["private_channel", "private_thread"]
TicketRecordStatus = Literal["open", "closed", "deleted"]
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
class TicketConfig:
    guild_id: int
    creation_mode: TicketCreationMode
    category_id: Optional[int] = None
    admin_role_ids: List[int] = field(default_factory=list)
    support_role_ids: List[int] = field(default_factory=list)
    naming_format: str = "ticket-{user}"
    open_style: Literal["message", "button"] = "button"
    ticket_types: Dict[str, TicketTypeConfig] = field(default_factory=dict)


@dataclass
class TicketRecord:
    ticket_id: str
    guild_id: int
    owner_user_id: int
    ticket_type_key: str = "default"
    channel_id: Optional[int] = None
    thread_id: Optional[int] = None
    status: TicketRecordStatus = "open"
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    closed_at: Optional[int] = None
    deleted_at: Optional[int] = None


@dataclass
class TicketMessageSnapshot:
    message_id: int
    author_id: int
    content: str
    embeds: List[Dict] = field(default_factory=list)
    attachments: List[Dict[str, str]] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class TicketTypeConfig:
    key: str
    label: str
    description: str = ""
    support_role_ids: List[int] = field(default_factory=list)
    category_id: Optional[int] = None


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
        self.bank_balances: Dict[int, Dict[int, int]] = {}
        self.bank_actions: Dict[int, List[BankAction]] = {}

        self.ticket_configs: Dict[int, TicketConfig] = {}
        self.ticket_records: Dict[str, TicketRecord] = {}
        self.ticket_messages: Dict[str, List[TicketMessageSnapshot]] = {}
        self.ticket_by_user: Dict[int, Dict[int, Dict[TicketRecordStatus, Set[str]]]] = {}

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
        for gid_str, ticket_cfg in raw.get("ticket_configs", {}).items():
            gid = int(gid_str)
            if not isinstance(ticket_cfg, dict):
                continue
            mode = str(ticket_cfg.get("mode", "private_channel"))
            category_id = ticket_cfg.get("category_id")
            open_style = str(ticket_cfg.get("open_style", "button"))
            default_category_id = int(category_id) if category_id is not None else None
            default_support_roles = list(map(int, ticket_cfg.get("support_role_ids", [])))
            self.ticket_configs[gid] = TicketConfig(
                guild_id=gid,
                creation_mode=mode if mode in {"private_thread", "private_channel"} else "private_channel",
                category_id=default_category_id,
                support_role_ids=default_support_roles,
                open_style=open_style if open_style in {"message", "button"} else "button",
                ticket_types={
                    "default": TicketTypeConfig(
                        key="default",
                        label="Support",
                        support_role_ids=default_support_roles,
                        category_id=default_category_id,
                    )
                },
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

    def _load_tickets_from_raw(self, raw: Dict) -> None:
        self.ticket_configs = {}
        self.ticket_records = {}
        self.ticket_messages = {}
        self.ticket_by_user = {}

        ticket_raw = raw.get("tickets", {}) if isinstance(raw.get("tickets", {}), dict) else {}

        for gid_str, conf in ticket_raw.get("configs", {}).items():
            if not isinstance(conf, dict):
                continue
            gid = int(gid_str)
            open_style = str(conf.get("open_style", "button"))
            type_map: Dict[str, TicketTypeConfig] = {}
            for type_key, type_data in (conf.get("ticket_types", {}) or {}).items():
                if not isinstance(type_data, dict):
                    continue
                key = str(type_key).strip().lower()
                if not key:
                    continue
                category_id = type_data.get("category_id")
                type_map[key] = TicketTypeConfig(
                    key=key,
                    label=str(type_data.get("label", key.title()))[:100],
                    description=str(type_data.get("description", ""))[:100],
                    support_role_ids=list(map(int, type_data.get("support_role_ids", []))),
                    category_id=int(category_id) if category_id is not None else None,
                )
            if "default" not in type_map:
                type_map["default"] = TicketTypeConfig(
                    key="default",
                    label="Support",
                    support_role_ids=list(map(int, conf.get("support_role_ids", []))),
                    category_id=conf.get("category_id"),
                )

            self.ticket_configs[gid] = TicketConfig(
                guild_id=gid,
                creation_mode=conf.get("creation_mode", "private_channel"),
                category_id=conf.get("category_id"),
                admin_role_ids=list(map(int, conf.get("admin_role_ids", []))),
                support_role_ids=list(map(int, conf.get("support_role_ids", []))),
                naming_format=conf.get("naming_format", "ticket-{user}"),
                open_style=open_style if open_style in {"message", "button"} else "button",
                ticket_types=type_map,
            )

        for ticket_id, rec in ticket_raw.get("records", {}).items():
            if not isinstance(rec, dict):
                continue
            self.ticket_records[str(ticket_id)] = TicketRecord(
                ticket_id=str(rec.get("ticket_id", ticket_id)),
                guild_id=int(rec["guild_id"]),
                owner_user_id=int(rec["owner_user_id"]),
                ticket_type_key=str(rec.get("ticket_type_key", "default")),
                channel_id=rec.get("channel_id"),
                thread_id=rec.get("thread_id"),
                status=rec.get("status", "open"),
                created_at=int(rec.get("created_at", int(time.time()))),
                updated_at=int(rec.get("updated_at", rec.get("created_at", int(time.time())))),
                closed_at=rec.get("closed_at"),
                deleted_at=rec.get("deleted_at"),
            )

        for ticket_id, snapshots in ticket_raw.get("messages", {}).items():
            out: List[TicketMessageSnapshot] = []
            for snap in snapshots or []:
                if not isinstance(snap, dict):
                    continue
                out.append(TicketMessageSnapshot(
                    message_id=int(snap["message_id"]),
                    author_id=int(snap["author_id"]),
                    content=snap.get("content", ""),
                    embeds=list(snap.get("embeds", [])),
                    attachments=list(snap.get("attachments", [])),
                    created_at=int(snap.get("created_at", int(time.time()))),
                ))
            self.ticket_messages[str(ticket_id)] = out

        by_user_raw = ticket_raw.get("by_user", {})
        if isinstance(by_user_raw, dict) and by_user_raw:
            for gid_str, users in by_user_raw.items():
                if not isinstance(users, dict):
                    continue
                gid = int(gid_str)
                self.ticket_by_user[gid] = {}
                for uid_str, grouped in users.items():
                    if not isinstance(grouped, dict):
                        continue
                    uid = int(uid_str)
                    self.ticket_by_user[gid][uid] = {
                        "open": set(map(str, grouped.get("open", []))),
                        "closed": set(map(str, grouped.get("closed", []))),
                        "deleted": set(map(str, grouped.get("deleted", []))),
                    }
        else:
            self._ticket_rebuild_user_index()

    def _ticket_rebuild_user_index(self) -> None:
        self.ticket_by_user = {}
        for record in self.ticket_records.values():
            self._ticket_index_record(record)

    def _ticket_index_record(self, record: TicketRecord) -> None:
        gid = int(record.guild_id)
        uid = int(record.owner_user_id)
        if gid not in self.ticket_by_user:
            self.ticket_by_user[gid] = {}
        if uid not in self.ticket_by_user[gid]:
            self.ticket_by_user[gid][uid] = {"open": set(), "closed": set(), "deleted": set()}

        for status in ["open", "closed", "deleted"]:
            self.ticket_by_user[gid][uid][status].discard(record.ticket_id)
        self.ticket_by_user[gid][uid][record.status].add(record.ticket_id)

    def _serialize_runtime_state(self) -> Dict:
        raw = {"templates": {}, "raids": {}, "guild_permissions": {}, "tickets": {"configs": {}, "records": {}, "messages": {}, "by_user": {}}}
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

        for gid, conf in self.ticket_configs.items():
            if isinstance(conf, dict):
                mode = str(conf.get("mode", "private_channel"))
                raw["tickets"]["configs"][str(gid)] = {
                    "guild_id": int(gid),
                    "creation_mode": mode if mode in {"private_thread", "private_channel"} else "private_channel",
                    "category_id": conf.get("category_id"),
                    "admin_role_ids": [],
                    "support_role_ids": list(map(int, conf.get("support_role_ids", []))),
                    "naming_format": "ticket-{user}",
                }
            else:
                raw["tickets"]["configs"][str(gid)] = {
                    "guild_id": conf.guild_id,
                    "creation_mode": conf.creation_mode,
                    "category_id": conf.category_id,
                    "admin_role_ids": list(map(int, conf.admin_role_ids)),
                    "support_role_ids": list(map(int, conf.support_role_ids)),
                    "naming_format": conf.naming_format,
                    "open_style": conf.open_style,
                    "ticket_types": {
                        key: {
                            "key": t.key,
                            "label": t.label,
                            "description": t.description,
                            "support_role_ids": list(map(int, t.support_role_ids)),
                            "category_id": t.category_id,
                        }
                        for key, t in conf.ticket_types.items()
                    },
                }

        for ticket_id, rec in self.ticket_records.items():
            raw["tickets"]["records"][str(ticket_id)] = asdict(rec)

        for ticket_id, snapshots in self.ticket_messages.items():
            raw["tickets"]["messages"][str(ticket_id)] = [asdict(snap) for snap in snapshots]

        for gid, users in self.ticket_by_user.items():
            raw["tickets"]["by_user"][str(gid)] = {}
            for uid, grouped in users.items():
                raw["tickets"]["by_user"][str(gid)][str(uid)] = {
                    "open": sorted(grouped["open"]),
                    "closed": sorted(grouped["closed"]),
                    "deleted": sorted(grouped["deleted"]),
                }
        return raw

    def get_permission_role_ids(self, guild_id: int, permission_key: str) -> List[int]:
        return list(self.guild_permissions.get(guild_id, {}).get(permission_key, []))

    def set_permission_role_ids(self, guild_id: int, permission_key: str, role_ids: List[int]) -> None:
        if guild_id not in self.guild_permissions:
            self.guild_permissions[guild_id] = {}
        self.guild_permissions[guild_id][permission_key] = list(map(int, role_ids))

    def get_ticket_config(self, guild_id: int) -> Dict[str, object]:
        data = self.ticket_configs.get(guild_id)
        if data is None:
            return {
                "mode": "private_channel",
                "category_id": None,
                "support_role_ids": [],
                "open_style": "button",
                "ticket_types": {
                    "default": {
                        "key": "default",
                        "label": "Support",
                        "description": "",
                        "support_role_ids": [],
                        "category_id": None,
                    }
                },
            }
        if isinstance(data, dict):
            return {
                "mode": str(data.get("mode", "private_channel")),
                "category_id": data.get("category_id"),
                "support_role_ids": list(map(int, data.get("support_role_ids", []))),
                "open_style": str(data.get("open_style", "button")),
                "ticket_types": data.get("ticket_types", {}),
            }
        type_map = {
            key: {
                "key": t.key,
                "label": t.label,
                "description": t.description,
                "support_role_ids": list(map(int, t.support_role_ids)),
                "category_id": t.category_id,
            }
            for key, t in data.ticket_types.items()
        }
        if "default" not in type_map:
            type_map["default"] = {
                "key": "default",
                "label": "Support",
                "description": "",
                "support_role_ids": list(map(int, data.support_role_ids)),
                "category_id": data.category_id,
            }

        return {
            "mode": data.creation_mode,
            "category_id": data.category_id,
            "support_role_ids": list(map(int, data.support_role_ids)),
            "open_style": data.open_style,
            "ticket_types": type_map,
        }

    def set_ticket_config(self, guild_id: int, **updates: object) -> None:
        conf = self.ticket_configs.get(guild_id)
        if conf is None or isinstance(conf, dict):
            current = self.get_ticket_config(guild_id)
            raw_types = current.get("ticket_types", {})
            type_map: Dict[str, TicketTypeConfig] = {}
            if isinstance(raw_types, dict):
                for type_key, type_data in raw_types.items():
                    if not isinstance(type_data, dict):
                        continue
                    key = str(type_key).strip().lower()
                    if not key:
                        continue
                    category_id = type_data.get("category_id")
                    type_map[key] = TicketTypeConfig(
                        key=key,
                        label=str(type_data.get("label", key.title())),
                        description=str(type_data.get("description", "")),
                        support_role_ids=list(map(int, type_data.get("support_role_ids", []))),
                        category_id=int(category_id) if category_id is not None else None,
                    )
            conf = TicketConfig(
                guild_id=guild_id,
                creation_mode=str(current.get("mode", "private_channel")),
                category_id=current.get("category_id"),
                support_role_ids=list(map(int, current.get("support_role_ids", []))),
                open_style=str(current.get("open_style", "button")),
                ticket_types=type_map,
            )

        mode = updates.get("mode")
        if mode is not None:
            conf.creation_mode = str(mode)

        if "category_id" in updates:
            category_id = updates.get("category_id")
            conf.category_id = int(category_id) if category_id is not None else None

        support_role_ids = updates.get("support_role_ids")
        if support_role_ids is not None:
            conf.support_role_ids = list(map(int, support_role_ids))

        open_style = updates.get("open_style")
        if open_style is not None:
            style_value = str(open_style)
            conf.open_style = style_value if style_value in {"message", "button"} else "button"

        ticket_types = updates.get("ticket_types")
        if ticket_types is not None and isinstance(ticket_types, dict):
            type_map: Dict[str, TicketTypeConfig] = {}
            for type_key, type_data in ticket_types.items():
                if not isinstance(type_data, dict):
                    continue
                key = str(type_key).strip().lower()
                if not key:
                    continue
                category_id = type_data.get("category_id")
                type_map[key] = TicketTypeConfig(
                    key=key,
                    label=str(type_data.get("label", key.title())),
                    description=str(type_data.get("description", "")),
                    support_role_ids=list(map(int, type_data.get("support_role_ids", []))),
                    category_id=int(category_id) if category_id is not None else None,
                )
            conf.ticket_types = type_map

        self.ticket_configs[guild_id] = conf

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
        self._load_tickets_from_raw(raw_for_state)
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

    # Ticket helpers
    def ticket_get_config(self, guild_id: int) -> Optional[TicketConfig]:
        return self.ticket_configs.get(int(guild_id))

    def ticket_set_config(self, config: TicketConfig) -> None:
        self.ticket_configs[int(config.guild_id)] = config

    def ticket_create_record(self, record: TicketRecord) -> None:
        now = int(time.time())
        record.created_at = int(record.created_at or now)
        record.updated_at = int(record.updated_at or record.created_at)
        self.ticket_records[record.ticket_id] = record
        self._ticket_index_record(record)

    def ticket_update_status(self, ticket_id: str, status: TicketRecordStatus, at: Optional[int] = None) -> Optional[TicketRecord]:
        record = self.ticket_records.get(str(ticket_id))
        if not record:
            return None
        ts = int(at or time.time())
        record.status = status
        record.updated_at = ts
        if status == "closed":
            record.closed_at = ts
        if status == "deleted":
            record.deleted_at = ts
        self._ticket_index_record(record)
        return record

    def ticket_set_channel_ref(self, ticket_id: str, channel_id: Optional[int] = None, thread_id: Optional[int] = None) -> Optional[TicketRecord]:
        record = self.ticket_records.get(str(ticket_id))
        if not record:
            return None
        record.channel_id = channel_id
        record.thread_id = thread_id
        record.updated_at = int(time.time())
        return record

    def ticket_append_snapshot(self, ticket_id: str, snapshot: TicketMessageSnapshot) -> None:
        ticket_key = str(ticket_id)
        if ticket_key not in self.ticket_messages:
            self.ticket_messages[ticket_key] = []
        self.ticket_messages[ticket_key].append(snapshot)

    def ticket_get_transcript(self, ticket_id: str) -> List[TicketMessageSnapshot]:
        return list(self.ticket_messages.get(str(ticket_id), []))

    def ticket_find_by_user(self, guild_id: int, user_id: int, status: Optional[TicketRecordStatus] = None) -> List[TicketRecord]:
        user_idx = self.ticket_by_user.get(int(guild_id), {}).get(int(user_id), {})
        if status is not None:
            ticket_ids = sorted(user_idx.get(status, set()))
        else:
            ticket_ids = sorted(set().union(*[user_idx.get("open", set()), user_idx.get("closed", set()), user_idx.get("deleted", set())]))
        return [self.ticket_records[ticket_id] for ticket_id in ticket_ids if ticket_id in self.ticket_records]

    def ticket_find_by_channel(self, guild_id: int, channel_id: Optional[int] = None, thread_id: Optional[int] = None) -> Optional[TicketRecord]:
        for record in self.ticket_records.values():
            if int(record.guild_id) != int(guild_id):
                continue
            if channel_id is not None and record.channel_id == channel_id:
                return record
            if thread_id is not None and record.thread_id == thread_id:
                return record
        return None

    def ticket_list_open(self, guild_id: int) -> List[TicketRecord]:
        out: List[TicketRecord] = []
        for record in self.ticket_records.values():
            if int(record.guild_id) == int(guild_id) and record.status == "open":
                out.append(record)
        return out
