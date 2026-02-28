from dataclasses import dataclass
from typing import Awaitable, Callable, List

import nextcord


CloseCallback = Callable[[nextcord.Interaction, str], Awaitable[None]]
EditCallback = Callable[[nextcord.Interaction, str, str, str], Awaitable[None]]


@dataclass
class RaidAssistantState:
    raid_id: str = ""


class RaidSelect(nextcord.ui.Select):
    def __init__(self, owner_id: int, options: List[nextcord.SelectOption]):
        self.owner_id = owner_id
        super().__init__(
            placeholder="Choisis un raid actif",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: nextcord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Ce menu n'est pas pour toi.", ephemeral=True)
        view = self.view
        if not isinstance(view, RaidAssistantView):
            return
        view.state.raid_id = self.values[0]
        await interaction.response.edit_message(content=view.render_content(), view=view)


class RaidEditModal(nextcord.ui.Modal):
    def __init__(self, view: "RaidAssistantView"):
        super().__init__(title="Modifier le raid", timeout=180)
        self.assistant_view = view
        self.title_input = nextcord.ui.TextInput(
            label="Nouveau titre (optionnel)",
            required=False,
            max_length=120,
        )
        self.start_input = nextcord.ui.TextInput(
            label="Nouvelle date Paris (optionnel)",
            placeholder="YYYY-MM-DD HH:MM",
            required=False,
            max_length=32,
        )
        self.add_item(self.title_input)
        self.add_item(self.start_input)

    async def callback(self, interaction: nextcord.Interaction):
        raid_id = self.assistant_view.state.raid_id
        if not raid_id:
            return await interaction.response.send_message("Choisis d'abord un raid.", ephemeral=True)
        await self.assistant_view.on_edit(
            interaction,
            raid_id,
            str(self.title_input.value).strip(),
            str(self.start_input.value).strip(),
        )


class RaidAssistantView(nextcord.ui.View):
    def __init__(self, owner_id: int, options: List[nextcord.SelectOption], on_close: CloseCallback, on_edit: EditCallback):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.on_close = on_close
        self.on_edit = on_edit
        self.state = RaidAssistantState(raid_id=options[0].value if options else "")
        if options:
            self.add_item(RaidSelect(owner_id=owner_id, options=options))

    def render_content(self) -> str:
        selected = self.state.raid_id or "aucun"
        return (
            "🛡️ **Assistant raid**\n"
            "1) Sélectionne un raid actif.\n"
            "2) Ferme-le ou modifie titre/date via modal.\n\n"
            f"• Raid sélectionné: `{selected}`"
        )

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Cet assistant n'est pas pour toi.", ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="Fermer raid", style=nextcord.ButtonStyle.danger)
    async def close_raid(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not self.state.raid_id:
            return await interaction.response.send_message("Choisis d'abord un raid.", ephemeral=True)
        await self.on_close(interaction, self.state.raid_id)

    @nextcord.ui.button(label="Modifier titre/date", style=nextcord.ButtonStyle.primary)
    async def edit_raid(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not self.state.raid_id:
            return await interaction.response.send_message("Choisis d'abord un raid.", ephemeral=True)
        await interaction.response.send_modal(RaidEditModal(self))

    @nextcord.ui.button(label="Annuler", style=nextcord.ButtonStyle.secondary)
    async def cancel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.stop()
        await interaction.response.edit_message(content="❎ Assistant raid annulé.", view=None)
