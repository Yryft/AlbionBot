from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

from albionbot.modules.raids import parse_comp_spec, raid_status
from albionbot.storage.store import CompTemplate, RaidEvent, Store

from .command_bus import (
    CommandHandler,
    OpenRaidFromTemplate,
    StartCompWizardFlow,
    ValidationError,
)
from .schemas import (
    GuildDTO,
    RaidDTO,
    RaidTemplateDTO,
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
        )
        self.service.store.raids[raid_id] = raid
        self.service.store.save()
        return self.service._to_raid_dto(raid)


@dataclass
class StartCompWizardFlowHandler(CommandHandler[RaidTemplateDTO]):
    service: "DashboardService"

    def handle(self, command: StartCompWizardFlow) -> RaidTemplateDTO:
        roles, warnings = parse_comp_spec(command.spec)
        if warnings and not roles:
            raise ValidationError(code="invalid_spec", message="; ".join(warnings), details={"warnings": warnings})

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
        return self.service.list_raid_templates()[0]


class DashboardService:
    def __init__(self, store: Store):
        self.store = store

    def list_guilds(self) -> List[GuildDTO]:
        guild_ids = set(self.store.ticket_configs.keys())
        guild_ids.update(record.guild_id for record in self.store.ticket_records.values())
        guild_ids.update(self.store.guild_permissions.keys())
        return [GuildDTO(id=gid, name=f"Guild {gid}") for gid in sorted(guild_ids)]

    def get_bot_guild_map(self) -> Dict[int, GuildDTO]:
        guilds = self.list_guilds()
        return {g.id: g for g in guilds}

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
                    created_by=tpl.created_by,
                    created_at=tpl.created_at,
                    raid_required_role_ids=tpl.raid_required_role_ids,
                    roles=[
                        {
                            "key": r.key,
                            "label": r.label,
                            "slots": r.slots,
                            "ip_required": r.ip_required,
                            "required_role_ids": r.required_role_ids,
                        }
                        for r in tpl.roles
                    ],
                )
            )
        return out

    def list_raids(self) -> List[RaidDTO]:
        return [self._to_raid_dto(raid) for raid in sorted(self.store.raids.values(), key=lambda r: r.start_at)]

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
                    message_id=snap.message_id,
                    author_id=snap.author_id,
                    content=snap.content,
                    created_at=snap.created_at,
                    event_type=event_type,
                )
            )

        return TicketTranscriptDTO(
            ticket_id=ticket.ticket_id,
            guild_id=ticket.guild_id,
            owner_user_id=ticket.owner_user_id,
            status=ticket.status,
            ticket_type_key=ticket.ticket_type_key,
            channel_id=ticket.channel_id,
            thread_id=ticket.thread_id,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            messages=messages,
        )

    def _to_raid_dto(self, raid: RaidEvent) -> RaidDTO:
        return RaidDTO(
            raid_id=raid.raid_id,
            template_name=raid.template_name,
            title=raid.title,
            description=raid.description,
            extra_message=raid.extra_message,
            start_at=raid.start_at,
            created_by=raid.created_by,
            created_at=raid.created_at,
            status=raid_status(raid),
        )
