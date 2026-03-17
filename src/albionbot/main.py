import logging
from typing import List

import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands, tasks

from .config import load_config
from .modules.bank import BankModule
from .modules.raids import RaidModule
from .modules.tickets import TicketModule
from .modules.killboard import KillboardModule
from .storage.store import Store
from .utils.discord import parse_ids
from .utils.permissions import (
    PERM_BANK_MANAGER,
    PERM_RAID_MANAGER,
    PERM_TICKET_MANAGER,
    can_manage_bank,
    can_manage_raids,
    can_manage_tickets,
    is_guild_admin,
)

log = logging.getLogger("albionbot")


def build_bot() -> commands.Bot:
    intents = nextcord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.voice_states = True
    # If DM wizard doesn't capture messages, enable Message Content Intent in the portal and uncomment:
    # intents.message_content = True
    return commands.Bot(intents=intents)


def _build_help_lines(member: nextcord.Member, cfg, store: Store) -> List[str]:
    is_raid_manager = can_manage_raids(cfg, member, store)
    is_bank_manager = can_manage_bank(cfg, member, store)
    is_ticket_manager = can_manage_tickets(cfg, member, store)

    lines: List[str] = [
        "**Commandes joueur**",
        "• `/help` — Affiche cette aide.",
        "• `/bal [user]` — Voir ta balance (ou un autre joueur si autorisé).",
        "• `/pay <joueur>` — Paiement rapide via formulaire.",
        "• `/bank_assistant` — Assistant interactif pour les actions banque.",
        "• `/raid_assistant` — Assistant interactif pour les raids.",
        "• `/ticket_open [type_key]` — Ouvrir un ticket.",
        "• `/ticket_close [reason]` — Fermer ton ticket (raison optionnelle).",
        "• `/killboard_list` — Voir les trackers killboard configurés.",
    ]

    if is_raid_manager:
        lines += [
            "",
            "**Commandes manager raid**",
            "• `/comp_wizard` — Créer un template via DM.",
            "• `/comp_edit <template>` — Modifier un template via DM.",
            "• `/comp_delete <template>` — Supprimer un template.",
            "• `/comp_list` — Lister les templates.",
            "• `/raid_open <template> <start> [vocal]` — Ouvrir un raid.",
            "• `/raid_edit <raid_id> [title] [start]` — Modifier un raid actif.",
            "• `/raid_list` — Lister les raids.",
            "• `/raid_close <raid_id>` — Fermer un raid.",
            "• `/loot_scout_limits <min> <max>` — Définir les limites scout.",
            "• `/loot_split ...` — Répartition du loot (thread raid).",
        ]

    if is_bank_manager:
        lines += [
            "",
            "**Commandes manager banque**",
            "• `/bank_add` / `/bank_remove` — Ajouter ou retirer des silver.",
            "• `/bank_add_split` / `/bank_remove_split` — Répartir une somme.",
            "• `/bank_undo` — Annuler la dernière action (<15 min).",
        ]

    if is_ticket_manager:
        lines += [
            "",
            "**Commandes manager tickets**",
            "• `/ticket_panel_send` — Envoyer le panneau d'ouverture de tickets.",
            "• `/ticket_type_set` / `/ticket_type_remove` — Gérer les types de tickets.",
            "• `/ticket_config_mode` — Définir le mode thread/canal privé.",
            "• `/ticket_config_category` — Définir ou retirer la catégorie par défaut.",
            "• `/ticket_config_roles` — Définir les rôles support par défaut.",
            "• `/ticket_config_open_style` — Choisir le style d'ouverture (message/bouton).",
            "• `/ticket_config_logs` — Définir le salon de logs tickets.",
            "• `/ticket_log_send` — Envoyer manuellement le log du ticket courant.",
        ]

    if is_guild_admin(member):
        lines += [
            "",
            "**Commande admin serveur**",
            "• `/permissions_set <permission> [roles]` — Définir les rôles autorisés.",
            "• `/permissions_assistant` — Version guidée via modal.",
        ]

    if not any([is_raid_manager, is_bank_manager, is_ticket_manager]):
        lines += [
            "",
            "🔒 Tu n'as pas de permissions manager actuellement.",
        ]

    return lines


