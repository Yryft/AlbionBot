from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RoleDTO(BaseModel):
    id: str
    name: str


class GuildDTO(BaseModel):
    id: str
    name: str
    roles: List[RoleDTO] = Field(default_factory=list)


class TicketMessageDTO(BaseModel):
    message_id: str
    author_id: str
    author_name: str = ""
    author_avatar_url: str = ""
    content: str
    created_at: int
    event_type: Literal["message", "edit", "delete", "system"]
    embeds: List[dict] = Field(default_factory=list)
    attachments: List[dict] = Field(default_factory=list)


class TicketTranscriptDTO(BaseModel):
    ticket_id: str
    guild_id: str
    owner_user_id: str
    status: Literal["open", "closed", "deleted"]
    ticket_type_key: str
    channel_id: Optional[str] = None
    thread_id: Optional[str] = None
    created_at: int
    updated_at: int
    messages: List[TicketMessageDTO] = Field(default_factory=list)


class RaidRoleDTO(BaseModel):
    key: str
    label: str
    slots: int
    ip_required: bool = False
    required_role_ids: List[str] = Field(default_factory=list)


class RaidTemplateDTO(BaseModel):
    name: str
    description: str
    content_type: Literal["ava_raid", "pvp", "pve"]
    created_by: str
    created_at: int
    raid_required_role_ids: List[str] = Field(default_factory=list)
    roles: List[RaidRoleDTO] = Field(default_factory=list)


class TemplateMutationResultDTO(BaseModel):
    template: RaidTemplateDTO
    spec_warnings: List[str] = Field(default_factory=list)
    spec_errors: List[str] = Field(default_factory=list)


class RaidOpenRequestDTO(BaseModel):
    request_id: str
    guild_id: str
    channel_id: str = Field(min_length=1)
    voice_channel_id: Optional[str] = Field(default=None, min_length=1)
    template_name: str
    title: str
    description: str = ""
    extra_message: str = ""
    start_at: int
    prep_minutes: int = 10
    cleanup_minutes: int = 30




class RaidOpenPreviewRequestDTO(BaseModel):
    guild_id: str
    template_name: str
    title: str
    description: str = ""
    extra_message: str = ""
    start_at: int


class RaidOpenPreviewComponentDTO(BaseModel):
    kind: Literal["select", "button"]
    label: str


class RaidOpenPreviewDTO(BaseModel):
    embed: dict
    components: List[RaidOpenPreviewComponentDTO] = Field(default_factory=list)
class RaidDTO(BaseModel):
    raid_id: str
    template_name: str
    title: str
    description: str
    extra_message: str
    start_at: int
    created_by: str
    created_at: int
    channel_id: Optional[str] = None
    message_id: Optional[str] = None
    voice_channel_id: Optional[str] = None
    status: Literal["OPEN", "PINGED", "CLOSED"]
    publish_status: Literal["pending", "delivered", "failed"] = "pending"
    publish_error: str = ""



class RaidParticipantDTO(BaseModel):
    user_id: str
    role_key: str
    status: Literal["main", "wait"]
    ip: Optional[int] = None
    joined_at: int


class RaidRosterDTO(BaseModel):
    raid: RaidDTO
    participants: List[RaidParticipantDTO] = Field(default_factory=list)
    absent_user_ids: List[str] = Field(default_factory=list)


class RaidSignupRequestDTO(BaseModel):
    role_key: str
    ip: Optional[int] = None


class CompTemplateCreateRequestDTO(BaseModel):
    request_id: str
    guild_id: str
    name: str
    description: str = ""
    content_type: Literal["ava_raid", "pvp", "pve"] = "pvp"
    raid_required_role_ids: List[str] = Field(default_factory=list)
    spec: str = Field(description="Spec wizard multi-lignes: Label;slots;options")


class RaidTemplateUpdateRequestDTO(BaseModel):
    description: str = ""
    content_type: Literal["ava_raid", "pvp", "pve"] = "pvp"
    raid_required_role_ids: List[str] = Field(default_factory=list)
    spec: str = Field(description="Spec wizard multi-lignes: Label;slots;options")


class RaidUpdateRequestDTO(BaseModel):
    title: str
    description: str = ""
    extra_message: str = ""
    start_at: int
    prep_minutes: int = 10
    cleanup_minutes: int = 30


class RaidStateUpdateRequestDTO(BaseModel):
    action: Literal["close"]


