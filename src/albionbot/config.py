import os
from dataclasses import dataclass
from typing import List, Optional

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1","true","yes","y","on")

def _env_int(name: str) -> Optional[int]:
    v = os.getenv(name)
    if not v:
        return None
    try:
        return int(v.strip())
    except ValueError:
        return None

def _env_list_int(name: str) -> List[int]:
    v = os.getenv(name, "").strip()
    if not v:
        return []
    out: List[int] = []
    for part in v.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out

@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_ids: List[int]
    data_path: str

    bank_database_url: str
    bank_sqlite_path: str

    raid_require_manage_guild: bool
    raid_manager_role_id: Optional[int]

    bank_require_manage_guild: bool
    bank_manager_role_id: Optional[int]
    bank_allow_negative: bool

    sched_tick_seconds: int
    default_prep_minutes: int
    default_cleanup_minutes: int
    voice_check_after_minutes: int

def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN env var")

    return Config(
        discord_token=token,
        guild_ids=_env_list_int("GUILD_IDS"),
        data_path=os.getenv("DATA_PATH", "data/state.json").strip(),

        bank_database_url=(os.getenv("BANK_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()),
        bank_sqlite_path=os.getenv("BANK_SQLITE_PATH", "data/bank.sqlite3").strip(),

        raid_require_manage_guild=_env_bool("RAID_REQUIRE_MANAGE_GUILD", True),
        raid_manager_role_id=_env_int("RAID_MANAGER_ROLE_ID"),

        bank_require_manage_guild=_env_bool("BANK_REQUIRE_MANAGE_GUILD", True),
        bank_manager_role_id=_env_int("BANK_MANAGER_ROLE_ID"),
        bank_allow_negative=_env_bool("BANK_ALLOW_NEGATIVE", True),

        sched_tick_seconds=int(os.getenv("SCHED_TICK_SECONDS", "15")),
        default_prep_minutes=int(os.getenv("DEFAULT_PREP_MINUTES", "10")),
        default_cleanup_minutes=int(os.getenv("DEFAULT_CLEANUP_MINUTES", "30")),
        voice_check_after_minutes=int(os.getenv("VOICE_CHECK_AFTER_MINUTES", "5")),
    )