def main():
    load_dotenv()
    cfg = load_config()
    store = Store(
        cfg.data_path,
        bank_action_log_limit=500,
        bank_database_url=cfg.bank_database_url,
        bank_sqlite_path=cfg.bank_sqlite_path,
    )
    bot = build_bot()

    raids = RaidModule(bot, store, cfg)
    bank = BankModule(bot, store, cfg)
    tickets = TicketModule(bot, store, cfg)
    killboard = KillboardModule(bot, store, cfg)

    guild_kwargs = {"guild_ids": cfg.guild_ids} if cfg.guild_ids else {}
    rotating_statuses = [
        nextcord.Streaming(
            name="regarde mon tuto cuisine",
            url="https://www.tiktok.com/@stephaniecooks1/video/7606490781146254600",
        ),
        nextcord.Streaming(
            name="listening to Can't Stop — Red Hot Chili Peppers",
            url="https://open.spotify.com/track/2aibwv5hGXSgw7Yru8IYTO",
        ),
    ]
    status_index = 0

    @bot.slash_command(name="help", description="Afficher l'aide des commandes selon ton rôle", **guild_kwargs)
    async def help_cmd(interaction: nextcord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message(
                "📘 Utilise cette commande sur le serveur pour voir les commandes disponibles.",
                ephemeral=True,
            )

        lines = _build_help_lines(interaction.user, cfg, store)
        embed = nextcord.Embed(
            title="📘 Aide AlbionBot",
            description="\n".join(lines),
            color=nextcord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.slash_command(name="permissions_set", description="(Admin) Définir les rôles autorisés par permission", **guild_kwargs)
    async def permissions_set(
        interaction: nextcord.Interaction,
        permission: str = nextcord.SlashOption(
            description="Permission à configurer",
            choices={"Raid manager": PERM_RAID_MANAGER, "Bank manager": PERM_BANK_MANAGER, "Ticket manager": PERM_TICKET_MANAGER},
        ),
        roles: str = nextcord.SlashOption(
            description="Mentions/IDs des rôles autorisés. Laisse vide pour vider.",
            required=False,
            default="",
        ),
    ):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        if not is_guild_admin(interaction.user):
            return await interaction.response.send_message("⛔ Cette commande est réservée aux administrateurs du serveur.", ephemeral=True)

        requested_ids = parse_ids(roles or "")
        valid_role_ids = [rid for rid in requested_ids if interaction.guild.get_role(rid) is not None]

        async with store.lock:
            store.set_permission_role_ids(interaction.guild.id, permission, valid_role_ids)
            store.save()

        if valid_role_ids:
            role_mentions = " ".join(f"<@&{rid}>" for rid in valid_role_ids)
            await interaction.response.send_message(
                f"✅ Permission `{permission}` mise à jour: {role_mentions}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"✅ Permission `{permission}` vidée (plus aucun rôle explicite).",
                ephemeral=True,
            )

    @bot.slash_command(name="permissions_assistant", description="(Admin) Assistant guidé des permissions", **guild_kwargs)
    async def permissions_assistant(interaction: nextcord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        if not is_guild_admin(interaction.user):
            return await interaction.response.send_message("⛔ Cette commande est réservée aux administrateurs du serveur.", ephemeral=True)

        class PermissionsModal(nextcord.ui.Modal):
            def __init__(self):
                super().__init__(title="Permissions manager", timeout=180)
                self.permission_input = nextcord.ui.TextInput(
                    label="Permission manager",
                    required=True,
                    placeholder=f"{PERM_RAID_MANAGER}, {PERM_BANK_MANAGER}, {PERM_TICKET_MANAGER}",
                    min_length=5,
                    max_length=32,
                )
                self.roles_input = nextcord.ui.TextInput(
                    label="Rôles (@roles/IDs), vide pour reset",
                    required=False,
                    min_length=0,
                    max_length=400,
                )
                self.add_item(self.permission_input)
                self.add_item(self.roles_input)

            async def callback(self, modal_interaction: nextcord.Interaction):
                if not modal_interaction.guild:
                    return await modal_interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

                permission = str(self.permission_input.value).strip()
                if permission not in {PERM_RAID_MANAGER, PERM_BANK_MANAGER, PERM_TICKET_MANAGER}:
                    return await modal_interaction.response.send_message(
                        f"Permission invalide. Utilise `{PERM_RAID_MANAGER}`, `{PERM_BANK_MANAGER}` ou `{PERM_TICKET_MANAGER}`.",
                        ephemeral=True,
                    )

                requested_ids = parse_ids(str(self.roles_input.value).strip())
                valid_role_ids = [rid for rid in requested_ids if modal_interaction.guild.get_role(rid) is not None]

                async with store.lock:
                    store.set_permission_role_ids(modal_interaction.guild.id, permission, valid_role_ids)
                    store.save()

                if valid_role_ids:
                    role_mentions = " ".join(f"<@&{rid}>" for rid in valid_role_ids)
                    await modal_interaction.response.send_message(
                        f"✅ Permission `{permission}` mise à jour: {role_mentions}",
                        ephemeral=True,
                    )
                else:
                    await modal_interaction.response.send_message(
                        f"✅ Permission `{permission}` vidée (plus aucun rôle explicite).",
                        ephemeral=True,
                    )

        await interaction.response.send_modal(PermissionsModal())

    @bot.event
    async def on_message(message: nextcord.Message):
        if message.author.bot:
            return
        async with store.lock:
            tickets.append_message_snapshot(message)
            store.save()

    @bot.event
    async def on_message_edit(before: nextcord.Message, after: nextcord.Message):
        if after.author and after.author.bot:
            return
        async with store.lock:
            tickets.append_edit_snapshot(before, after)
            store.save()

    @bot.event
    async def on_message_delete(message: nextcord.Message):
        if message.author and message.author.bot:
            return
        async with store.lock:
            tickets.append_delete_snapshot(message)
            store.save()

    @bot.event
    async def on_guild_channel_delete(channel: nextcord.abc.GuildChannel):
        async with store.lock:
            ticket = tickets.finalize_ticket(channel.id, status="deleted")
            if ticket:
                store.save()

    @bot.event
    async def on_thread_delete(thread: nextcord.Thread):
        async with store.lock:
            ticket = tickets.finalize_ticket(thread.id, status="deleted")
            if ticket:
                store.save()

    @bot.event
    async def on_guild_channel_update(before: nextcord.abc.GuildChannel, after: nextcord.abc.GuildChannel):
        before_name = (getattr(before, "name", "") or "").lower()
        after_name = (getattr(after, "name", "") or "").lower()
        if "closed" in after_name and "closed" not in before_name:
            async with store.lock:
                ticket = tickets.finalize_ticket(after.id, status="closed")
                if ticket:
                    store.save()

    @bot.event
    async def on_ready():
        log.info("Logged in as %s", bot.user)

        tickets.register_persistent_views()

        if not rotate_presence.is_running():
            rotate_presence.start()

        raids.start()

        if not sync_external_state.is_running():
            sync_external_state.start()

        # persistent views for existing raids after restart
        for raid in list(store.raids.values()):
            if raid.message_id:
                tpl = store.templates.get(raid.template_name)
                if not tpl:
                    continue
                view = raids.build_view(raid, tpl)
                try:
                    bot.add_view(view, message_id=raid.message_id)
                except Exception:
                    try:
                        bot.add_view(view)
                    except Exception:
                        pass


    @tasks.loop(seconds=5)
    async def sync_external_state():
        changed = False
        async with store.lock:
            changed = store.reload_if_changed()
        if changed:
            await raids.reconcile_external_updates()

    @tasks.loop(seconds=20)
    async def rotate_presence():
        nonlocal status_index
        await bot.change_presence(activity=rotating_statuses[status_index])
        status_index = (status_index + 1) % len(rotating_statuses)

    bot.run(cfg.discord_token)