class BalanceEntryDTO(BaseModel):
    user_id: str
    balance: int
    rank: int = 0


class BankActionRequestDTO(BaseModel):
    request_id: str
    guild_id: str
    action_type: Literal["add", "remove", "add_split", "remove_split"]
    amount: int = Field(ge=0)
    target_user_ids: List[str] = Field(default_factory=list)
    note: str = ""


class BankActionResultDTO(BaseModel):
    action_id: str
    guild_id: str
    action_type: Literal["add", "remove", "add_split", "remove_split"]
    total_delta: int
    impacted_users: int
    note: str = ""


class BankUndoRequestDTO(BaseModel):
    guild_id: str


class BankUndoResultDTO(BaseModel):
    action_id: str
    guild_id: str
    action_type: Literal["add", "remove", "add_split", "remove_split"]
    undone_at: int


class BankTransferRequestDTO(BaseModel):
    guild_id: str
    to_user_id: str
    amount: int = Field(gt=0)
    note: str = ""


class BankTransferResultDTO(BaseModel):
    guild_id: str
    from_user_id: str
    to_user_id: str
    amount: int
    note: str = ""


class BankBalanceDTO(BaseModel):
    guild_id: str
    user_id: str
    balance: int


class BankActionHistoryEntryDTO(BaseModel):
    action_id: str
    guild_id: str
    actor_id: str
    created_at: int
    action_type: Literal["add", "remove", "add_split", "remove_split"]
    total_delta: int
    impacted_users: int
    note: str = ""
    undone: bool = False
    undone_at: Optional[int] = None


class DiscordUserDTO(BaseModel):
    id: str
    username: str
    global_name: Optional[str] = None
    avatar: Optional[str] = None


class DiscordGuildDTO(BaseModel):
    id: str
    name: str
    icon: Optional[str] = None
    owner: bool = False
    permissions: str = "0"


class MeDTO(BaseModel):
    user: DiscordUserDTO
    csrf_token: str
    selected_guild_id: Optional[str] = None
    guilds: List[DiscordGuildDTO] = Field(default_factory=list)


class DiscordChannelDTO(BaseModel):
    id: str
    name: str
    type: int


class DiscordMemberDTO(BaseModel):
    id: str
    display_name: str


class DiscordDirectoryDTO(BaseModel):
    channels: List[DiscordChannelDTO] = Field(default_factory=list)
    roles: List[RoleDTO] = Field(default_factory=list)
    members: List[DiscordMemberDTO] = Field(default_factory=list)


class GuildPermissionBindingDTO(BaseModel):
    permission_key: Literal["raid_manager", "bank_manager", "ticket_manager"]
    role_ids: List[str] = Field(default_factory=list)
    user_ids: List[str] = Field(default_factory=list)


class GuildPermissionUpdateRequestDTO(BaseModel):
    role_ids: List[str] = Field(default_factory=list)
    user_ids: List[str] = Field(default_factory=list)


class CraftItemDTO(BaseModel):
    id: str
    name: str
    tier: int
    enchant: int
    icon: str
    category: str
    craftable: bool


class CraftRecipeMaterialDTO(BaseModel):
    item_id: str
    item_name: str
    quantity: int


class CraftItemDetailDTO(BaseModel):
    item: CraftItemDTO
    recipe: List[CraftRecipeMaterialDTO] = Field(default_factory=list)
    recipes: List[List[CraftRecipeMaterialDTO]] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)




class CraftFocusCostUpsertEntryDTO(BaseModel):
    item_id: str = Field(min_length=1)
    base_focus_cost: int = Field(gt=0)
    tier: int | None = None
    enchant: int | None = None
    source: str = Field(default="manual", min_length=1)


class CraftFocusCostBulkUpsertRequestDTO(BaseModel):
    entries: List[CraftFocusCostUpsertEntryDTO] = Field(default_factory=list, min_length=1, max_length=1000)


class CraftFocusCostEntryDTO(BaseModel):
    item_id: str
    base_focus_cost: int
    tier: int | None = None
    enchant: int | None = None
    source: str
    updated_at: int

