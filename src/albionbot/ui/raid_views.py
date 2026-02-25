import nextcord
from nextcord.ext import commands
from typing import List

from ..storage.store import RaidEvent, CompTemplate
from ..utils.text import limit_str

class IpModal(nextcord.ui.Modal):
    def __init__(self, *, bot: commands.Bot, raid_id: str, role_key: str, role_label: str, on_submit):
        super().__init__(title=f"IP requis — {role_label}", timeout=180)
        self.bot = bot
        self.raid_id = raid_id
        self.role_key = role_key
        self.on_submit_cb = on_submit

        self.ip_input = nextcord.ui.TextInput(
            label="IP de ton arme",
            placeholder="Ex: 1750",
            min_length=1,
            max_length=4,
            required=True,
        )
        self.add_item(self.ip_input)

    async def callback(self, interaction: nextcord.Interaction):
        await self.on_submit_cb(interaction, self.raid_id, self.role_key, str(self.ip_input.value).strip())

class RoleSelect(nextcord.ui.Select):
    def __init__(self, *, bot: commands.Bot, raid_id: str, options: List[nextcord.SelectOption], page: int, pages: int, disabled: bool, on_select):
        self.bot = bot
        self.raid_id = raid_id
        self.on_select_cb = on_select
        super().__init__(
            placeholder=f"S'inscrire — choisir un rôle (page {page}/{pages})",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"raid:{raid_id}:select:{page}",
            disabled=disabled,
        )

    async def callback(self, interaction: nextcord.Interaction):
        await self.on_select_cb(interaction, self.raid_id, self.values[0])

class AbsentButton(nextcord.ui.Button):
    def __init__(self, *, bot: commands.Bot, raid_id: str, disabled: bool, on_click):
        super().__init__(label="Absent (toggle)", style=nextcord.ButtonStyle.secondary, custom_id=f"raid:{raid_id}:absent", disabled=disabled)
        self.bot = bot
        self.raid_id = raid_id
        self.on_click_cb = on_click

    async def callback(self, interaction: nextcord.Interaction):
        await self.on_click_cb(interaction, self.raid_id)

class LeaveButton(nextcord.ui.Button):
    def __init__(self, *, bot: commands.Bot, raid_id: str, disabled: bool, on_click):
        super().__init__(label="Leave", style=nextcord.ButtonStyle.secondary, custom_id=f"raid:{raid_id}:leave", disabled=disabled)
        self.bot = bot
        self.raid_id = raid_id
        self.on_click_cb = on_click

    async def callback(self, interaction: nextcord.Interaction):
        await self.on_click_cb(interaction, self.raid_id)

class RaidView(nextcord.ui.View):
    def __init__(self, *, bot: commands.Bot, raid: RaidEvent, template: CompTemplate, join_disabled: bool, actions_disabled: bool, on_select, on_absent, on_leave):
        super().__init__(timeout=None)

        options_all: List[nextcord.SelectOption] = []
        for r in template.roles:
            desc = f"slots {r.slots}"
            if r.ip_required:
                desc += " • IP"
            if r.required_role_ids:
                desc += " • req"
            options_all.append(nextcord.SelectOption(
                label=limit_str(r.label, 90),
                value=r.key,
                description=limit_str(desc, 100),
            ))

        chunks = [options_all[i:i+25] for i in range(0, len(options_all), 25)]
        pages = max(1, len(chunks))
        for idx, chunk in enumerate(chunks, start=1):
            self.add_item(RoleSelect(
                bot=bot,
                raid_id=raid.raid_id,
                options=chunk,
                page=idx,
                pages=pages,
                disabled=join_disabled,
                on_select=on_select,
            ))

        self.add_item(AbsentButton(bot=bot, raid_id=raid.raid_id, disabled=actions_disabled, on_click=on_absent))
        self.add_item(LeaveButton(bot=bot, raid_id=raid.raid_id, disabled=actions_disabled, on_click=on_leave))
