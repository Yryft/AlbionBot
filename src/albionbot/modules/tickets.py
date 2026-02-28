import io
import html
from datetime import datetime
from typing import List

import nextcord
from nextcord.ext import commands

from ..config import Config
from ..storage.store import Store, TicketRecord
from ..utils.permissions import can_manage_tickets


def _fmt_ts(ts: int) -> str:
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S UTC")


def _ticket_summary(ticket: TicketRecord) -> str:
    participants = ", ".join(f"<@{uid}>" for uid in ticket.participant_user_ids[:15]) or "—"
    if len(ticket.participant_user_ids) > 15:
        participants += f" (+{len(ticket.participant_user_ids) - 15})"

    closed_at = _fmt_ts(ticket.closed_at) if ticket.closed_at is not None else "—"
    return (
        f"`{ticket.ticket_id}` • status=`{ticket.status}`\n"
        f"• owner: <@{ticket.owner_user_id}>\n"
        f"• créé: {_fmt_ts(ticket.created_at)}\n"
        f"• maj: {_fmt_ts(ticket.updated_at)}\n"
        f"• fermé: {closed_at}\n"
        f"• participants: {participants}"
    )


def _build_transcript_text(ticket: TicketRecord) -> str:
    header = [
        f"Ticket {ticket.ticket_id}",
        f"Status: {ticket.status}",
        f"Owner: {ticket.owner_user_id}",
        f"Created: {_fmt_ts(ticket.created_at)}",
        f"Updated: {_fmt_ts(ticket.updated_at)}",
        "",
        "Messages:",
    ]
    body = [
        f"[{_fmt_ts(message.created_at)}] {message.author_user_id}: {message.content}"
        for message in ticket.transcript_messages
    ]
    return "\n".join(header + body)


def _build_transcript_html(ticket: TicketRecord) -> str:
    rows = []
    for message in ticket.transcript_messages:
        rows.append(
            "<tr>"
            f"<td>{_fmt_ts(message.created_at)}</td>"
            f"<td>{message.author_user_id}</td>"
            f"<td>{html.escape(message.content).replace(chr(10), '<br>')}</td>"
            "</tr>"
        )
    table = "\n".join(rows) or "<tr><td colspan='3'>Aucun message</td></tr>"
    return (
        "<html><head><meta charset='utf-8'><title>Ticket Transcript</title></head><body>"
        f"<h2>Ticket {ticket.ticket_id}</h2>"
        f"<p>Status: {ticket.status} | Owner: {ticket.owner_user_id}</p>"
        "<table border='1' cellspacing='0' cellpadding='4'>"
        "<thead><tr><th>Date</th><th>Auteur</th><th>Message</th></tr></thead>"
        f"<tbody>{table}</tbody></table></body></html>"
    )


class TicketModule:
    def __init__(self, bot: commands.Bot, store: Store, cfg: Config):
        self.bot = bot
        self.store = store
        self.cfg = cfg
        self._register_commands()

    def _can_access_ticket(self, member: nextcord.Member, ticket: TicketRecord) -> bool:
        if member.id == ticket.owner_user_id:
            return True
        return can_manage_tickets(self.cfg, member, self.store)

    async def _send_transcript(self, interaction: nextcord.Interaction, ticket: TicketRecord):
        transcript_text = _build_transcript_text(ticket)
        transcript_html = _build_transcript_html(ticket)

        files = [
            nextcord.File(io.BytesIO(transcript_text.encode("utf-8")), filename=f"ticket-{ticket.ticket_id}.txt"),
            nextcord.File(io.BytesIO(transcript_html.encode("utf-8")), filename=f"ticket-{ticket.ticket_id}.html"),
        ]

        try:
            await interaction.followup.send("📎 Transcript du ticket.", files=files, ephemeral=True)
            return
        except Exception:
            pass

        chunks: List[str] = []
        chunk = ""
        for line in transcript_text.splitlines():
            line = line[:1900]
            candidate = f"{chunk}\n{line}" if chunk else line
            if len(candidate) > 1800:
                chunks.append(chunk)
                chunk = line
            else:
                chunk = candidate
        if chunk:
            chunks.append(chunk)

        for idx, part in enumerate(chunks[:10], start=1):
            await interaction.followup.send(f"Transcript chunk {idx}/{len(chunks)}\n```\n{part}\n```", ephemeral=True)

    def _register_commands(self):
        bot = self.bot
        guild_kwargs = {"guild_ids": self.cfg.guild_ids} if self.cfg.guild_ids else {}

        @bot.slash_command(name="my_tickets", description="Voir la liste de tes tickets", **guild_kwargs)
        async def my_tickets(interaction: nextcord.Interaction):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

            tickets = self.store.ticket_list_for_owner(interaction.guild.id, interaction.user.id)
            if not tickets:
                return await interaction.response.send_message("Tu n'as aucun ticket.", ephemeral=True)

            lines = ["🎟️ **Tes tickets**", ""]
            lines.extend(_ticket_summary(ticket) for ticket in tickets[:20])
            await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

        @bot.slash_command(name="ticket_history", description="(Support/Admin) Voir l'historique ticket d'un membre", **guild_kwargs)
        async def ticket_history(
            interaction: nextcord.Interaction,
            user: nextcord.Member = nextcord.SlashOption(description="Membre cible"),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

            if not can_manage_tickets(self.cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Accès refusé.", ephemeral=True)

            tickets = self.store.ticket_list_for_owner(interaction.guild.id, user.id)
            if not tickets:
                return await interaction.response.send_message(f"Aucun ticket pour {user.mention}.", ephemeral=True)

            lines = [f"🎟️ **Historique tickets de {user.mention}**", ""]
            lines.extend(_ticket_summary(ticket) for ticket in tickets[:20])
            await interaction.response.send_message("\n\n".join(lines), ephemeral=True)

        @bot.slash_command(name="ticket_export", description="Exporter le transcript d'un ticket", **guild_kwargs)
        async def ticket_export(
            interaction: nextcord.Interaction,
            ticket_id: str = nextcord.SlashOption(description="Identifiant ticket"),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

            ticket = self.store.ticket_get(ticket_id)
            if ticket is None or ticket.guild_id != interaction.guild.id:
                return await interaction.response.send_message("Ticket introuvable.", ephemeral=True)

            if not self._can_access_ticket(interaction.user, ticket):
                return await interaction.response.send_message("⛔ Accès refusé.", ephemeral=True)

            async with self.store.lock:
                self.store.ticket_log_audit_view(ticket.ticket_id, interaction.user.id)
                self.store.save()

            await interaction.response.send_message(
                "📦 **Export ticket**\n\n" + _ticket_summary(ticket),
                ephemeral=True,
            )
            await self._send_transcript(interaction, ticket)
