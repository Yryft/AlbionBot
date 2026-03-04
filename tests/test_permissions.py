import unittest

from albionbot.config import Config
from albionbot.storage.store import Store
from albionbot.utils.permissions import PERM_RAID_MANAGER, has_logical_permission


class PermissionLayerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(
            discord_token="x",
            guild_ids=[],
            data_path="data/state.json",
            bank_database_url="",
            bank_sqlite_path="data/bank.sqlite3",
            raid_require_manage_guild=True,
            raid_manager_role_id=None,
            bank_require_manage_guild=True,
            bank_manager_role_id=None,
            support_role_id=None,
            ticket_admin_role_id=None,
            bank_allow_negative=True,
            sched_tick_seconds=15,
            default_prep_minutes=10,
            default_cleanup_minutes=30,
            voice_check_after_minutes=5,
        )
        self.store = Store(path=":memory:", bank_sqlite_path=":memory:")
        self.guild_id = 123
        self.manager_role = 987
        self.store.set_permission_role_ids(self.guild_id, PERM_RAID_MANAGER, [self.manager_role])

    def test_admin_authorized(self):
        allowed = has_logical_permission(
            self.cfg,
            self.store,
            self.guild_id,
            PERM_RAID_MANAGER,
            role_ids=[],
            is_admin=True,
            can_manage_guild=False,
        )
        self.assertTrue(allowed)

    def test_member_forbidden_without_role(self):
        allowed = has_logical_permission(
            self.cfg,
            self.store,
            self.guild_id,
            PERM_RAID_MANAGER,
            role_ids=[111],
            is_admin=False,
            can_manage_guild=False,
        )
        self.assertFalse(allowed)

    def test_member_allowed_with_direct_user_permission(self):
        allowed_user_id = 4444
        self.store.set_permission_user_ids(self.guild_id, PERM_RAID_MANAGER, [allowed_user_id])
        allowed = has_logical_permission(
            self.cfg,
            self.store,
            self.guild_id,
            PERM_RAID_MANAGER,
            role_ids=[111],
            user_id=allowed_user_id,
            is_admin=False,
            can_manage_guild=False,
        )
        self.assertTrue(allowed)

    def test_role_removed_forbidden(self):
        self.store.set_permission_role_ids(self.guild_id, PERM_RAID_MANAGER, [555])
        allowed = has_logical_permission(
            self.cfg,
            self.store,
            self.guild_id,
            PERM_RAID_MANAGER,
            role_ids=[self.manager_role],
            is_admin=False,
            can_manage_guild=False,
        )
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
