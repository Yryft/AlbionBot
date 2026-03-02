from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RoleDTO(BaseModel):
    id: int
    name: str


class GuildDTO(BaseModel):
    id: int
    name: str
    roles: List[RoleDTO] = Field(default_factory=list)


class TicketMessageDTO(BaseModel):
    message_id: int
    author_id: int
    content: str
    created_at: int
    event_type: Literal["message", "edit", "delete", "system"]


class TicketTranscriptDTO(BaseModel):
    ticket_id: str
    guild_id: int
    owner_user_id: int
    status: Literal["open", "closed", "deleted"]
    ticket_type_key: str
    channel_id: Optional[int] = None
    thread_id: Optional[int] = None
    created_at: int
    updated_at: int
    messages: List[TicketMessageDTO] = Field(default_factory=list)


class RaidRoleDTO(BaseModel):
    key: str
    label: str
    slots: int
    ip_required: bool = False
    required_role_ids: List[int] = Field(default_factory=list)


class RaidTemplateDTO(BaseModel):
    name: str
    description: str
    content_type: Literal["ava_raid", "pvp", "pve"]
    created_by: int
    created_at: int
    raid_required_role_ids: List[int] = Field(default_factory=list)
    roles: List[RaidRoleDTO] = Field(default_factory=list)


class RaidOpenRequestDTO(BaseModel):
    request_id: str
    guild_id: int
    template_name: str
    title: str
    description: str = ""
    extra_message: str = ""
    start_at: int
    prep_minutes: int = 10
    cleanup_minutes: int = 30


class RaidDTO(BaseModel):
    raid_id: str
    template_name: str
    title: str
    description: str
    extra_message: str
    start_at: int
    created_by: int
    created_at: int
    status: Literal["OPEN", "PINGED", "CLOSED"]


class CompTemplateCreateRequestDTO(BaseModel):
    request_id: str
    guild_id: int
    name: str
    description: str = ""
    content_type: Literal["ava_raid", "pvp", "pve"] = "pvp"
    raid_required_role_ids: List[int] = Field(default_factory=list)
    spec: str = Field(description="Spec wizard multi-lignes: Label;slots;options")


class DiscordUserDTO(BaseModel):
    id: str
    username: str
    global_name: Optional[str] = None
    avatar: Optional[str] = None


class DiscordGuildDTO(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    owner: bool = False
    permissions: str = "0"


class MeDTO(BaseModel):
    user: DiscordUserDTO
    selected_guild_id: Optional[int] = None
    guilds: List[DiscordGuildDTO] = Field(default_factory=list)
