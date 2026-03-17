from __future__ import annotations

import logging
from typing import Optional

import nextcord
from nextcord.ext import commands, tasks

from ..config import Config
from ..storage.store import Store
from web.backend.killboard import KillboardService

log = logging.getLogger("albionbot.killboard")


class KillboardModule:
    def __init__(self, bot: commands.Bot, store: Store, cfg: Config):
        self.bot = bot
        self.store = store
        self.cfg = cfg
        self.service = KillboardService(store)
        self.guild_kwargs = {"guild_ids": cfg.guild_ids} if cfg.guild_ids else {}
        self._register_commands()
        self.poller.start()

    def cog_unload(self):
        self.poller.cancel()

    def _register_commands(self) -> None:
        @self.bot.slash_command(name="killboard_add_guild", description="Ajouter une guilde Albion à la whitelist killboard", **self.guild_kwargs)
        async def killboard_add_guild(interaction: nextcord.Interaction, albion_server: str = nextcord.SlashOption(choices=["europe", "americas", "asia"]), guild_id: str = nextcord.SlashOption(), guild_name: str = nextcord.SlashOption(), channel: Optional[nextcord.TextChannel] = nextcord.SlashOption(required=False, default=None)):
            if not interaction.guild:
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            tracker = self.service.add_tracker(interaction.guild.id, interaction.user.id, albion_server, "guild", guild_id, guild_name, channel.id if channel else None)
            await interaction.response.send_message(f"✅ Tracker ajouté `{tracker['tracker_id']}` pour **{guild_name}**.", ephemeral=True)

        @self.bot.slash_command(name="killboard_add_player", description="Ajouter un joueur Albion à la whitelist killboard", **self.guild_kwargs)
        async def killboard_add_player(interaction: nextcord.Interaction, albion_server: str = nextcord.SlashOption(choices=["europe", "americas", "asia"]), player_id: str = nextcord.SlashOption(), player_name: str = nextcord.SlashOption(), channel: Optional[nextcord.TextChannel] = nextcord.SlashOption(required=False, default=None)):
            if not interaction.guild:
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            tracker = self.service.add_tracker(interaction.guild.id, interaction.user.id, albion_server, "player", player_id, player_name, channel.id if channel else None)
            await interaction.response.send_message(f"✅ Tracker ajouté `{tracker['tracker_id']}` pour **{player_name}**.", ephemeral=True)

        @self.bot.slash_command(name="killboard_remove", description="Supprimer un tracker killboard", **self.guild_kwargs)
        async def killboard_remove(interaction: nextcord.Interaction, tracker_id: str = nextcord.SlashOption()):
            self.service.delete_tracker(tracker_id)
            await interaction.response.send_message("🗑️ Tracker supprimé.", ephemeral=True)

        @self.bot.slash_command(name="killboard_list", description="Lister les trackers killboard", **self.guild_kwargs)
        async def killboard_list(interaction: nextcord.Interaction):
            if not interaction.guild:
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            rows = self.service.list_trackers(interaction.guild.id)
            if not rows:
                return await interaction.response.send_message("Aucun tracker configuré.", ephemeral=True)
            lines = [f"• `{r['tracker_id']}` [{r['albion_server']}] {r['kind']}={r['target_name']} (channel={r.get('post_channel_id') or 'none'})" for r in rows]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        @self.bot.slash_command(name="killboard_poll_now", description="Lancer un cycle de polling killboard immédiatement", **self.guild_kwargs)
        async def killboard_poll_now(interaction: nextcord.Interaction):
            posted = await self.service.poll_once()
            await interaction.response.send_message(f"✅ Poll killboard terminé ({posted} events marqués postés).", ephemeral=True)

    @tasks.loop(minutes=2)
    async def poller(self):
        try:
            await self.service.poll_once()
        except Exception as exc:
            log.exception("Killboard poller error: %s", exc)

    @poller.before_loop
    async def before_poller(self):
        await self.bot.wait_until_ready()
