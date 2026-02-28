import logging
from typing import List
import nextcord
from nextcord.ext import commands, tasks
from dotenv import load_dotenv

from .config import load_config
from .storage.store import Store
from .modules.raids import RaidModule
from .modules.bank import BankModule
from .utils.discord import parse_ids
from .utils.permissions import can_manage_bank, can_manage_raids, is_guild_admin, PERM_BANK_MANAGER, PERM_RAID_MANAGER

log = logging.getLogger("albionbot")

def build_bot() -> commands.Bot:
    intents = nextcord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.voice_states = True
    # If DM wizard doesn't capture messages, enable Message Content Intent in the portal and uncomment:
    # intents.message_content = True
    return commands.Bot(intents=intents)

def main():
    load_dotenv()
    cfg = load_config()
    store = Store(cfg.data_path, bank_action_log_limit=500, bank_database_url=cfg.bank_database_url, bank_sqlite_path=cfg.bank_sqlite_path)
    bot = build_bot()

    raids = RaidModule(bot, store, cfg)
    bank = BankModule(bot, store, cfg)

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

        member = interaction.user
        is_raid_manager = can_manage_raids(cfg, member, store)
        is_bank_manager = can_manage_bank(cfg, member, store)

        lines: List[str] = [
            "📘 **Aide AlbionBot**",
            "",
            "**Commandes joueur**",
            "• `/help` — Affiche cette aide.",
            "• `/bal [user]` — Voir ta balance (ou un autre si autorisé).",
            "• `/pay <joueur>` — Choisir un joueur puis saisir montant/note en modal.",
            "",
            "**Fonctions raid (UI)**",
            "• Message raid: sélection de rôle, `Absent`, `Leave`, `DM notif (toggle)`.",
            "• Le bouton DM notif permet de recevoir un DM au mass-up (avec vocal si défini).",
        ]

        if is_raid_manager:
            lines += [
                "",
                "**Commandes manager raid**",
                "• `/comp_wizard` — Créer un template via DM.",
                "• `/comp_edit <template>` — Modifier un template via DM.",
                "• `/comp_delete <template>` — Supprimer un template.",
                "• `/comp_list` — Lister les templates.",
                "• `/raid_open ...` — Ouvrir un raid.",
                "• `/raid_assistant` — Assistant guidé (sélection, close, edit).",
                "• `/raid_edit <raid_id> [title] [start]` — Modifier un raid actif.",
                "• `/raid_list` — Lister les raids.",
                "• `/raid_close <raid_id>` — Fermer un raid.",
                "• `/loot_scout_limits <min> <max>` — Configurer limites scout.",
                "• `/loot_split ...` — Calcul/paiement split loot (thread raid uniquement).",
            ]

        if is_bank_manager:
            lines += [
                "",
                "**Commandes manager banque**",
                "• `/bank_add` / `/bank_remove` — Ajouter/retirer avec écran de confirmation.",
                "• `/bank_add_split` / `/bank_remove_split` — Répartir une somme.",
                "• `/bank_undo` — Annuler la dernière action (<15 min).",
            ]

        if is_guild_admin(member):
            lines += [
                "",
                "**Commande admin serveur**",
                "• `/permissions_set <permission> [roles]` — Définir quels rôles peuvent gérer raid/banque.",
                "• `/permissions_assistant` — Version guidée via modal.",
            ]

        if not is_raid_manager and not is_bank_manager:
            lines += [
                "",
                "🔒 Tu n'as pas de permissions manager raid/banque actuellement.",
            ]

        embed = nextcord.Embed(
            title="📘 Aide AlbionBot",
            description="\n".join(lines[2:]),
            color=nextcord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.slash_command(name="permissions_set", description="(Admin) Définir les rôles autorisés par permission", **guild_kwargs)
    async def permissions_set(
        interaction: nextcord.Interaction,
        permission: str = nextcord.SlashOption(
            description="Permission à configurer",
            choices={"Raid manager": PERM_RAID_MANAGER, "Bank manager": PERM_BANK_MANAGER},
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
                    label="Permission (raid_manager ou bank_manager)",
                    required=True,
                    placeholder=f"{PERM_RAID_MANAGER} ou {PERM_BANK_MANAGER}",
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
                if permission not in {PERM_RAID_MANAGER, PERM_BANK_MANAGER}:
                    return await modal_interaction.response.send_message(
                        f"Permission invalide. Utilise `{PERM_RAID_MANAGER}` ou `{PERM_BANK_MANAGER}`.",
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
    async def on_ready():
        log.info("Logged in as %s", bot.user)

        if not rotate_presence.is_running():
            rotate_presence.start()

        raids.start()

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

    @tasks.loop(seconds=20)
    async def rotate_presence():
        nonlocal status_index
        await bot.change_presence(activity=rotating_statuses[status_index])
        status_index = (status_index + 1) % len(rotating_statuses)

    bot.run(cfg.discord_token)
