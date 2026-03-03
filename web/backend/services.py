from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from albionbot.modules.raids import AVA_RAID, MAX_IP, MIN_IP, count_main_for_role, parse_comp_spec, raid_status, recompute_promotions, role_map
from albionbot.modules.bank import (
    UNDO_WINDOW_SECONDS,
    _now,
    apply_deltas,
    can_apply_deltas,
    compute_split_deltas,
    find_last_action_for_actor,
    make_action_id,
)
from albionbot.storage.store import CompRole, CompTemplate, RaidCommand, RaidEvent, Signup, Store
from albionbot.storage.store import BankAction

from .command_bus import (
    CommandHandler,
    OpenRaidFromTemplate,
    StartCompWizardFlow,
    ValidationError,
)
from .schemas import (
    BalanceEntryDTO,
    BankActionHistoryEntryDTO,
    BankActionResultDTO,
    BankBalanceDTO,
    BankTransferResultDTO,
    BankUndoResultDTO,
    GuildDTO,
    RaidDTO,
    RaidTemplateDTO,
    TemplateMutationResultDTO,
    RaidUpdateRequestDTO,
    RaidTemplateUpdateRequestDTO,
    RaidRosterDTO,
    RaidParticipantDTO,
    TicketMessageDTO,
    TicketTranscriptDTO,
)


