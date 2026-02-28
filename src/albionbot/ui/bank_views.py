from dataclasses import dataclass
from typing import Callable, Awaitable

import nextcord

from ..storage.store import BankActionType


ActionCallback = Callable[[nextcord.Interaction, BankActionType, int, str, str], Awaitable[None]]
PaySubmitCallback = Callable[[nextcord.Interaction, str, int, str], Awaitable[None]]


@dataclass
class BankWizardState:
    action_type: BankActionType = "add"
    amount: int = 0
    targets: str = ""
    note: str = ""


class BankWizardActionSelect(nextcord.ui.Select):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        options = [
            nextcord.SelectOption(label="Ajouter", value="add", description="Ajoute le montant à chaque cible"),
            nextcord.SelectOption(label="Retirer", value="remove", description="Retire le montant à chaque cible"),
            nextcord.SelectOption(label="Ajouter (réparti)", value="add_split", description="Répartit un total entre les cibles"),
            nextcord.SelectOption(label="Retirer (réparti)", value="remove_split", description="Répartit un retrait total entre les cibles"),
        ]
        super().__init__(
            placeholder="1) Choisis le type d'action",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: nextcord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Ce menu n'est pas pour toi.", ephemeral=True)
        view = self.view
        if not isinstance(view, BankWizardView):
            return
        view.state.action_type = self.values[0]  # type: ignore[assignment]
        await interaction.response.edit_message(content=view.render_content(), view=view)


class BankWizardInputModal(nextcord.ui.Modal):
    def __init__(self, view: "BankWizardView"):
        super().__init__(title="2) Données de l'action", timeout=180)
        self.wizard_view = view

        self.amount_input = nextcord.ui.TextInput(
            label="Montant ou total",
            placeholder="Ex: 500000",
            required=True,
            default_value=str(view.state.amount) if view.state.amount > 0 else "",
            min_length=1,
            max_length=12,
        )
        self.targets_input = nextcord.ui.TextInput(
            label="Cibles (@users/@roles ou IDs)",
            placeholder="Ex: @Joueur @Officiers",
            required=True,
            default_value=view.state.targets,
            min_length=2,
            max_length=400,
        )
        self.note_input = nextcord.ui.TextInput(
            label="Note (optionnel)",
            required=False,
            default_value=view.state.note,
            min_length=0,
            max_length=200,
        )

        self.add_item(self.amount_input)
        self.add_item(self.targets_input)
        self.add_item(self.note_input)

    async def callback(self, interaction: nextcord.Interaction):
        raw_amount = str(self.amount_input.value).strip().replace(" ", "")
        if not raw_amount.isdigit():
            return await interaction.response.send_message("Montant invalide: mets un nombre entier positif.", ephemeral=True)

        amount = int(raw_amount)
        if amount < 0:
            return await interaction.response.send_message("Montant invalide: mets une valeur >= 0.", ephemeral=True)

        self.wizard_view.state.amount = amount
        self.wizard_view.state.targets = str(self.targets_input.value).strip()
        self.wizard_view.state.note = str(self.note_input.value).strip()

        await interaction.response.edit_message(content=self.wizard_view.render_content(), view=self.wizard_view)


class BankWizardView(nextcord.ui.View):
    def __init__(self, owner_id: int, on_confirm: ActionCallback):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.on_confirm = on_confirm
        self.state = BankWizardState()
        self.add_item(BankWizardActionSelect(owner_id=owner_id))

    def render_content(self) -> str:
        return (
            "🧾 **Assistant banque**\n"
            "1) Choisis l'action dans le menu.\n"
            "2) Clique sur **Saisir montant/cibles**.\n"
            "3) Vérifie puis **Valider**.\n\n"
            f"• Action: `{self.state.action_type}`\n"
            f"• Montant: `{self.state.amount}`\n"
            f"• Cibles: `{self.state.targets or 'non définies'}`\n"
            f"• Note: `{self.state.note or '—'}`"
        )

    def _is_ready(self) -> bool:
        return self.state.amount >= 0 and bool(self.state.targets.strip())

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Cet assistant n'est pas pour toi.", ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="Saisir montant/cibles", style=nextcord.ButtonStyle.secondary)
    async def open_modal(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_modal(BankWizardInputModal(self))

    @nextcord.ui.button(label="Valider", style=nextcord.ButtonStyle.success)
    async def validate(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not self._is_ready():
            return await interaction.response.send_message(
                "Action incomplète: renseigne au minimum un montant et des cibles.",
                ephemeral=True,
            )
        await self.on_confirm(interaction, self.state.action_type, self.state.amount, self.state.targets, self.state.note)

    @nextcord.ui.button(label="Annuler", style=nextcord.ButtonStyle.danger)
    async def cancel(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.stop()
        await interaction.response.edit_message(content="❎ Assistant banque annulé.", view=None)


class PayModal(nextcord.ui.Modal):
    def __init__(self, on_submit: PaySubmitCallback):
        super().__init__(title="Paiement", timeout=180)
        self.on_submit_cb = on_submit

        self.target_input = nextcord.ui.TextInput(
            label="Destinataire (@user ou ID)",
            placeholder="Ex: @Joueur",
            required=True,
            min_length=2,
            max_length=80,
        )
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

        self.add_item(self.target_input)
        self.add_item(self.amount_input)
        self.add_item(self.note_input)

    async def callback(self, interaction: nextcord.Interaction):
        raw_amount = str(self.amount_input.value).strip().replace(" ", "")
        if not raw_amount.isdigit():
            return await interaction.response.send_message("Montant invalide: mets un entier positif.", ephemeral=True)

        amount = int(raw_amount)
        if amount <= 0:
            return await interaction.response.send_message("Montant invalide: mets une valeur > 0.", ephemeral=True)

        await self.on_submit_cb(
            interaction,
            str(self.target_input.value).strip(),
            amount,
            str(self.note_input.value).strip(),
        )
