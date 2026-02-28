from typing import Awaitable, Callable

import nextcord


RaidOpenSubmitCallback = Callable[[nextcord.Interaction, str, str, str, str, str], Awaitable[None]]
LootParamsSubmitCallback = Callable[[nextcord.Interaction, str, str, str], Awaitable[None]]
ConfirmCallback = Callable[[nextcord.Interaction], Awaitable[None]]


class RaidOpenDetailsModal(nextcord.ui.Modal):
    def __init__(self, on_submit: RaidOpenSubmitCallback):
        super().__init__(title="Détails du raid", timeout=180)
        self.on_submit_cb = on_submit

        self.title_input = nextcord.ui.TextInput(label="Titre (optionnel)", required=False, max_length=120)
        self.description_input = nextcord.ui.TextInput(label="Description (optionnel)", required=False, max_length=1000)
        self.extra_input = nextcord.ui.TextInput(label="Message RL (optionnel)", required=False, max_length=400)
        self.prep_input = nextcord.ui.TextInput(label="Prep minutes", required=True, default_value="10", max_length=3)
        self.cleanup_input = nextcord.ui.TextInput(label="Cleanup minutes", required=True, default_value="30", max_length=3)

        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.extra_input)
        self.add_item(self.prep_input)
        self.add_item(self.cleanup_input)

    async def callback(self, interaction: nextcord.Interaction):
        await self.on_submit_cb(
            interaction,
            str(self.title_input.value).strip(),
            str(self.description_input.value).strip(),
            str(self.extra_input.value).strip(),
            str(self.prep_input.value).strip(),
            str(self.cleanup_input.value).strip(),
        )


class LootSplitParamsModal(nextcord.ui.Modal):
    def __init__(self, on_submit: LootParamsSubmitCallback):
        super().__init__(title="Paramètres de répartition", timeout=180)
        self.on_submit_cb = on_submit

        self.tax_input = nextcord.ui.TextInput(label="Tax coffre %", required=True, default_value="10")
        self.rl_bonus_input = nextcord.ui.TextInput(label="Bonus RL %", required=True, default_value="7.5")
        self.scout_input = nextcord.ui.TextInput(label="Part scout %", required=True, default_value="10")

        self.add_item(self.tax_input)
        self.add_item(self.rl_bonus_input)
        self.add_item(self.scout_input)

    async def callback(self, interaction: nextcord.Interaction):
        await self.on_submit_cb(
            interaction,
            str(self.tax_input.value).strip(),
            str(self.rl_bonus_input.value).strip(),
            str(self.scout_input.value).strip(),
        )


class ConfirmView(nextcord.ui.View):
    def __init__(self, owner_id: int, on_confirm: ConfirmCallback):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.on_confirm = on_confirm

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Cette action n'est pas pour toi.", ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="Confirmer", style=nextcord.ButtonStyle.success)
    async def confirm(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.on_confirm(interaction)

    @nextcord.ui.button(label="Annuler", style=nextcord.ButtonStyle.danger)
    async def cancel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.stop()
        await interaction.response.edit_message(content="❎ Action annulée.", view=None)
