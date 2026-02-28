import asyncio
import re
import time
from typing import Dict, List, Optional, Tuple

import nextcord
from nextcord.ext import commands

from ..config import Config
from ..storage.store import Store, TicketMessageSnapshot, TicketRecord
from ..utils.discord import parse_ids
from ..utils.permissions import can_manage_tickets

TICKET_MODE_THREAD = "private_thread"
TICKET_MODE_CHANNEL = "private_channel"
OPEN_STYLE_MESSAGE = "message"
OPEN_STYLE_BUTTON = "button"


class TicketOpenLauncherButton(nextcord.ui.Button):
    def __init__(self, module: "TicketModule"):
        super().__init__(
            style=nextcord.ButtonStyle.blurple,
            label="Ouvrir un ticket",
            emoji="🎫",
            custom_id="albionbot:ticket_open",
        )
        self.module = module

    async def callback(self, interaction: nextcord.Interaction):
        await self.module.send_open_picker(interaction)


class TicketOpenLauncherView(nextcord.ui.View):
    def __init__(self, module: "TicketModule"):
        super().__init__(timeout=None)
        self.add_item(TicketOpenLauncherButton(module))


class TicketCloseConfirmView(nextcord.ui.View):
    def __init__(self, module: "TicketModule"):
        super().__init__(timeout=120)
        self.module = module

    @nextcord.ui.button(label="Confirmer la fermeture", style=nextcord.ButtonStyle.danger)
    async def confirm_close(self, _: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.module.close_ticket_channel(interaction)

    @nextcord.ui.button(label="Annuler", style=nextcord.ButtonStyle.secondary)
    async def cancel_close(self, _: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.edit_message(content="✅ Fermeture annulée.", view=None)


class TicketCloseView(nextcord.ui.View):
    def __init__(self, module: "TicketModule"):
        super().__init__(timeout=None)
        self.module = module

    @nextcord.ui.button(
        label="Fermer le ticket",
        style=nextcord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="albionbot:ticket_close",
    )
    async def close_ticket(self, _: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not await self.module.can_close_ticket(interaction):
            return await interaction.response.send_message(
                "⛔ Tu dois être l'auteur du ticket ou avoir les permissions de support/admin.",
                ephemeral=True,
            )
        await interaction.response.send_message(
            "Confirme la fermeture du ticket.",
            ephemeral=True,
            view=TicketCloseConfirmView(self.module),
        )


class TicketModule:
    def __init__(self, bot: commands.Bot, store: Store, cfg: Config):
        self.bot = bot
        self.store = store
        self.cfg = cfg
        self._persistent_views_registered = False
        self._register_commands()

    def register_persistent_views(self) -> None:
        if self._persistent_views_registered:
            return
        self.bot.add_view(TicketOpenLauncherView(self))
        self.bot.add_view(TicketCloseView(self))
        self._persistent_views_registered = True

    def _slugify_type_key(self, value: str) -> str:
        key = re.sub(r"[^a-z0-9_-]+", "-", (value or "").strip().lower()).strip("-")
        return key[:32]

    def _all_ticket_types(self, guild_id: int) -> Dict[str, Dict[str, object]]:
        conf = self.store.get_ticket_config(guild_id)
        raw_types = conf.get("ticket_types", {})
        out: Dict[str, Dict[str, object]] = {}
        if isinstance(raw_types, dict):
            for key, data in raw_types.items():
                if not isinstance(data, dict):
                    continue
                safe_key = self._slugify_type_key(str(key))
                if not safe_key:
                    continue
                out[safe_key] = {
                    "key": safe_key,
                    "label": str(data.get("label", safe_key.title()))[:100],
                    "description": str(data.get("description", ""))[:100],
                    "support_role_ids": list(map(int, data.get("support_role_ids", []))),
                    "category_id": data.get("category_id"),
                }
        if "default" not in out:
            out["default"] = {
                "key": "default",
                "label": "Support",
                "description": "",
                "support_role_ids": list(map(int, conf.get("support_role_ids", []))),
                "category_id": conf.get("category_id"),
            }
        return out

    def _save_ticket_types(self, guild_id: int, ticket_types: Dict[str, Dict[str, object]]) -> None:
        self.store.set_ticket_config(guild_id, ticket_types=ticket_types)

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

        perms = category.permissions_for(me) if category is not None else guild.me.guild_permissions
        missing: List[str] = []
        for attr, label in self._required_bot_permissions(mode):
            if not getattr(perms, attr, False):
                missing.append(label)
        return missing

    async def can_close_ticket(self, interaction: nextcord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return False
        channel = interaction.channel
        if channel is None:
            return False
        ticket = self.store.ticket_find_by_channel(
            interaction.guild.id,
            channel_id=(channel.id if isinstance(channel, nextcord.abc.GuildChannel) else None),
            thread_id=(channel.id if isinstance(channel, nextcord.Thread) else None),
        )
        if not ticket or ticket.status != "open":
            return False
        if ticket.owner_user_id == interaction.user.id:
            return True

        ticket_type = self._all_ticket_types(interaction.guild.id).get(ticket.ticket_type_key, {})
        role_ids = set(map(int, ticket_type.get("support_role_ids", [])))
        member_role_ids = {r.id for r in interaction.user.roles}
        return bool(role_ids.intersection(member_role_ids)) or can_manage_tickets(self.cfg, interaction.user, self.store)

    async def close_ticket_channel(self, interaction: nextcord.Interaction) -> None:
        if not interaction.guild or not interaction.channel:
            return await interaction.response.edit_message(content="Commande serveur uniquement.", view=None)

        ticket = self.store.ticket_find_by_channel(
            interaction.guild.id,
            channel_id=(interaction.channel.id if isinstance(interaction.channel, nextcord.abc.GuildChannel) else None),
            thread_id=(interaction.channel.id if isinstance(interaction.channel, nextcord.Thread) else None),
        )
        if ticket is None:
            return await interaction.response.edit_message(content="⛔ Ce salon n'est pas un ticket connu.", view=None)

        async with self.store.lock:
            self.store.ticket_update_status(ticket.ticket_id, status="closed")
            self.store.save()

        if isinstance(interaction.channel, nextcord.Thread):
            await interaction.response.edit_message(content="✅ Ticket fermé. Archivage du thread...", view=None)
            await interaction.channel.edit(name=f"closed-{interaction.channel.name}", archived=True, locked=True)
            return

        await interaction.response.edit_message(content="✅ Ticket fermé. Le salon sera supprimé dans 8 secondes.", view=None)
        await interaction.channel.send("🔒 Ticket fermé.")
        await interaction.channel.edit(name=f"closed-{interaction.channel.name}")
        await asyncio.sleep(8)
        await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")

    async def send_open_picker(self, interaction: nextcord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

        type_map = self._all_ticket_types(interaction.guild.id)
        options = [
            nextcord.SelectOption(
                label=str(data["label"]),
                value=key,
                description=str(data.get("description", ""))[:100] or None,
            )
            for key, data in sorted(type_map.items())
        ]

        module = self

        class TypePicker(nextcord.ui.View):
            def __init__(self):
                super().__init__(timeout=120)
                self.ticket_type = options[0].value

            @nextcord.ui.select(placeholder="Choisis le type de ticket", min_values=1, max_values=1, options=options)
            async def pick(self, _: nextcord.ui.Select, select_interaction: nextcord.Interaction):
                self.ticket_type = str(_.values[0])
                await select_interaction.response.send_message(
                    f"Type sélectionné: `{self.ticket_type}`. Clique sur **Ouvrir**.",
                    ephemeral=True,
                )

            @nextcord.ui.button(label="Ouvrir", style=nextcord.ButtonStyle.success)
            async def open_now(self, _: nextcord.ui.Button, button_interaction: nextcord.Interaction):
                await module.open_ticket(button_interaction, self.ticket_type)

        await interaction.response.send_message("Sélectionne un type de ticket.", ephemeral=True, view=TypePicker())

    async def open_ticket(self, interaction: nextcord.Interaction, ticket_type_key: str):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

        ticket_types = self._all_ticket_types(interaction.guild.id)
        ticket_type = ticket_types.get(self._slugify_type_key(ticket_type_key))
        if ticket_type is None:
            return await interaction.response.send_message("⛔ Type de ticket inconnu.", ephemeral=True)

        existing = [
            rec
            for rec in self.store.ticket_find_by_user(interaction.guild.id, interaction.user.id, status="open")
            if rec.ticket_type_key == ticket_type["key"]
        ]
        if existing:
            return await interaction.response.send_message(
                "⛔ Tu as déjà un ticket ouvert pour ce type.",
                ephemeral=True,
            )

        conf = self.store.get_ticket_config(interaction.guild.id)
        mode = str(conf.get("mode", TICKET_MODE_CHANNEL))

        support_role_ids = list(map(int, ticket_type.get("support_role_ids", [])))
        category = interaction.guild.get_channel(ticket_type.get("category_id") or 0)
        if category is not None and not isinstance(category, nextcord.CategoryChannel):
            category = None

        missing = self._check_bot_permissions(interaction.guild, mode, category=category)
        if missing:
            return await interaction.response.send_message(
                f"⛔ Permissions bot insuffisantes: {self._format_missing_perms(missing)}",
                ephemeral=True,
            )

        ticket_id = f"{interaction.guild.id}-{interaction.user.id}-{int(time.time())}"
        label = str(ticket_type["label"]).lower().replace(" ", "-")[:12]

        if mode == TICKET_MODE_CHANNEL:
            if category is None:
                return await interaction.response.send_message(
                    "⛔ Ce type de ticket nécessite une catégorie valide.",
                    ephemeral=True,
                )

            overwrites = {
                interaction.guild.default_role: nextcord.PermissionOverwrite(view_channel=False),
                interaction.guild.me: nextcord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                interaction.user: nextcord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            for role_id in support_role_ids:
                role = interaction.guild.get_role(role_id)
                if role is not None:
                    overwrites[role] = nextcord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

            channel = await interaction.guild.create_text_channel(
                name=f"ticket-{label}-{interaction.user.name}"[:95],
                category=category,
                overwrites=overwrites,
                reason=f"Ticket {ticket_id}",
            )
            thread = None
        else:
            base_channel = interaction.channel
            if not isinstance(base_channel, nextcord.TextChannel):
                return await interaction.response.send_message(
                    "⛔ Les tickets en mode thread doivent être ouverts depuis un salon texte.",
                    ephemeral=True,
                )
            thread = await base_channel.create_thread(
                name=f"ticket-{label}-{interaction.user.name}"[:95],
                auto_archive_duration=1440,
                type=nextcord.ChannelType.private_thread,
                reason=f"Ticket {ticket_id}",
            )
            await thread.add_user(interaction.user)
            for member in interaction.guild.members:
                if member.bot:
                    continue
                if any(role.id in support_role_ids for role in member.roles):
                    try:
                        await thread.add_user(member)
                    except Exception:
                        pass
            channel = base_channel

        record = TicketRecord(
            ticket_id=ticket_id,
            guild_id=interaction.guild.id,
            owner_user_id=interaction.user.id,
            ticket_type_key=str(ticket_type["key"]),
            channel_id=(channel.id if mode == TICKET_MODE_CHANNEL else channel.id),
            thread_id=(thread.id if thread else None),
            status="open",
        )

        async with self.store.lock:
            self.store.ticket_create_record(record)
            self.store.save()

        target = thread if thread is not None else channel
        support_mentions = " ".join(f"<@&{rid}>" for rid in support_role_ids) or "Aucun rôle support"
        await target.send(
            f"🎫 Ticket **{ticket_type['label']}** ouvert par {interaction.user.mention}.\n"
            f"Support autorisé: {support_mentions}",
            view=TicketCloseView(self),
        )
        await interaction.response.send_message(f"✅ Ticket créé: {target.mention}", ephemeral=True)

    def _register_commands(self):
        bot = self.bot
        cfg = self.cfg
        guild_kwargs = {"guild_ids": cfg.guild_ids} if cfg.guild_ids else {}

        @bot.slash_command(name="ticket_panel_send", description="(Admin/Manager) Envoyer le panneau d'ouverture de tickets", **guild_kwargs)
        async def ticket_panel_send(interaction: nextcord.Interaction):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_tickets(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)
            if not isinstance(interaction.channel, nextcord.TextChannel):
                return await interaction.response.send_message("⛔ Utilisable uniquement en salon texte.", ephemeral=True)

            type_lines = [
                f"• **{d['label']}** (`{k}`) — {d.get('description', '') or 'Sans description'}"
                for k, d in sorted(self._all_ticket_types(interaction.guild.id).items())
            ]
            embed = nextcord.Embed(
                title="🎫 Ouvrir un ticket",
                description="Choisis un type puis ouvre ton ticket.\n\n" + "\n".join(type_lines),
                color=nextcord.Color.green(),
            )
            await interaction.channel.send(embed=embed, view=TicketOpenLauncherView(self))
            await interaction.response.send_message("✅ Panneau ticket envoyé.", ephemeral=True)

        @bot.slash_command(name="ticket_open", description="Ouvrir un ticket", **guild_kwargs)
        async def ticket_open(
            interaction: nextcord.Interaction,
            type_key: str = nextcord.SlashOption(description="Type ticket (laisser vide pour le menu)", required=False, default=""),
        ):
            if not type_key:
                return await self.send_open_picker(interaction)
            await self.open_ticket(interaction, type_key)

        @bot.slash_command(name="ticket_close", description="Fermer le ticket courant", **guild_kwargs)
        async def ticket_close(interaction: nextcord.Interaction):
            if not await self.can_close_ticket(interaction):
                return await interaction.response.send_message("⛔ Tu ne peux pas fermer ce ticket.", ephemeral=True)
            await interaction.response.send_message("Confirme la fermeture.", ephemeral=True, view=TicketCloseConfirmView(self))

        @bot.slash_command(name="ticket_type_set", description="(Admin/Manager) Créer/mettre à jour un type de ticket", **guild_kwargs)
        async def ticket_type_set(
            interaction: nextcord.Interaction,
            key: str = nextcord.SlashOption(description="Clé type (ex: recrutement)", required=True),
            label: str = nextcord.SlashOption(description="Nom affiché", required=True),
            description: str = nextcord.SlashOption(description="Description courte", required=False, default=""),
            support_roles: str = nextcord.SlashOption(description="Mentions/IDs rôles support", required=False, default=""),
            category: Optional[nextcord.CategoryChannel] = nextcord.SlashOption(description="Catégorie de création (mode canal)", required=False, default=None),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_tickets(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            safe_key = self._slugify_type_key(key)
            if not safe_key:
                return await interaction.response.send_message("⛔ Clé invalide.", ephemeral=True)

            role_ids: List[int] = []
            for rid in set(parse_ids(support_roles or "")):
                if interaction.guild.get_role(rid):
                    role_ids.append(rid)
            role_ids.sort()

            all_types = self._all_ticket_types(interaction.guild.id)
            all_types[safe_key] = {
                "key": safe_key,
                "label": label[:100],
                "description": description[:100],
                "support_role_ids": role_ids,
                "category_id": category.id if category else None,
            }

            async with self.store.lock:
                self._save_ticket_types(interaction.guild.id, all_types)
                self.store.save()

            mentions = " ".join(f"<@&{rid}>" for rid in role_ids) if role_ids else "aucun"
            await interaction.response.send_message(
                f"✅ Type `{safe_key}` enregistré. Support: {mentions}.",
                ephemeral=True,
            )

        @bot.slash_command(name="ticket_type_remove", description="(Admin/Manager) Supprimer un type de ticket", **guild_kwargs)
        async def ticket_type_remove(
            interaction: nextcord.Interaction,
            key: str = nextcord.SlashOption(description="Clé à supprimer", required=True),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_tickets(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            safe_key = self._slugify_type_key(key)
            if safe_key == "default":
                return await interaction.response.send_message("⛔ Le type `default` ne peut pas être supprimé.", ephemeral=True)

            all_types = self._all_ticket_types(interaction.guild.id)
            if safe_key not in all_types:
                return await interaction.response.send_message("⛔ Type introuvable.", ephemeral=True)
            del all_types[safe_key]

            async with self.store.lock:
                self._save_ticket_types(interaction.guild.id, all_types)
                self.store.save()

            await interaction.response.send_message(f"✅ Type `{safe_key}` supprimé.", ephemeral=True)

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
            if not can_manage_tickets(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

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
                description="Catégorie par défaut (laisser vide pour reset)",
                required=False,
                default=None,
            ),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_tickets(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            async with self.store.lock:
                self.store.set_ticket_config(interaction.guild.id, category_id=(category.id if category else None))
                ticket_types = self._all_ticket_types(interaction.guild.id)
                ticket_types["default"]["category_id"] = category.id if category else None
                self._save_ticket_types(interaction.guild.id, ticket_types)
                self.store.save()

            if category:
                await interaction.response.send_message(f"✅ Catégorie ticket définie sur {category.mention}.", ephemeral=True)
            else:
                await interaction.response.send_message("✅ Catégorie ticket réinitialisée.", ephemeral=True)

        @bot.slash_command(name="ticket_config_roles", description="(Admin/Manager) Configurer les rôles support par défaut", **guild_kwargs)
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
            if not can_manage_tickets(cfg, interaction.user, self.store):
                return await interaction.response.send_message("⛔ Permission insuffisante (admin/manager requis).", ephemeral=True)

            role_ids: List[int] = []
            for rid in set(parse_ids(roles or "")):
                if interaction.guild.get_role(rid) is not None:
                    role_ids.append(rid)
            role_ids.sort()

            async with self.store.lock:
                self.store.set_ticket_config(interaction.guild.id, support_role_ids=role_ids)
                ticket_types = self._all_ticket_types(interaction.guild.id)
                ticket_types["default"]["support_role_ids"] = role_ids
                self._save_ticket_types(interaction.guild.id, ticket_types)
                self.store.save()

            if role_ids:
                mentions = " ".join(f"<@&{rid}>" for rid in role_ids)
                await interaction.response.send_message(f"✅ Rôles ticket par défaut: {mentions}", ephemeral=True)
            else:
                await interaction.response.send_message("✅ Rôles ticket par défaut vidés.", ephemeral=True)

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
            if not can_manage_tickets(cfg, interaction.user, self.store):
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
