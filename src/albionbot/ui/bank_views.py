from typing import Awaitable, Callable

import nextcord


PaySubmitCallback = Callable[[nextcord.Interaction, int, str], Awaitable[None]]
ConfirmCallback = Callable[[nextcord.Interaction], Awaitable[None]]


class PayDetailsModal(nextcord.ui.Modal):
    def __init__(self, on_submit: PaySubmitCallback):
        super().__init__(title="Paiement", timeout=180)
        self.on_submit_cb = on_submit

        self.amount_input = nextcord.ui.TextInput(
            label="Montant",
            placeholder="Ex: 250000",
            required=True,
            min_length=1,
            max_length=12,
        )
        self.note_input = nextcord.ui.TextInput(
            label="Note (optionnel)",
            required=False,
            min_length=0,
            max_length=200,
        )

        self.add_item(self.amount_input)
        self.add_item(self.note_input)

    async def callback(self, interaction: nextcord.Interaction):
        raw_amount = str(self.amount_input.value).strip().replace(" ", "")
        if not raw_amount.isdigit():
            return await interaction.response.send_message("Montant invalide: mets un entier positif.", ephemeral=True)

        amount = int(raw_amount)
        if amount <= 0:
            return await interaction.response.send_message("Montant invalide: mets une valeur > 0.", ephemeral=True)

        await self.on_submit_cb(interaction, amount, str(self.note_input.value).strip())


class BankActionConfirmView(nextcord.ui.View):
    def __init__(self, owner_id: int, on_confirm: ConfirmCallback):
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.on_confirm = on_confirm

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Cette confirmation n'est pas pour toi.", ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="Confirmer", style=nextcord.ButtonStyle.success)
    async def confirm(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.on_confirm(interaction)

    @nextcord.ui.button(label="Annuler", style=nextcord.ButtonStyle.danger)
    async def cancel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.stop()
        await interaction.response.edit_message(content="❎ Action annulée.", view=None)
