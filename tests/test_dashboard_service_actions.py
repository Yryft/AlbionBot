from __future__ import annotations

from web.backend.command_bus import CommandContext, StartCompWizardFlow
from albionbot.storage.store import CompRole, CompTemplate, RaidEvent, Store, TicketMessageSnapshot, TicketRecord
import time
from web.backend.schemas import RaidTemplateUpdateRequestDTO, RaidUpdateRequestDTO
from web.backend.services import DashboardService, StartCompWizardFlowHandler


def _build_store(tmp_path):
    path = tmp_path / "state.json"
    store = Store(path=str(path), bank_database_url="", bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    store.templates["zvz"] = CompTemplate(
        name="zvz",
        description="old",
        created_by=1,
        roles=[CompRole(key="dps", label="DPS", slots=5)],
    )
    store.raids["r1"] = RaidEvent(
        raid_id="r1",
        template_name="zvz",
        title="Old raid",
        description="",
        extra_message="",
        start_at=1700000000,
        created_by=1,
    )
    return store


def test_update_template_and_raid(tmp_path):
    service = DashboardService(_build_store(tmp_path))

    updated_tpl = service.update_raid_template(
        "zvz",
        RaidTemplateUpdateRequestDTO(description="new", content_type="pvp", raid_required_role_ids=[], spec="Tank;2\nDps;8"),
    )
    assert updated_tpl.template.name == "zvz"
    assert len(updated_tpl.template.roles) == 2

    updated_raid = service.update_raid(
        "r1",
        RaidUpdateRequestDTO(title="Prime", description="desc", extra_message="extra", start_at=1800000000, prep_minutes=15, cleanup_minutes=20),
    )
    assert updated_raid.title == "Prime"
    assert updated_raid.start_at == 1800000000


def test_apply_bank_split_and_list_balances(tmp_path):
    service = DashboardService(_build_store(tmp_path))

    result = service.apply_bank_action(
        guild_id=10,
        actor_id=99,
        action_type="add_split",
        amount=300,
        target_user_ids=[1, 2, 3],
        note="loot",
    )
    assert result.impacted_users == 3
    balances = service.list_balances(10)
    assert len(balances) == 3
    assert sum(entry.balance for entry in balances) == 300


def test_ticket_transcript_contains_author_metadata(tmp_path):
    store = _build_store(tmp_path)
    store.ticket_records["t1"] = TicketRecord(
        ticket_id="t1",
        guild_id=10,
        owner_user_id=42,
        status="open",
        ticket_type_key="default",
    )
    store.ticket_append_snapshot("t1", TicketMessageSnapshot(
        message_id=123,
        author_id=42,
        author_name="Player42",
        author_avatar_url="https://cdn.example/avatar.png",
        content="hello",
    ))
    service = DashboardService(store)
    transcript = service.get_ticket_transcript(10, "t1")
    assert transcript is not None
    assert transcript.messages[0].author_name == "Player42"
    assert transcript.messages[0].author_avatar_url.endswith("avatar.png")


def test_user_raid_visibility_and_signup_flow(tmp_path):
    store = _build_store(tmp_path)
    store.templates["zvz"].raid_required_role_ids = [77]
    store.templates["zvz"].roles = [
        CompRole(key="tank", label="Tank", slots=1),
        CompRole(key="dps", label="DPS", slots=2),
    ]
    store.raids["r1"].start_at = int(time.time()) + 3600
    service = DashboardService(store)

    assert service.list_user_raids([1]) == []
    assert len(service.list_user_raids([77])) == 1

    roster = service.signup_raid("r1", user_id=10, user_role_ids=[77], role_key="tank", ip=None)
    assert len(roster.participants) == 1
    assert roster.participants[0].status == "main"

    roster = service.signup_raid("r1", user_id=11, user_role_ids=[77], role_key="tank", ip=None)
    assert len(roster.participants) == 2
    assert sorted([p.status for p in roster.participants]) == ["main", "wait"]

    roster = service.leave_raid("r1", user_id=10, user_role_ids=[77])
    assert len(roster.participants) == 1
    assert roster.participants[0].user_id == "11"
    assert roster.participants[0].status == "main"


def test_dashboard_create_ava_template_normalizes_reserved_roles(tmp_path):
    service = DashboardService(_build_store(tmp_path))
    handler = StartCompWizardFlowHandler(service)
    command = StartCompWizardFlow(
        context=CommandContext(guild_id=10, user_id=42, request_id="req-1"),
        template_id="ava",
        description="ava template",
        content_type="ava_raid",
        raid_required_role_ids=[77],
        spec="Raid Leader;9;ip=true;req=999\nDPS;5;ip\nScout;2;req=123456789012345678\nScout;3;req=234567890123456789",
    )

    result = handler.handle(command)

    assert [role.key for role in result.template.roles] == ["raid_leader", "dps", "scout"]
    assert result.template.roles[0].slots == 1
    assert result.template.roles[0].ip_required is False
    assert result.template.roles[0].required_role_ids == []
    assert result.template.roles[-1].slots == 1
    assert result.template.roles[-1].ip_required is False
    assert result.template.roles[-1].required_role_ids == ["123456789012345678"]


def test_dashboard_edit_ava_template_normalizes_reserved_roles(tmp_path):
    service = DashboardService(_build_store(tmp_path))

    updated_tpl = service.update_raid_template(
        "zvz",
        RaidTemplateUpdateRequestDTO(
            description="ava",
            content_type="ava_raid",
            raid_required_role_ids=[],
            spec="Raid Leader;2;ip=true\nTank;2\nScout;4;req=111111111111111111,222222222222222222\nScout;5;req=333333333333333333",
        ),
    )

    assert [role.key for role in updated_tpl.template.roles] == ["raid_leader", "tank", "scout"]
    assert updated_tpl.template.roles[0].slots == 1
    assert updated_tpl.template.roles[0].ip_required is False
    assert updated_tpl.template.roles[0].required_role_ids == []
    assert updated_tpl.template.roles[-1].slots == 1
    assert updated_tpl.template.roles[-1].ip_required is False
    assert updated_tpl.template.roles[-1].required_role_ids == ["111111111111111111", "222222222222222222"]
