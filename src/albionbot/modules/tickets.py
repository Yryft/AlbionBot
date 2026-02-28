import time
from typing import List, Optional, Tuple

import nextcord
from nextcord.ext import commands

from ..config import Config
from ..storage.store import Store, TicketMessageSnapshot, TicketRecord
from ..utils.discord import parse_ids
from ..utils.permissions import can_manage_raids

TICKET_MODE_THREAD = "private_thread"
TICKET_MODE_CHANNEL = "private_channel"
OPEN_STYLE_MESSAGE = "message"
OPEN_STYLE_BUTTON = "button"


class TicketModule:
    def __init__(self, bot: commands.Bot, store: Store, cfg: Config):
        self.bot = bot
        self.store = store
        self.cfg = cfg
        self._register_commands()

    def _format_missing_perms(self, names: List[str]) -> str:
        return ", ".join(f"`{name}`" for name in names)

    def _required_bot_permissions(self, mode: str) -> List[Tuple[str, str]]:
        if mode == TICKET_MODE_THREAD:
            return [
                ("manage_channels", "Manage Channels"),
                ("create_private_threads", "Create Private Threads"),
                ("send_messages_in_threads", "Send Messages in Threads"),
            ]
        return [
            ("manage_channels", "Manage Channels"),
            ("manage_roles", "Manage Roles"),
            ("view_channel", "View Channels"),
        ]

    def _check_bot_permissions(
        self,
        guild: nextcord.Guild,
        mode: str,
        category: Optional[nextcord.CategoryChannel] = None,
    ) -> List[str]:
        me = guild.me
        if me is None:
            return []

        if category is not None:
            perms = category.permissions_for(me)
        else:
            perms = guild.me.guild_permissions

        missing: List[str] = []
        for attr, label in self._required_bot_permissions(mode):
            if not getattr(perms, attr, False):
                missing.append(label)
        return missing

    def _register_commands(self):
        bot = self.bot
        cfg = self.cfg
        guild_kwargs = {"guild_ids": cfg.guild_ids} if cfg.guild_ids else {}

        @bot.slash_command(name="ticket_config_mode", description="(Admin/Manager) Configurer le mode d'ouverture ticket", **guild_kwargs)
        async def ticket_config_mode(
            interaction: nextcord.Interaction,
            mode: str = nextcord.SlashOption(
                description="Mode ticket",
                choices={"Thread privé": TICKET_MODE_THREAD, "Canal privé": TICKET_MODE_CHANNEL},
            ),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            cur = self.store.get_ticket_config(interaction.guild.id)
            if mode == TICKET_MODE_THREAD and cur.get("category_id") is not None:
                return await interaction.response.send_message(
                    "⛔ Mode `private_thread` incompatible avec une catégorie ticket définie. "
                    "Retire d'abord la catégorie avec `/ticket_config_category`.",
                    ephemeral=True,
                )

            missing = self._check_bot_permissions(interaction.guild, mode)
            if missing:
                return await interaction.response.send_message(
                    "⛔ Permissions bot insuffisantes pour ce mode: "
                    f"{self._format_missing_perms(missing)}.",
                    ephemeral=True,
                )

            async with self.store.lock:
                self.store.set_ticket_config(interaction.guild.id, mode=mode)
                self.store.save()

            await interaction.response.send_message(f"✅ Mode ticket configuré sur `{mode}`.", ephemeral=True)

        @bot.slash_command(name="ticket_config_category", description="(Admin/Manager) Configurer la catégorie des tickets", **guild_kwargs)
        async def ticket_config_category(
            interaction: nextcord.Interaction,
            category: Optional[nextcord.CategoryChannel] = nextcord.SlashOption(
                description="Catégorie cible (laisser vide pour reset)",
                required=False,
                default=None,
            ),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            cur = self.store.get_ticket_config(interaction.guild.id)
            mode = str(cur.get("mode", TICKET_MODE_CHANNEL))

            if category is not None and category.guild.id != interaction.guild.id:
                return await interaction.response.send_message(
                    "⛔ La catégorie fournie n'appartient pas à ce serveur.",
                    ephemeral=True,
                )
            if mode == TICKET_MODE_THREAD and category is not None:
                return await interaction.response.send_message(
                    "⛔ Mode `private_thread` incompatible avec une catégorie ticket: "
                    "les threads privés sont créés dans un salon parent, pas dans une catégorie.",
                    ephemeral=True,
                )

            if category is not None:
                missing = self._check_bot_permissions(interaction.guild, mode, category=category)
                if missing:
                    return await interaction.response.send_message(
                        "⛔ Permissions bot insuffisantes dans cette catégorie: "
                        f"{self._format_missing_perms(missing)}.",
                        ephemeral=True,
                    )

            async with self.store.lock:
                self.store.set_ticket_config(interaction.guild.id, category_id=(category.id if category else None))
                self.store.save()

            if category:
                await interaction.response.send_message(f"✅ Catégorie ticket définie sur {category.mention}.", ephemeral=True)
            else:
                await interaction.response.send_message("✅ Catégorie ticket réinitialisée.", ephemeral=True)

        @bot.slash_command(name="ticket_config_roles", description="(Admin/Manager) Configurer les rôles support/admin tickets", **guild_kwargs)
        async def ticket_config_roles(
            interaction: nextcord.Interaction,
            roles: str = nextcord.SlashOption(
                description="Mentions/IDs des rôles autorisés",
                required=False,
                default="",
            ),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            role_ids: List[int] = []
            for rid in set(parse_ids(roles or "")):
                if interaction.guild.get_role(rid) is not None:
                    role_ids.append(rid)
            role_ids.sort()

            async with self.store.lock:
                self.store.set_ticket_config(interaction.guild.id, support_role_ids=role_ids)
                self.store.save()

            if role_ids:
                mentions = " ".join(f"<@&{rid}>" for rid in role_ids)
                await interaction.response.send_message(f"✅ Rôles ticket mis à jour: {mentions}", ephemeral=True)
            else:
                await interaction.response.send_message("✅ Rôles ticket vidés.", ephemeral=True)

        @bot.slash_command(name="ticket_config_open_style", description="(Admin/Manager) Choisir le style d'ouverture ticket", **guild_kwargs)
        async def ticket_config_open_style(
            interaction: nextcord.Interaction,
            style: str = nextcord.SlashOption(
                description="Style d'ouverture",
                choices={"Message": OPEN_STYLE_MESSAGE, "Bouton": OPEN_STYLE_BUTTON},
            ),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            async with self.store.lock:
                self.store.set_ticket_config(interaction.guild.id, open_style=style)
                self.store.save()

            await interaction.response.send_message(f"✅ Style d'ouverture configuré sur `{style}`.", ephemeral=True)

    def _find_ticket_by_message(self, message: nextcord.Message) -> Optional[TicketRecord]:
        if not message.guild:
            return None
        if isinstance(message.channel, nextcord.Thread):
            return self.store.ticket_find_by_channel(message.guild.id, thread_id=message.channel.id)
        return self.store.ticket_find_by_channel(message.guild.id, channel_id=message.channel.id)

    def append_message_snapshot(self, message: nextcord.Message) -> None:
        ticket = self._find_ticket_by_message(message)
        if ticket is None:
            return
        snapshot = TicketMessageSnapshot(
            message_id=message.id,
            author_id=message.author.id,
            content=message.content or "",
            embeds=[embed.to_dict() for embed in message.embeds],
            attachments=[{"id": str(a.id), "filename": a.filename, "url": a.url} for a in message.attachments],
            created_at=int(message.created_at.timestamp()) if message.created_at else int(time.time()),
        )
        self.store.ticket_append_snapshot(ticket.ticket_id, snapshot)

    def append_edit_snapshot(self, before: nextcord.Message, after: nextcord.Message) -> None:
        ticket = self._find_ticket_by_message(after)
        if ticket is None:
            return
        before_content = before.content or ""
        after_content = after.content or ""
        if before_content == after_content:
            return
        snapshot = TicketMessageSnapshot(
            message_id=after.id,
            author_id=after.author.id,
            content=f"[EDIT]\nBefore: {before_content}\nAfter: {after_content}",
            embeds=[embed.to_dict() for embed in after.embeds],
            attachments=[{"id": str(a.id), "filename": a.filename, "url": a.url} for a in after.attachments],
        )
        self.store.ticket_append_snapshot(ticket.ticket_id, snapshot)

    def append_delete_snapshot(self, message: nextcord.Message) -> None:
        ticket = self._find_ticket_by_message(message)
        if ticket is None:
            return
        snapshot = TicketMessageSnapshot(
            message_id=message.id,
            author_id=message.author.id if message.author else 0,
            content=f"[DELETE] {message.content or ''}".strip(),
            embeds=[embed.to_dict() for embed in message.embeds],
            attachments=[{"id": str(a.id), "filename": a.filename, "url": a.url} for a in message.attachments],
        )
        self.store.ticket_append_snapshot(ticket.ticket_id, snapshot)

    def finalize_ticket(self, channel_id: int, status: str) -> Optional[TicketRecord]:
        for record in self.store.ticket_records.values():
            if channel_id not in {record.channel_id, record.thread_id}:
                continue
            return self.store.ticket_update_status(record.ticket_id, status=status)  # type: ignore[arg-type]
        return None