class CraftSimulationRequestDTO(BaseModel):
    item_id: str
    recipe_index: int | None = None
    enchantment_level: int = Field(default=0, ge=0, le=4)
    quantity: int = Field(gt=0, le=100000)
    category_mastery_level: int = Field(ge=0, le=100)
    category_specializations: dict[str, int] = Field(default_factory=dict)
    item_specializations: dict[str, int] = Field(default_factory=dict)
    location_key: str = Field(default="none", min_length=1)
    city_key: str | None = None
    hideout_biome_key: str | None = None
    hideout_territory_level: int | None = Field(default=None, ge=1, le=9)
    hideout_zone_quality: int | None = Field(default=None, ge=1, le=6)
    available_focus: int = Field(ge=0)
    use_focus: bool = True


class CraftSpecializationItemDTO(BaseModel):
    item_id: str
    item_name: str
    icon: str
    tier: int


class CraftSpecializationsDTO(BaseModel):
    category: str
    category_id: str | None = None
    category_mastery_item_id: str
    category_mastery_icon: str
    items: List[CraftSpecializationItemDTO] = Field(default_factory=list)


class CraftCategoryPresetDTO(BaseModel):
    category_mastery_level: int = Field(default=0, ge=0, le=100)
    item_specializations: dict[str, int] = Field(default_factory=dict)




class CraftUserPreferencesDTO(BaseModel):
    item_id: str | None = None
    enchantment_level: int = Field(default=0, ge=0, le=4)
    quantity: int = Field(default=1, ge=1, le=100000)
    category_mastery_level: int = Field(default=0, ge=0, le=100)
    target_specialization_level: int = Field(default=0, ge=0, le=100)
    location_key: str = Field(default="none", min_length=1)
    city_key: str | None = None
    hideout_biome_key: str | None = None
    hideout_territory_level: int | None = Field(default=None, ge=1, le=9)
    hideout_zone_quality: int | None = Field(default=None, ge=1, le=6)
    available_focus: int = Field(default=0, ge=0)
    use_focus: bool = True
    tax_rate: float = Field(default=6.5, ge=0.0, le=100.0)
    focus_unit_price: float = Field(default=0.0, ge=0.0)
    journal_unit_price: float = Field(default=0.0, ge=0.0)
    sale_unit_price: float = Field(default=0.0, ge=0.0)
    station_fee_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    pricing_mode: str = Field(default="manual", min_length=1)
    category_presets: dict[str, CraftCategoryPresetDTO] = Field(default_factory=dict)

class CraftSimulationMaterialDTO(BaseModel):
    item_id: str
    item_name: str
    icon: str = ""
    gross_quantity: int
    net_quantity: int


class CraftSimulationResultDTO(BaseModel):
    item_id: str
    category_id: str | None = None
    fce: int = 0
    focus_efficiency: float
    focus_per_item: int
    total_focus: int
    items_craftable_with_available_focus: int
    base_materials: List[CraftSimulationMaterialDTO] = Field(default_factory=list)
    intermediate_materials: List[CraftSimulationMaterialDTO] = Field(default_factory=list)
    applied_yields: dict = Field(default_factory=dict)
    recipe_index: int = 0
    available_recipes: int = 1
    warnings: List[str] = Field(default_factory=list)


class CraftProfitabilityPricingMode(str, Enum):
    manual = "manual"
    prefilled = "prefilled"


class CraftProfitabilityRequestDTO(BaseModel):
    simulation: CraftSimulationResultDTO
    material_unit_prices: dict[str, float] = Field(default_factory=dict)
    imbuer_journal_unit_price: float = Field(default=0.0, ge=0)
    item_sale_unit_price: float = Field(ge=0)
    crafted_quantity: int = Field(gt=0, le=100000)
    market_tax_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    station_fee_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    focus_unit_price: float = Field(default=0.0, ge=0)
    include_focus_cost: bool = True
    pricing_mode: CraftProfitabilityPricingMode = CraftProfitabilityPricingMode.manual


class CraftProfitabilityLineDTO(BaseModel):
    item_id: str
    item_name: str
    quantity: int
    unit_price: float
    total_cost: float
    source: str = "manual"


class CraftProfitabilityResultDTO(BaseModel):
    simulation: CraftSimulationResultDTO
    pricing_mode: CraftProfitabilityPricingMode
    material_lines: List[CraftProfitabilityLineDTO] = Field(default_factory=list)
    total_material_cost: float
    focus_cost: float
    imbuer_journal_cost: float
    total_cost: float
    gross_revenue: float
    market_tax_amount: float
    station_fee_amount: float
    net_revenue: float
    profit: float
    margin_pct: float
