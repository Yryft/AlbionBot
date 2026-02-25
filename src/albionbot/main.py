import logging
from typing import List
import nextcord
from nextcord.ext import commands, tasks
from dotenv import load_dotenv

from .config import load_config
from .storage.store import Store
from .modules.raids import RaidModule
from .modules.bank import BankModule

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

    def _can_manage_raids(member: nextcord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        if cfg.raid_require_manage_guild and member.guild_permissions.manage_guild:
            return True
        if cfg.raid_manager_role_id is not None:
            return any(r.id == cfg.raid_manager_role_id for r in member.roles)
        return False

    def _can_manage_bank(member: nextcord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        if cfg.bank_require_manage_guild and member.guild_permissions.manage_guild:
            return True
        if cfg.bank_manager_role_id is not None:
            return any(r.id == cfg.bank_manager_role_id for r in member.roles)
        return False

    @bot.slash_command(name="help", description="Afficher l'aide des commandes selon ton rôle", **guild_kwargs)
    async def help_cmd(interaction: nextcord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message(
                "📘 Utilise cette commande sur le serveur pour voir les commandes disponibles.",
                ephemeral=True,
            )

        member = interaction.user
        is_raid_manager = _can_manage_raids(member)
        is_bank_manager = _can_manage_bank(member)

        lines: List[str] = [
            "📘 **Aide AlbionBot**",
            "",
            "**Commandes joueur**",
            "• `/help` — Affiche cette aide.",
            "• `/bal [user]` — Voir ta balance (ou un autre si autorisé).",
            "• `/pay <joueur> <montant> [note]` — Payer un joueur depuis ta balance.",
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
                "• `/bank_add` / `/bank_remove` — Ajouter/retirer (cibles multiples).",
                "• `/bank_add_split` / `/bank_remove_split` — Répartir une somme.",
                "• `/bank_undo` — Annuler la dernière action (<15 min).",
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
