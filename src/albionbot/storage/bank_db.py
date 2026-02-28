import os
import time
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .store import BankAction

# Optional dependency for Railway Postgres.
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None


@dataclass
class BankDBConfig:
    # If set, should be a PostgreSQL connection URL (Railway provides DATABASE_URL).
    database_url: str = ""
    # Used when no database_url is provided.
    sqlite_path: str = "data/bank.sqlite3"
    # Keep at most N actions per guild (older ones will be pruned).
    action_log_limit: int = 500


class BankDB:
    """
    SQL storage for the Bank module.

    - PostgreSQL: when database_url is set (recommended on Railway).
    - SQLite: fallback when database_url is empty (OK locally; on Railway needs a persistent volume).
    """

    def __init__(self, cfg: BankDBConfig):
        self.cfg = cfg
        self.kind = "postgres" if (cfg.database_url or "").strip() else "sqlite"

        if self.kind == "postgres":
            if psycopg is None:
                raise RuntimeError(
                    "BANK_DATABASE_URL/DATABASE_URL is set but psycopg is not installed. "
                    "Add 'psycopg[binary]' to dependencies."
                )
            url = (cfg.database_url or "").strip()
            # Some providers still use postgres:// (psycopg prefers postgresql:// but accepts both)
            self._pg_conn = psycopg.connect(url, row_factory=dict_row)
            self._pg_conn.autocommit = True
            self._sqlite_conn = None
        else:
            self._pg_conn = None
            path = cfg.sqlite_path.strip() or "data/bank.sqlite3"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._sqlite_conn = sqlite3.connect(path, check_same_thread=False)
            self._sqlite_conn.row_factory = sqlite3.Row

        self._init_schema()

    def close(self) -> None:
        try:
            if self._pg_conn:
                self._pg_conn.close()
        finally:
            if self._sqlite_conn:
                self._sqlite_conn.close()

    # -----------------------------
    # Schema
    # -----------------------------
    def _init_schema(self) -> None:
        if self.kind == "postgres":
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bank_balances (
                    guild_id BIGINT NOT NULL,
                    user_id  BIGINT NOT NULL,
                    balance  INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                );
                """
            )
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bank_actions (
                    action_id TEXT PRIMARY KEY,
                    guild_id  BIGINT NOT NULL,
                    actor_id  BIGINT NOT NULL,
                    created_at INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    undone BOOLEAN NOT NULL DEFAULT FALSE,
                    undone_at INTEGER NULL
                );
                """
            )
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bank_action_deltas (
                    action_id TEXT NOT NULL REFERENCES bank_actions(action_id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    delta INTEGER NOT NULL,
                    PRIMARY KEY (action_id, user_id)
                );
                """
            )
            self._exec("CREATE INDEX IF NOT EXISTS idx_bank_actions_guild_created ON bank_actions(guild_id, created_at DESC);")
            self._exec("CREATE INDEX IF NOT EXISTS idx_bank_actions_actor_created ON bank_actions(guild_id, actor_id, created_at DESC);")
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
        else:
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bank_balances (
                    guild_id INTEGER NOT NULL,
                    user_id  INTEGER NOT NULL,
                    balance  INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                );
                """
            )
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bank_actions (
                    action_id TEXT PRIMARY KEY,
                    guild_id  INTEGER NOT NULL,
                    actor_id  INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    undone INTEGER NOT NULL DEFAULT 0,
                    undone_at INTEGER NULL
                );
                """
            )
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bank_action_deltas (
                    action_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    delta INTEGER NOT NULL,
                    PRIMARY KEY (action_id, user_id),
                    FOREIGN KEY (action_id) REFERENCES bank_actions(action_id) ON DELETE CASCADE
                );
                """
            )
            self._exec("CREATE INDEX IF NOT EXISTS idx_bank_actions_guild_created ON bank_actions(guild_id, created_at DESC);")
            self._exec("CREATE INDEX IF NOT EXISTS idx_bank_actions_actor_created ON bank_actions(guild_id, actor_id, created_at DESC);")
            self._exec(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )

    # -----------------------------
    # Low-level exec helpers
    # -----------------------------
    def _exec(self, sql: str, params: Tuple = ()) -> None:
        if self.kind == "postgres":
            assert self._pg_conn is not None
            with self._pg_conn.cursor() as cur:
                cur.execute(sql, params)
        else:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.cursor()
            cur.execute(sql, params)
            self._sqlite_conn.commit()

    def _fetchone(self, sql: str, params: Tuple = ()) -> Optional[dict]:
        if self.kind == "postgres":
            assert self._pg_conn is not None
            with self._pg_conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else None
        else:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def _fetchall(self, sql: str, params: Tuple = ()) -> List[dict]:
        if self.kind == "postgres":
            assert self._pg_conn is not None
            with self._pg_conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        else:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    # -----------------------------
    # Public API
    # -----------------------------
    def get_balance(self, guild_id: int, user_id: int) -> int:
        row = self._fetchone(
            "SELECT balance FROM bank_balances WHERE guild_id = ? AND user_id = ?;"
            if self.kind == "sqlite"
            else "SELECT balance FROM bank_balances WHERE guild_id = %s AND user_id = %s;",
            (guild_id, user_id)
        )
        return int(row["balance"]) if row else 0

    def set_balance(self, guild_id: int, user_id: int, balance: int) -> None:
        now = int(time.time())
        if self.kind == "postgres":
            self._exec(
                """
                INSERT INTO bank_balances(guild_id, user_id, balance, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (guild_id, user_id)
                DO UPDATE SET balance = EXCLUDED.balance, updated_at = EXCLUDED.updated_at;
                """,
                (guild_id, user_id, int(balance), now)
            )
        else:
            self._exec(
                """
                INSERT INTO bank_balances(guild_id, user_id, balance, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id)
                DO UPDATE SET balance = excluded.balance, updated_at = excluded.updated_at;
                """,
                (guild_id, user_id, int(balance), now)
            )

    def get_leaderboard(self, guild_id: int, limit: int, offset: int = 0) -> List[Tuple[int, int]]:
        rows = self._fetchall(
            """
            SELECT user_id, balance
            FROM bank_balances
            WHERE guild_id = ? AND balance != 0
            ORDER BY balance DESC, user_id ASC
            LIMIT ? OFFSET ?;
            """ if self.kind == "sqlite" else
            """
            SELECT user_id, balance
            FROM bank_balances
            WHERE guild_id = %s AND balance <> 0
            ORDER BY balance DESC, user_id ASC
            LIMIT %s OFFSET %s;
            """,
            (int(guild_id), int(limit), int(offset))
        )
        return [(int(r["user_id"]), int(r["balance"])) for r in rows]

    def get_leaderboard_count(self, guild_id: int) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) as c FROM bank_balances WHERE guild_id = ? AND balance != 0;"
            if self.kind == "sqlite" else
            "SELECT COUNT(*) as c FROM bank_balances WHERE guild_id = %s AND balance <> 0;",
            (int(guild_id),)
        )
        return int(row["c"]) if row else 0

    def append_action(self, action: BankAction) -> None:
        # Insert action
        if self.kind == "postgres":
            self._exec(
                """
                INSERT INTO bank_actions(action_id, guild_id, actor_id, created_at, action_type, note, undone, undone_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    action.action_id,
                    int(action.guild_id),
                    int(action.actor_id),
                    int(action.created_at),
                    str(action.action_type),
                    str(action.note or ""),
                    bool(action.undone),
                    action.undone_at,
                )
            )
            # deltas
            assert self._pg_conn is not None
            with self._pg_conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO bank_action_deltas(action_id, user_id, delta) VALUES (%s, %s, %s);",
                    [(action.action_id, int(uid), int(delta)) for uid, delta in action.deltas.items()]
                )
        else:
            self._exec(
                """
                INSERT INTO bank_actions(action_id, guild_id, actor_id, created_at, action_type, note, undone, undone_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    action.action_id,
                    int(action.guild_id),
                    int(action.actor_id),
                    int(action.created_at),
                    str(action.action_type),
                    str(action.note or ""),
                    1 if action.undone else 0,
                    action.undone_at,
                )
            )
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.cursor()
            cur.executemany(
                "INSERT INTO bank_action_deltas(action_id, user_id, delta) VALUES (?, ?, ?);",
                [(action.action_id, int(uid), int(delta)) for uid, delta in action.deltas.items()]
            )
            self._sqlite_conn.commit()

        self._prune_actions_if_needed(action.guild_id)

    def find_last_action_for_actor(self, guild_id: int, actor_id: int) -> Optional[BankAction]:
        # Get last action header
        row = self._fetchone(
            """
            SELECT action_id, guild_id, actor_id, created_at, action_type, note, undone, undone_at
            FROM bank_actions
            WHERE guild_id = ? AND actor_id = ? AND undone = 0
            ORDER BY created_at DESC
            LIMIT 1;
            """ if self.kind == "sqlite" else
            """
            SELECT action_id, guild_id, actor_id, created_at, action_type, note, undone, undone_at
            FROM bank_actions
            WHERE guild_id = %s AND actor_id = %s AND undone = FALSE
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (guild_id, actor_id)
        )
        if not row:
            return None

        action_id = row["action_id"]
        deltas_rows = self._fetchall(
            "SELECT user_id, delta FROM bank_action_deltas WHERE action_id = ?;" if self.kind == "sqlite"
            else "SELECT user_id, delta FROM bank_action_deltas WHERE action_id = %s;",
            (action_id,)
        )
        deltas = {int(r["user_id"]): int(r["delta"]) for r in deltas_rows}

        return BankAction(
            action_id=str(row["action_id"]),
            guild_id=int(row["guild_id"]),
            actor_id=int(row["actor_id"]),
            created_at=int(row["created_at"]),
            action_type=str(row["action_type"]),
            deltas=deltas,
            note=str(row.get("note", "") or ""),
            undone=bool(row["undone"]) if self.kind == "postgres" else bool(int(row["undone"])),
            undone_at=row.get("undone_at"),
        )

    def mark_action_undone(self, action_id: str, undone_at: int) -> None:
        if self.kind == "postgres":
            self._exec(
                "UPDATE bank_actions SET undone = TRUE, undone_at = %s WHERE action_id = %s;",
                (int(undone_at), str(action_id))
            )
        else:
            self._exec(
                "UPDATE bank_actions SET undone = 1, undone_at = ? WHERE action_id = ?;",
                (int(undone_at), str(action_id))
            )


    def get_state_blob(self, key: str) -> Optional[str]:
        row = self._fetchone(
            "SELECT value_json FROM bot_state WHERE key = ?;" if self.kind == "sqlite"
            else "SELECT value_json FROM bot_state WHERE key = %s;",
            (str(key),)
        )
        if not row:
            return None
        return str(row["value_json"])

    def set_state_blob(self, key: str, value_json: str) -> None:
        now = int(time.time())
        if self.kind == "postgres":
            self._exec(
                """
                INSERT INTO bot_state(key, value_json, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (key)
                DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = EXCLUDED.updated_at;
                """,
                (str(key), str(value_json), now)
            )
        else:
            self._exec(
                """
                INSERT INTO bot_state(key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at;
                """,
                (str(key), str(value_json), now)
            )

    def is_empty(self) -> bool:
        row = self._fetchone(
            "SELECT COUNT(*) as c FROM bank_actions;" if self.kind == "sqlite" else "SELECT COUNT(*) as c FROM bank_actions;"
            if self.kind == "postgres" else "SELECT 0 as c;"
        )
        return (row is None) or int(row["c"]) == 0

    def import_from_json(self, bank_balances: Dict[int, Dict[int, int]], bank_actions: Dict[int, List[BankAction]]) -> int:
        """
        Import existing JSON bank state into SQL (one-shot).
        Returns number of imported actions.
        """
        # balances
        for gid, d in bank_balances.items():
            for uid, bal in d.items():
                self.set_balance(int(gid), int(uid), int(bal))

        imported = 0
        for gid, actions in bank_actions.items():
            for a in actions:
                # Only import actions not already present
                exists = self._fetchone(
                    "SELECT action_id FROM bank_actions WHERE action_id = ?;" if self.kind == "sqlite"
                    else "SELECT action_id FROM bank_actions WHERE action_id = %s;",
                    (a.action_id,)
                )
                if exists:
                    continue
                self.append_action(a)
                if a.undone and a.undone_at:
                    self.mark_action_undone(a.action_id, int(a.undone_at))
                imported += 1
        return imported

    # -----------------------------
    # Maintenance
    # -----------------------------
    def _prune_actions_if_needed(self, guild_id: int) -> None:
        limit = int(self.cfg.action_log_limit or 0)
        if limit <= 0:
            return

        # Fetch action_ids to delete (older than 'limit' most recent)
        rows = self._fetchall(
            """
            SELECT action_id
            FROM bank_actions
            WHERE guild_id = ?
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?;
            """ if self.kind == "sqlite" else
            """
            SELECT action_id
            FROM bank_actions
            WHERE guild_id = %s
            ORDER BY created_at DESC
            OFFSET %s;
            """,
            (int(guild_id), int(limit))
        )
        if not rows:
            return
        to_delete = [r["action_id"] for r in rows]
        if self.kind == "postgres":
            # delete deltas then actions (CASCADE should also handle deltas, but keep explicit)
            assert self._pg_conn is not None
            with self._pg_conn.cursor() as cur:
                cur.execute("DELETE FROM bank_action_deltas WHERE action_id = ANY(%s);", (to_delete,))
                cur.execute("DELETE FROM bank_actions WHERE action_id = ANY(%s);", (to_delete,))
        else:
            assert self._sqlite_conn is not None
            cur = self._sqlite_conn.cursor()
            cur.executemany("DELETE FROM bank_action_deltas WHERE action_id = ?;", [(aid,) for aid in to_delete])
            cur.executemany("DELETE FROM bank_actions WHERE action_id = ?;", [(aid,) for aid in to_delete])
            self._sqlite_conn.commit()
