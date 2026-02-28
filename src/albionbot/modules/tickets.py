import logging
import time
from typing import Optional

import nextcord
from nextcord.ext import commands

from ..config import Config
from ..storage.store import Store, TicketRecord, TicketGuildConfig
from ..utils.permissions import can_manage_tickets

log = logging.getLogger("albionbot.tickets")


def _now() -> int:
    return int(time.time())


class TicketOpenView(nextcord.ui.View):
    def __init__(self, module: "TicketsModule"):
        super().__init__(timeout=None)
        self.module = module

    @nextcord.ui.button(label="Ouvrir un ticket", style=nextcord.ButtonStyle.green, custom_id="ticket:open")
    async def open_ticket(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.module.open_ticket(interaction)


class TicketsModule:
    def __init__(self, bot: commands.Bot, store: Store, cfg: Config):
        self.bot = bot
        self.store = store
        self.cfg = cfg
        self.open_view = TicketOpenView(self)
        self.bot.add_view(self.open_view)
        self._register_commands()

    def _find_open_ticket_for_owner(self, guild_id: int, owner_id: int) -> Optional[TicketRecord]:
        for ticket in self.store.tickets.values():
            if ticket.guild_id == guild_id and ticket.owner_id == owner_id and ticket.status == "open":
                return ticket
        return None

    def _find_ticket_for_channel(self, guild_id: int, channel_id: int) -> Optional[TicketRecord]:
        for ticket in self.store.tickets.values():
            if ticket.guild_id != guild_id:
                continue
            if ticket.channel_id == channel_id or ticket.thread_id == channel_id:
                return ticket
        return None

    def _discord_target_exists(self, guild: nextcord.Guild, ticket: TicketRecord) -> bool:
        if ticket.target_type == "thread":
            return ticket.thread_id is not None and guild.get_thread(ticket.thread_id) is not None
        return ticket.channel_id is not None and guild.get_channel(ticket.channel_id) is not None

    async def _sync_guild_tickets(self, guild: nextcord.Guild) -> None:
        dirty = False
        for ticket in self.store.tickets.values():
            if ticket.guild_id != guild.id or ticket.status != "open":
                continue
            if not self._discord_target_exists(guild, ticket):
                log.warning("Ticket %s marqué deleted: cible Discord introuvable", ticket.ticket_id)
                ticket.status = "deleted"
                ticket.deleted_at = _now()
                dirty = True
        if dirty:
            async with self.store.lock:
                self.store.save()

    def _next_ticket_identifier(self) -> str:
        year = time.gmtime().tm_year
        prefix = f"TCK-{year}-"
        max_seq = 0
        for ticket_id in self.store.tickets.keys():
            if not ticket_id.startswith(prefix):
                continue
            try:
                max_seq = max(max_seq, int(ticket_id.split("-")[-1]))
            except ValueError:
                continue
        return f"{prefix}{max_seq + 1:04d}"

    def _ticket_embed(self, ticket: TicketRecord) -> nextcord.Embed:
        status_map = {
            "open": "🟢 Ouvert",
            "closed": "🟠 Fermé",
            "deleted": "⚫ Supprimé",
        }
        embed = nextcord.Embed(title=f"Ticket {ticket.ticket_id}", color=nextcord.Color.blurple())
        embed.add_field(name="Owner", value=f"<@{ticket.owner_id}>", inline=True)
        embed.add_field(name="Créé", value=f"<t:{ticket.created_at}:F>", inline=True)
        embed.add_field(name="État", value=status_map.get(ticket.status, ticket.status), inline=True)
        embed.set_footer(text=f"Ticket ID: {ticket.ticket_id}")
        return embed

    def _is_support_member(self, member: nextcord.Member, support_role_ids: list[int]) -> bool:
        if member.guild_permissions.administrator:
            return True
        member_role_ids = {role.id for role in member.roles}
        return any(role_id in member_role_ids for role_id in support_role_ids)

    async def _create_ticket_target(self, guild: nextcord.Guild, owner: nextcord.Member, ticket_id: str, cfg: TicketGuildConfig):
        support_role_ids = list(cfg.support_role_ids)
        if cfg.mode == "thread":
            if not cfg.parent_channel_id:
                raise RuntimeError("Aucun canal parent configuré pour les threads privés.")
            parent = guild.get_channel(cfg.parent_channel_id)
            if not isinstance(parent, nextcord.TextChannel):
                raise RuntimeError("Le canal parent configuré est introuvable ou invalide.")
            thread = await parent.create_thread(
                name=f"ticket-{ticket_id.lower()}",
                type=nextcord.ChannelType.private_thread,
                invitable=False,
            )
            await thread.add_user(owner)
            for role_id in support_role_ids:
                role = guild.get_role(role_id)
                if not role:
                    continue
                for member in role.members:
                    try:
                        await thread.add_user(member)
                    except Exception:
                        pass
            return None, thread

        overwrites = {
            guild.default_role: nextcord.PermissionOverwrite(view_channel=False),
            owner: nextcord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            guild.me: nextcord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        for role_id in support_role_ids:
            role = guild.get_role(role_id)
            if role is None:
                continue
            overwrites[role] = nextcord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        category = guild.get_channel(cfg.category_id) if cfg.category_id else None
        if category is not None and not isinstance(category, nextcord.CategoryChannel):
            category = None

        channel = await guild.create_text_channel(
            name=f"ticket-{ticket_id.lower()}",
            overwrites=overwrites,
            category=category,
            reason=f"Création ticket {ticket_id}",
        )
        return channel, None

    async def open_ticket(self, interaction: nextcord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

        await self._sync_guild_tickets(interaction.guild)
        if self._find_open_ticket_for_owner(interaction.guild.id, interaction.user.id):
            return await interaction.response.send_message("Tu as déjà un ticket ouvert.", ephemeral=True)

        async with self.store.lock:
            cfg = self.store.get_ticket_config(interaction.guild.id)

        async with self.store.lock:
            ticket_id = self._next_ticket_identifier()

        try:
            channel, thread = await self._create_ticket_target(interaction.guild, interaction.user, ticket_id, cfg)
        except Exception as exc:
            return await interaction.response.send_message(f"❌ Impossible de créer le ticket: {exc}", ephemeral=True)

        async with self.store.lock:
            ticket = TicketRecord(
                ticket_id=ticket_id,
                guild_id=interaction.guild.id,
                owner_id=interaction.user.id,
                status="open",
                created_at=_now(),
                channel_id=channel.id if channel else None,
                thread_id=thread.id if thread else None,
                target_type="thread" if thread else "channel",
            )
            self.store.tickets[ticket.ticket_id] = ticket
            self.store.save()

        target = thread or channel
        embed = self._ticket_embed(ticket)
        await target.send(embed=embed)
        await interaction.response.send_message(f"✅ Ticket créé: {target.mention}", ephemeral=True)

    def _register_commands(self):
        bot = self.bot
        guild_kwargs = {"guild_ids": self.cfg.guild_ids} if self.cfg.guild_ids else {}

        @bot.slash_command(name="ticket_open", description="Ouvrir un ticket support", **guild_kwargs)
        async def ticket_open(interaction: nextcord.Interaction):
            await self.open_ticket(interaction)

        @bot.slash_command(name="ticket_panel", description="Publier le panel ticket", **guild_kwargs)
        async def ticket_panel(interaction: nextcord.Interaction):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_tickets(self.cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permissions insuffisantes.", ephemeral=True)

            embed = nextcord.Embed(
                title="Support",
                description="Clique sur le bouton pour ouvrir un ticket privé.",
                color=nextcord.Color.green(),
            )
            await interaction.channel.send(embed=embed, view=self.open_view)
            await interaction.response.send_message("✅ Panel publié.", ephemeral=True)

        @bot.slash_command(name="ticket_close", description="Fermer le ticket courant", **guild_kwargs)
        async def ticket_close(interaction: nextcord.Interaction):
            if not interaction.guild or not interaction.channel or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

            await self._sync_guild_tickets(interaction.guild)
            ticket = self._find_ticket_for_channel(interaction.guild.id, interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("Aucun ticket associé à ce canal/thread.", ephemeral=True)

            cfg = self.store.get_ticket_config(interaction.guild.id)
            is_owner = ticket.owner_id == interaction.user.id
            is_support = self._is_support_member(interaction.user, cfg.support_role_ids)
            if not is_owner and not is_support and not can_manage_tickets(self.cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Tu ne peux pas fermer ce ticket.", ephemeral=True)

            async with self.store.lock:
                ticket.status = "closed"
                ticket.closed_at = _now()
                self.store.save()

            await interaction.response.send_message(f"🟠 Ticket `{ticket.ticket_id}` marqué fermé.", ephemeral=False)

        @bot.slash_command(name="ticket_delete", description="Supprimer le ticket courant", **guild_kwargs)
        async def ticket_delete(interaction: nextcord.Interaction):
            if not interaction.guild or not interaction.channel or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_tickets(self.cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permissions insuffisantes.", ephemeral=True)

            ticket = self._find_ticket_for_channel(interaction.guild.id, interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("Aucun ticket associé à ce canal/thread.", ephemeral=True)

            await interaction.response.send_message("🗑️ Suppression en cours...", ephemeral=True)
            try:
                archive_embed = self._ticket_embed(ticket)
                archive_embed.color = nextcord.Color.dark_grey()
                archive_embed.add_field(name="Archivage", value=f"Suppression demandée par {interaction.user.mention}", inline=False)
                await interaction.channel.send(embed=archive_embed)
                await interaction.channel.delete(reason=f"Ticket {ticket.ticket_id} supprimé")
            except Exception as exc:
                log.warning("Suppression ticket %s échouée: %s", ticket.ticket_id, exc)

            async with self.store.lock:
                ticket.status = "deleted"
                ticket.deleted_at = _now()
                self.store.save()

        @bot.slash_command(name="ticket_add_user", description="Ajouter un utilisateur au ticket", **guild_kwargs)
        async def ticket_add_user(
            interaction: nextcord.Interaction,
            user: nextcord.Member = nextcord.SlashOption(description="Membre à ajouter"),
        ):
            if not interaction.guild or not interaction.channel or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

            ticket = self._find_ticket_for_channel(interaction.guild.id, interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("Aucun ticket associé à ce canal/thread.", ephemeral=True)
            if not can_manage_tickets(self.cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permissions insuffisantes.", ephemeral=True)

            if isinstance(interaction.channel, nextcord.Thread):
                await interaction.channel.add_user(user)
            elif isinstance(interaction.channel, nextcord.TextChannel):
                overwrite = interaction.channel.overwrites_for(user)
                overwrite.view_channel = True
                overwrite.send_messages = True
                overwrite.read_message_history = True
                await interaction.channel.set_permissions(user, overwrite=overwrite)
            await interaction.response.send_message(f"✅ {user.mention} ajouté au ticket.", ephemeral=True)

        @bot.slash_command(name="ticket_remove_user", description="Retirer un utilisateur du ticket", **guild_kwargs)
        async def ticket_remove_user(
            interaction: nextcord.Interaction,
            user: nextcord.Member = nextcord.SlashOption(description="Membre à retirer"),
        ):
            if not interaction.guild or not interaction.channel or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

            ticket = self._find_ticket_for_channel(interaction.guild.id, interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("Aucun ticket associé à ce canal/thread.", ephemeral=True)
            if not can_manage_tickets(self.cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permissions insuffisantes.", ephemeral=True)

            if isinstance(interaction.channel, nextcord.Thread):
                await interaction.channel.remove_user(user)
            elif isinstance(interaction.channel, nextcord.TextChannel):
                await interaction.channel.set_permissions(user, overwrite=None)
            await interaction.response.send_message(f"✅ {user.mention} retiré du ticket.", ephemeral=True)

        @bot.slash_command(name="ticket_config", description="Configurer le système de ticket", **guild_kwargs)
        async def ticket_config(
            interaction: nextcord.Interaction,
            mode: str = nextcord.SlashOption(description="Mode", choices={"Salon privé": "channel", "Thread privé": "thread"}),
            support_roles: str = nextcord.SlashOption(description="IDs des rôles support (csv)", required=False, default=""),
            category: Optional[nextcord.CategoryChannel] = nextcord.SlashOption(description="Catégorie pour salons privés", required=False, default=None),
            parent_channel: Optional[nextcord.TextChannel] = nextcord.SlashOption(description="Canal parent pour threads privés", required=False, default=None),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("⛔ Admin uniquement.", ephemeral=True)

            parsed_roles = []
            if support_roles.strip():
                for part in support_roles.split(","):
                    try:
                        rid = int(part.strip())
                    except ValueError:
                        continue
                    if interaction.guild.get_role(rid):
                        parsed_roles.append(rid)

            cfg = TicketGuildConfig(
                mode=mode,
                category_id=category.id if category else None,
                parent_channel_id=parent_channel.id if parent_channel else None,
                support_role_ids=parsed_roles,
            )
            async with self.store.lock:
                self.store.set_ticket_config(interaction.guild.id, cfg)
                self.store.save()

            await interaction.response.send_message("✅ Configuration tickets mise à jour.", ephemeral=True)