@dataclass
class OpenRaidFromTemplateHandler(CommandHandler[RaidDTO]):
    service: "DashboardService"

    def handle(self, command: OpenRaidFromTemplate) -> RaidDTO:
        if command.template_id not in self.service.store.templates:
            raise ValidationError(code="template_not_found", message="Template introuvable")

        raid_id = uuid.uuid4().hex[:10]
        raid = RaidEvent(
            raid_id=raid_id,
            template_name=command.template_id,
            title=command.title,
            description=command.description,
            extra_message=command.extra_message,
            start_at=command.start_at,
            created_by=command.context.user_id,
            created_at=int(time.time()),
            prep_minutes=command.prep_minutes,
            cleanup_minutes=command.cleanup_minutes,
            channel_id=command.channel_id,
            voice_channel_id=command.voice_channel_id,
        )
        self.service.store.raids[raid_id] = raid
        now = int(time.time())
        command_id = f"open_raid_from_template:{raid_id}"
        self.service.store.raid_commands[command_id] = RaidCommand(
            command_id=command_id,
            command_type="open_raid_from_template",
            raid_id=raid_id,
            status="pending",
            payload={"channel_id": int(command.channel_id)},
            attempts=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        self.service.store.save()
        return self.service._to_raid_dto(raid)


@dataclass
class StartCompWizardFlowHandler(CommandHandler[TemplateMutationResultDTO]):
    service: "DashboardService"

    def handle(self, command: StartCompWizardFlow) -> TemplateMutationResultDTO:
        roles, warnings, errors = self.service.parse_template_spec(command.spec)
        if errors:
            raise ValidationError(
                code="invalid_spec",
                message="; ".join(errors),
                details={"warnings": warnings, "errors": errors},
            )

        if command.content_type == AVA_RAID:
            roles = self.service.normalize_ava_roles(roles)

        template = CompTemplate(
            name=command.template_id,
            description=command.description,
            created_by=command.context.user_id,
            content_type=command.content_type,
            raid_required_role_ids=command.raid_required_role_ids,
            roles=roles,
        )
        self.service.store.templates[command.template_id] = template
        self.service.store.save()
        dto = next(tpl for tpl in self.service.list_raid_templates() if tpl.name == command.template_id)
        return TemplateMutationResultDTO(template=dto, spec_warnings=warnings, spec_errors=[])


class DashboardService:
    def __init__(self, store: Store, bank_allow_negative: bool = True):
        self.store = store
        self.bank_allow_negative = bool(bank_allow_negative)

    def list_guilds(self) -> List[GuildDTO]:
        guild_ids = set(self.store.ticket_configs.keys())
        guild_ids.update(record.guild_id for record in self.store.ticket_records.values())
        guild_ids.update(self.store.guild_permissions.keys())
        return [GuildDTO(id=str(gid), name=f"Guild {gid}") for gid in sorted(guild_ids)]

    def get_bot_guild_map(self) -> Dict[int, GuildDTO]:
        guilds = self.list_guilds()
        return {int(g.id): g for g in guilds}

    def list_ticket_transcripts(self, guild_id: int) -> List[TicketTranscriptDTO]:
        rows: List[TicketTranscriptDTO] = []
        for ticket in sorted(self.store.ticket_records.values(), key=lambda t: t.updated_at, reverse=True):
            if ticket.guild_id != int(guild_id):
                continue
            rows.append(self._to_ticket_transcript(ticket))
        return rows

    def get_ticket_transcript(self, guild_id: int, ticket_id: str) -> Optional[TicketTranscriptDTO]:
        ticket = self.store.ticket_records.get(ticket_id)
        if ticket is None or ticket.guild_id != int(guild_id):
            return None
        return self._to_ticket_transcript(ticket)

    def list_raid_templates(self) -> List[RaidTemplateDTO]:
        out: List[RaidTemplateDTO] = []
        for tpl in sorted(self.store.templates.values(), key=lambda t: t.created_at, reverse=True):
            out.append(
                RaidTemplateDTO(
                    name=tpl.name,
                    description=tpl.description,
                    content_type=tpl.content_type,
                    created_by=str(tpl.created_by),
                    created_at=tpl.created_at,
                    raid_required_role_ids=[str(role_id) for role_id in tpl.raid_required_role_ids],
                    roles=[
                        {
                            "key": r.key,
                            "label": r.label,
                            "slots": r.slots,
                            "ip_required": r.ip_required,
                            "required_role_ids": [str(role_id) for role_id in r.required_role_ids],
                        }
                        for r in tpl.roles
                    ],
                )
            )
        return out

    def list_raids(self) -> List[RaidDTO]:
        return [self._to_raid_dto(raid) for raid in sorted(self.store.raids.values(), key=lambda r: r.start_at)]

    def list_user_raids(self, user_role_ids: List[int], include_all: bool = False) -> List[RaidDTO]:
        visible: List[RaidDTO] = []
        for raid in self.store.raids.values():
            tpl = self.store.templates.get(raid.template_name)
            if tpl is None:
                continue
            if not include_all and tpl.raid_required_role_ids and not set(user_role_ids).intersection(set(tpl.raid_required_role_ids)):
                continue
            visible.append(self._to_raid_dto(raid))
        return sorted(visible, key=lambda r: r.start_at, reverse=True)

    def get_raid_roster(self, raid_id: str, user_role_ids: List[int]) -> RaidRosterDTO:
        raid = self.store.raids.get(raid_id)
        if raid is None:
            raise ValidationError(code="raid_not_found", message="Raid introuvable")
        tpl = self.store.templates.get(raid.template_name)
        if tpl is None:
            raise ValidationError(code="template_not_found", message="Template introuvable")
        if tpl.raid_required_role_ids and not set(user_role_ids).intersection(set(tpl.raid_required_role_ids)):
            raise ValidationError(code="forbidden_raid", message="Accès raid refusé")

        participants = [
            RaidParticipantDTO(
                user_id=str(s.user_id),
                role_key=s.role_key,
                status=s.status,
                ip=s.ip,
                joined_at=s.joined_at,
            )
            for s in sorted(raid.signups.values(), key=lambda x: (x.role_key, x.status, x.joined_at))
        ]
        return RaidRosterDTO(
            raid=self._to_raid_dto(raid),
            participants=participants,
            absent_user_ids=[str(user_id) for user_id in sorted(raid.absent)],
        )

    def signup_raid(self, raid_id: str, user_id: int, user_role_ids: List[int], role_key: str, ip: Optional[int]) -> RaidRosterDTO:
        raid = self.store.raids.get(raid_id)
        if raid is None:
            raise ValidationError(code="raid_not_found", message="Raid introuvable")
        tpl = self.store.templates.get(raid.template_name)
        if tpl is None:
            raise ValidationError(code="template_not_found", message="Template introuvable")
        if raid.ping_done or raid.cleanup_done or int(time.time()) >= raid.start_at:
            raise ValidationError(code="signups_closed", message="Inscriptions fermées")
        if tpl.raid_required_role_ids and not set(user_role_ids).intersection(set(tpl.raid_required_role_ids)):
            raise ValidationError(code="forbidden_raid", message="Accès raid refusé")

        rm = role_map(tpl)
        role_def = rm.get(role_key)
        if role_def is None:
            raise ValidationError(code="invalid_role", message="Rôle invalide")
        if role_key == "raid_leader":
            raise ValidationError(code="reserved_role", message="Rôle réservé")
        if role_def.required_role_ids and not set(user_role_ids).intersection(set(role_def.required_role_ids)):
            raise ValidationError(code="forbidden_role", message="Rôle non autorisé")
        if role_def.ip_required:
            if ip is None:
                raise ValidationError(code="ip_required", message="IP requis")
            if ip < MIN_IP or ip > MAX_IP:
                raise ValidationError(code="invalid_ip", message="IP invalide")
        else:
            ip = None

        cur = raid.signups.get(user_id)
        if cur and cur.role_key == "raid_leader" and role_key != "raid_leader":
            raise ValidationError(code="reserved_role", message="Raid leader verrouillé")

        main_count = count_main_for_role(raid, role_key)
        status = "main" if main_count < role_def.slots else "wait"
        raid.absent.discard(user_id)
        raid.signups[user_id] = Signup(user_id=user_id, role_key=role_key, status=status, ip=ip, joined_at=int(time.time()))
        recompute_promotions(raid, tpl)
        self.store.save()
        return self.get_raid_roster(raid_id, user_role_ids)

    def leave_raid(self, raid_id: str, user_id: int, user_role_ids: List[int]) -> RaidRosterDTO:
        raid = self.store.raids.get(raid_id)
        if raid is None:
            raise ValidationError(code="raid_not_found", message="Raid introuvable")
        tpl = self.store.templates.get(raid.template_name)
        if tpl is None:
            raise ValidationError(code="template_not_found", message="Template introuvable")
        changed = False
        if user_id in raid.signups:
            if raid.signups[user_id].role_key == "raid_leader":
                raise ValidationError(code="reserved_role", message="Raid leader ne peut pas quitter")
            del raid.signups[user_id]
            changed = True
        if user_id in raid.absent:
            raid.absent.discard(user_id)
            changed = True
        if not changed:
            raise ValidationError(code="not_signed", message="Aucune inscription à retirer")
        recompute_promotions(raid, tpl)
        self.store.save()
        return self.get_raid_roster(raid_id, user_role_ids)

    def delete_raid(self, raid_id: str) -> None:
        raid = self.store.raids.get(raid_id)
        if raid is None:
            raise ValidationError(code="raid_not_found", message="Raid introuvable")
        del self.store.raids[raid_id]
        self.store.save()

    def delete_ticket_transcript(self, guild_id: int, ticket_id: str) -> None:
        ticket = self.store.ticket_records.get(ticket_id)
        if ticket is None or ticket.guild_id != int(guild_id):
            raise ValidationError(code="ticket_not_found", message="Ticket introuvable")
        self.store.ticket_records.pop(ticket_id, None)
        self.store.ticket_messages.pop(ticket_id, None)
        self.store.save()

    def update_raid_template(self, template_name: str, payload: RaidTemplateUpdateRequestDTO) -> TemplateMutationResultDTO:
        template = self.store.templates.get(template_name)
        if template is None:
            raise ValidationError(code="template_not_found", message="Template introuvable")
        roles, warnings, errors = self.parse_template_spec(payload.spec)
        if errors:
            raise ValidationError(
                code="invalid_spec",
                message="; ".join(errors),
                details={"warnings": warnings, "errors": errors},
            )
        template.description = payload.description
        template.content_type = payload.content_type
        template.raid_required_role_ids = payload.raid_required_role_ids
        if payload.content_type == AVA_RAID:
            roles = self.normalize_ava_roles(roles)
        template.roles = roles
        self.store.save()
        dto = next(tpl for tpl in self.list_raid_templates() if tpl.name == template_name)
        return TemplateMutationResultDTO(template=dto, spec_warnings=warnings, spec_errors=[])

    def delete_raid_template(self, template_name: str) -> None:
        template = self.store.templates.get(template_name)
        if template is None:
            raise ValidationError(code="template_not_found", message="Template introuvable")
        self.store.templates.pop(template.name, None)
        self.store.save()

    @staticmethod
    def _is_ava_reserved_role(role: CompRole) -> bool:
        normalized_key = role.key.strip().lower()
        normalized_label = role.label.strip().lower().replace(" ", "_")
        return (
            normalized_key in {"raid_leader", "scout"}
            or normalized_key.startswith("raid_leader_")
            or normalized_key.startswith("scout_")
            or normalized_label in {"raid_leader", "scout"}
        )

    def normalize_ava_roles(self, roles: List[CompRole]) -> List[CompRole]:
        scout_required_role_ids: List[int] = []
        for role in roles:
            if self._is_ava_reserved_role(role) and role.key.strip().lower().startswith("scout"):
                scout_required_role_ids = list(role.required_role_ids)
                break

        filtered_roles = [role for role in roles if not self._is_ava_reserved_role(role)]
        forced_roles = [
            CompRole(key="raid_leader", label="Raid Leader", slots=1, ip_required=False, required_role_ids=[]),
            CompRole(key="scout", label="Scout", slots=1, ip_required=False, required_role_ids=scout_required_role_ids),
        ]
        return [forced_roles[0]] + filtered_roles + [forced_roles[1]]

    def update_raid(self, raid_id: str, payload: RaidUpdateRequestDTO) -> RaidDTO:
        raid = self.store.raids.get(raid_id)
        if raid is None:
            raise ValidationError(code="raid_not_found", message="Raid introuvable")
        raid.title = payload.title
        raid.description = payload.description
        raid.extra_message = payload.extra_message
        raid.start_at = payload.start_at
        raid.prep_minutes = payload.prep_minutes
        raid.cleanup_minutes = payload.cleanup_minutes
        self.store.save()
        return self._to_raid_dto(raid)

    def close_raid(self, raid_id: str) -> RaidDTO:
        raid = self.store.raids.get(raid_id)
        if raid is None:
            raise ValidationError(code="raid_not_found", message="Raid introuvable")
        raid.ping_done = True
        self.store.save()
        return self._to_raid_dto(raid)

    def list_balances(self, guild_id: int) -> List[BalanceEntryDTO]:
        rows, _ = self.store.bank_get_leaderboard(guild_id, limit=500, offset=0)
        return [BalanceEntryDTO(user_id=str(user_id), balance=balance, rank=index + 1) for index, (user_id, balance) in enumerate(rows)]

    def apply_bank_action(self, guild_id: int, actor_id: int, action_type: str, amount: int, target_user_ids: List[int], note: str) -> BankActionResultDTO:
        if not target_user_ids:
            raise ValidationError(code="targets_required", message="Aucune cible fournie")
        split = action_type in {"add_split", "remove_split"}
        sign = +1 if action_type in {"add", "add_split"} else -1
        if split:
            deltas = compute_split_deltas(amount, target_user_ids, sign)
        else:
            deltas = {uid: sign * amount for uid in target_user_ids}
        ok, reason = can_apply_deltas(self.store, guild_id, deltas, allow_negative=self.bank_allow_negative)
        if not ok:
            raise ValidationError(code="insufficient_balance", message=reason)
        apply_deltas(self.store, guild_id, deltas)
        action = BankAction(
            action_id=make_action_id(),
            guild_id=guild_id,
            actor_id=actor_id,
            created_at=int(time.time()),
            action_type=action_type,
            deltas=deltas,
            note=note.strip(),
        )
        self.store.bank_append_action(action)
        self.store.save()
        return BankActionResultDTO(
            action_id=action.action_id,
            guild_id=str(guild_id),
            action_type=action_type,
            total_delta=sum(deltas.values()),
            impacted_users=len(deltas),
            note=action.note,
        )

    def get_balance(self, guild_id: int, user_id: int) -> BankBalanceDTO:
        return BankBalanceDTO(guild_id=str(guild_id), user_id=str(user_id), balance=self.store.bank_get_balance(guild_id, user_id))

    def transfer_balance(self, guild_id: int, from_user_id: int, to_user_id: int, amount: int, note: str) -> BankTransferResultDTO:
        if amount <= 0:
            raise ValidationError(code="invalid_amount", message="Montant invalide")
        if from_user_id == to_user_id:
            raise ValidationError(code="invalid_target", message="Impossible de se transférer à soi-même")

        deltas = {from_user_id: -int(amount), to_user_id: int(amount)}
        ok, reason = can_apply_deltas(self.store, guild_id, deltas, allow_negative=False)
        if not ok:
            raise ValidationError(code="insufficient_balance", message=reason)

        apply_deltas(self.store, guild_id, deltas)
        self.store.save()
        return BankTransferResultDTO(
            guild_id=str(guild_id),
            from_user_id=str(from_user_id),
            to_user_id=str(to_user_id),
            amount=int(amount),
            note=note.strip(),
        )

    def undo_last_bank_action(self, guild_id: int, actor_id: int) -> BankUndoResultDTO:
        action = find_last_action_for_actor(self.store, guild_id, actor_id)
        if action is None:
            raise ValidationError(code="undo_not_found", message="Aucune action annulable trouvée")

        age = _now() - action.created_at
        if age > UNDO_WINDOW_SECONDS:
            raise ValidationError(code="undo_window_expired", message="Fenêtre d'undo dépassée (15 min)")

        reverse = {uid: -delta for uid, delta in action.deltas.items()}
        ok, reason = can_apply_deltas(self.store, guild_id, reverse, allow_negative=self.bank_allow_negative)
        if not ok:
            raise ValidationError(code="undo_insufficient_balance", message=reason)

        apply_deltas(self.store, guild_id, reverse)
        undone_at = _now()
        self.store.bank_mark_action_undone(action.action_id, undone_at)
        self.store.save()

        return BankUndoResultDTO(
            action_id=action.action_id,
            guild_id=str(guild_id),
            action_type=action.action_type,
            undone_at=undone_at,
        )

    def list_bank_action_history(self, guild_id: int, limit: int = 25) -> List[BankActionHistoryEntryDTO]:
        actions = self.store.bank_list_actions(guild_id, limit=max(1, int(limit)))
        out: List[BankActionHistoryEntryDTO] = []
        for action in actions:
            out.append(
                BankActionHistoryEntryDTO(
                    action_id=action.action_id,
                    guild_id=str(action.guild_id),
                    actor_id=str(action.actor_id),
                    created_at=action.created_at,
                    action_type=action.action_type,
                    total_delta=sum(action.deltas.values()),
                    impacted_users=len(action.deltas),
                    note=action.note,
                    undone=action.undone,
                    undone_at=action.undone_at,
                )
            )
        return out

    def _to_ticket_transcript(self, ticket) -> TicketTranscriptDTO:
        messages = []
        for snap in self.store.ticket_get_transcript(ticket.ticket_id):
            event_type = "message"
            if snap.content.startswith("[EDIT]"):
                event_type = "edit"
            elif snap.content.startswith("[DELETE]"):
                event_type = "delete"
            elif snap.content.startswith("[CLOSE_REASON]"):
                event_type = "system"
            messages.append(
                TicketMessageDTO(
                    message_id=str(snap.message_id),
                    author_id=str(snap.author_id),
                    author_name=snap.author_name,
                    author_avatar_url=snap.author_avatar_url,
                    content=snap.content,
                    created_at=snap.created_at,
                    event_type=event_type,
                    embeds=snap.embeds,
                    attachments=snap.attachments,
                )
            )

        return TicketTranscriptDTO(
            ticket_id=ticket.ticket_id,
            guild_id=str(ticket.guild_id),
            owner_user_id=str(ticket.owner_user_id),
            status=ticket.status,
            ticket_type_key=ticket.ticket_type_key,
            channel_id=str(ticket.channel_id) if ticket.channel_id is not None else None,
            thread_id=str(ticket.thread_id) if ticket.thread_id is not None else None,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            messages=messages,
        )

    def _to_raid_dto(self, raid: RaidEvent) -> RaidDTO:
        command = next(
            (
                cmd
                for cmd in self.store.raid_commands.values()
                if cmd.raid_id == raid.raid_id and cmd.command_type == "open_raid_from_template"
            ),
            None,
        )
        publish_status = command.status if command is not None else ("delivered" if raid.message_id else "pending")
        publish_error = command.last_error if command is not None else ""
        return RaidDTO(
            raid_id=raid.raid_id,
            template_name=raid.template_name,
            title=raid.title,
            description=raid.description,
            extra_message=raid.extra_message,
            start_at=raid.start_at,
            created_by=str(raid.created_by),
            created_at=raid.created_at,
            channel_id=str(raid.channel_id) if raid.channel_id is not None else None,
            message_id=str(raid.message_id) if raid.message_id is not None else None,
            voice_channel_id=str(raid.voice_channel_id) if raid.voice_channel_id is not None else None,
            status=raid_status(raid),
            publish_status=publish_status,
            publish_error=publish_error,
        )
    @staticmethod
    def parse_template_spec(spec: str) -> tuple[list, list[str], list[str]]:
        roles, raw_warnings = parse_comp_spec(spec)
        errors: list[str] = []
        warnings: list[str] = []
        for message in raw_warnings:
            if message.startswith("Ligne") and ("format invalide" in message or "slots invalide" in message):
                errors.append(message)
            elif message in {"Spec vide.", "Aucun rôle valide."}:
                errors.append(message)
            else:
                warnings.append(message)
        return roles, warnings, errors
