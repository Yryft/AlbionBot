from typing import Awaitable, Callable, List, Tuple

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


class BankLeaderboardView(nextcord.ui.View):
    def __init__(
        self,
        owner_id: int,
        guild_name: str,
        entries: List[Tuple[int, int]],
        page_size: int = 10,
    ):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.guild_name = guild_name
        self.entries = entries
        self.page_size = max(1, page_size)
        self.page = 0

    @property
    def page_count(self) -> int:
        return max(1, (len(self.entries) + self.page_size - 1) // self.page_size)

    def _slice(self) -> List[Tuple[int, int]]:
        start = self.page * self.page_size
        return self.entries[start:start + self.page_size]

    def _build_description(self) -> str:
        if not self.entries:
            return "Aucune entrée de banque pour ce serveur."

        start_rank = self.page * self.page_size + 1
        lines: List[str] = []
        for i, (user_id, balance) in enumerate(self._slice()):
            rank = start_rank + i
            lines.append(f"**#{rank}** • <@{user_id}> — **{balance:,}**")
        return "\n".join(lines)

    def _update_buttons(self) -> None:
        has_multiple_pages = self.page_count > 1
        self.prev_button.disabled = (not has_multiple_pages) or self.page <= 0
        self.next_button.disabled = (not has_multiple_pages) or self.page >= (self.page_count - 1)

    def render_embed(self) -> nextcord.Embed:
        self._update_buttons()
        embed = nextcord.Embed(
            title=f"🏦 Leaderboard banque — {self.guild_name}",
            description=self._build_description(),
            color=nextcord.Color.gold(),
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.page_count} • {len(self.entries)} entrée(s)")
        return embed

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Ce leaderboard n'est pas pour toi.", ephemeral=True)
            return False
        return True

    @nextcord.ui.button(label="⬅️ Précédent", style=nextcord.ButtonStyle.secondary)
    async def prev_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.render_embed(), view=self)

    @nextcord.ui.button(label="Suivant ➡️", style=nextcord.ButtonStyle.secondary)
    async def next_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        self.page = min(self.page_count - 1, self.page + 1)
        await interaction.response.edit_message(embed=self.render_embed(), view=self)
