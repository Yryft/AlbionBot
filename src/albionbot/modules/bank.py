import time
import logging
from typing import Dict, List, Optional, Tuple

import nextcord
from nextcord.ext import commands

from ..config import Config
from ..storage.store import Store, BankAction, BankActionType
from ..utils.discord import parse_ids, mention

log = logging.getLogger("albionbot.bank")

UNDO_WINDOW_SECONDS = 15 * 60

def _now() -> int:
    return int(time.time())

def can_manage_bank(cfg: Config, member: nextcord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if cfg.bank_require_manage_guild and member.guild_permissions.manage_guild:
        return True
    if cfg.bank_manager_role_id is not None:
        return any(r.id == cfg.bank_manager_role_id for r in member.roles)
    return False

def resolve_targets(guild: nextcord.Guild,
                    user: Optional[nextcord.Member],
                    role: Optional[nextcord.Role],
                    targets_text: str) -> List[nextcord.Member]:
    members: Dict[int, nextcord.Member] = {}

    if user:
        members[user.id] = user

    if role:
        for m in role.members:
            if not m.bot:
                members[m.id] = m

    ids = parse_ids(targets_text or "")
    for _id in ids:
        r = guild.get_role(_id)
        if r:
            for m in r.members:
                if not m.bot:
                    members[m.id] = m
            continue
        m = guild.get_member(_id)
        if m and not m.bot:
            members[m.id] = m

    return [members[k] for k in sorted(members.keys())]

def make_action_id() -> str:
    return f"A{int(time.time()*1000)}"

def compute_split_deltas(total: int, user_ids: List[int], sign: int) -> Dict[int, int]:
    n = len(user_ids)
    if n <= 0:
        return {}
    base = total // n
    rem = total % n
    deltas = {}
    for i, uid in enumerate(sorted(user_ids)):
        amt = base + (1 if i < rem else 0)
        deltas[uid] = sign * amt
    return deltas

def can_apply_deltas(store: Store, guild_id: int, deltas: Dict[int, int], allow_negative: bool) -> Tuple[bool, str]:
    if allow_negative:
        return True, ""
    for uid, delta in deltas.items():
        cur = store.bank_get_balance(guild_id, uid)
        if cur + delta < 0:
            return False, f"Solde insuffisant pour {mention(uid)} (bal={cur}, delta={delta})."
    return True, ""

def apply_deltas(store: Store, guild_id: int, deltas: Dict[int, int]) -> None:
    for uid, delta in deltas.items():
        cur = store.bank_get_balance(guild_id, uid)
        store.bank_set_balance(guild_id, uid, cur + delta)

def find_last_action_for_actor(store: Store, guild_id: int, actor_id: int) -> Optional[BankAction]:
    return store.bank_find_last_action_for_actor(guild_id, actor_id)

class BankModule:
    def __init__(self, bot: commands.Bot, store: Store, cfg: Config):
        self.bot = bot
        self.store = store
        self.cfg = cfg
        self._register_commands()

    async def _bank_change_common(
        self,
        interaction: nextcord.Interaction,
        action_type: BankActionType,
        amount: int,
        user: Optional[nextcord.Member],
        role: Optional[nextcord.Role],
        targets: str,
        note: str,
        split: bool,
    ):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        if not can_manage_bank(self.cfg, interaction.user):
            return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)
        if amount < 0:
            return await interaction.response.send_message("Montant invalide (>=0).", ephemeral=True)

        resolved = resolve_targets(interaction.guild, user=user, role=role, targets_text=targets or "")
        if not resolved:
            return await interaction.response.send_message("Aucune cible trouvée. Utilise `user`, `role` ou `targets`.", ephemeral=True)

        guild_id = interaction.guild.id
        actor_id = interaction.user.id
        ids = [m.id for m in resolved]

        if split:
            sign = +1 if action_type == "add_split" else -1
            deltas = compute_split_deltas(amount, ids, sign=sign)
        else:
            sign = +1 if action_type == "add" else -1
            deltas = {uid: sign * amount for uid in ids}

        async with self.store.lock:
            ok, reason = can_apply_deltas(self.store, guild_id, deltas, allow_negative=self.cfg.bank_allow_negative)
            if not ok:
                return await interaction.response.send_message(f"⛔ {reason}", ephemeral=True)

            apply_deltas(self.store, guild_id, deltas)

            action = BankAction(
                action_id=make_action_id(),
                guild_id=guild_id,
                actor_id=actor_id,
                created_at=_now(),
                action_type=action_type,
                deltas=deltas,
                note=note.strip() if note else "",
            )
            self.store.bank_append_action(action)
            self.store.save()

        total_delta = sum(deltas.values())
        n = len(deltas)
        preview = ", ".join(mention(uid) for uid in list(sorted(deltas.keys()))[:10])
        more = "" if n <= 10 else f" (+{n-10} autres)"

        await interaction.response.send_message(
            f"✅ Action `{action.action_type}` appliquée sur **{n}** personne(s).\n"
            f"Δ total = **{total_delta}**\n"
            f"Cibles: {preview}{more}\n"
            f"Undo possible via `/bank_undo` pendant 15 min.",
            ephemeral=True
        )

    def _register_commands(self):
        bot = self.bot
        cfg = self.cfg
        guild_kwargs = {"guild_ids": cfg.guild_ids} if cfg.guild_ids else {}

        @bot.slash_command(name="bal", description="Voir ta balance", **guild_kwargs)
        async def bal(interaction: nextcord.Interaction, user: Optional[nextcord.Member] = nextcord.SlashOption(description="Voir la balance de quelqu'un (si autorisé)", required=False)):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

            target = user or interaction.user
            if target.id != interaction.user.id and not can_manage_bank(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Tu ne peux voir que ta balance.", ephemeral=True)

            balance = self.store.bank_get_balance(interaction.guild.id, target.id)
            await interaction.response.send_message(f"💰 Balance de {target.mention} : **{balance}**", ephemeral=True)

        @bot.slash_command(name="bank_add", description="Ajouter à la balance (mass possible)", **guild_kwargs)
        async def bank_add(
            interaction: nextcord.Interaction,
            amount: int = nextcord.SlashOption(description="Montant à ajouter", min_value=0),
            user: Optional[nextcord.Member] = nextcord.SlashOption(description="Cible unique (optionnel)", required=False),
            role: Optional[nextcord.Role] = nextcord.SlashOption(description="Ajouter à tous les membres d'un rôle (optionnel)", required=False),
            targets: str = nextcord.SlashOption(description="Mentions/IDs @users/@roles (optionnel)", required=False, default=""),
            note: str = nextcord.SlashOption(description="Note (optionnel)", required=False, default=""),
        ):
            await self._bank_change_common(interaction, "add", amount, user, role, targets, note, split=False)

        @bot.slash_command(name="bank_remove", description="Retirer de la balance (mass possible)", **guild_kwargs)
        async def bank_remove(
            interaction: nextcord.Interaction,
            amount: int = nextcord.SlashOption(description="Montant à retirer", min_value=0),
            user: Optional[nextcord.Member] = nextcord.SlashOption(description="Cible unique (optionnel)", required=False),
            role: Optional[nextcord.Role] = nextcord.SlashOption(description="Retirer à tous les membres d'un rôle (optionnel)", required=False),
            targets: str = nextcord.SlashOption(description="Mentions/IDs @users/@roles (optionnel)", required=False, default=""),
            note: str = nextcord.SlashOption(description="Note (optionnel)", required=False, default=""),
        ):
            await self._bank_change_common(interaction, "remove", amount, user, role, targets, note, split=False)

        @bot.slash_command(name="bank_add_split", description="Ajouter une somme répartie entre les cibles", **guild_kwargs)
        async def bank_add_split(
            interaction: nextcord.Interaction,
            total: int = nextcord.SlashOption(description="Somme totale à répartir", min_value=0),
            user: Optional[nextcord.Member] = nextcord.SlashOption(description="(optionnel) ajoute 1 personne", required=False),
            role: Optional[nextcord.Role] = nextcord.SlashOption(description="(optionnel) rôle cible", required=False),
            targets: str = nextcord.SlashOption(description="Mentions/IDs @users/@roles (optionnel)", required=False, default=""),
            note: str = nextcord.SlashOption(description="Note (optionnel)", required=False, default=""),
        ):
            await self._bank_change_common(interaction, "add_split", total, user, role, targets, note, split=True)

        @bot.slash_command(name="bank_remove_split", description="Retirer une somme répartie entre les cibles", **guild_kwargs)
        async def bank_remove_split(
            interaction: nextcord.Interaction,
            total: int = nextcord.SlashOption(description="Somme totale à répartir (retirée au total)", min_value=0),
            user: Optional[nextcord.Member] = nextcord.SlashOption(description="(optionnel) ajoute 1 personne", required=False),
            role: Optional[nextcord.Role] = nextcord.SlashOption(description="(optionnel) rôle cible", required=False),
            targets: str = nextcord.SlashOption(description="Mentions/IDs @users/@roles (optionnel)", required=False, default=""),
            note: str = nextcord.SlashOption(description="Note (optionnel)", required=False, default=""),
        ):
            await self._bank_change_common(interaction, "remove_split", total, user, role, targets, note, split=True)

        @bot.slash_command(name="bank_undo", description="Annule ta dernière action banque (si <15min)", **guild_kwargs)
        async def bank_undo(interaction: nextcord.Interaction):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_bank(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)

            guild_id = interaction.guild.id
            actor_id = interaction.user.id

            async with self.store.lock:
                action = find_last_action_for_actor(self.store, guild_id, actor_id)
                if not action:
                    return await interaction.response.send_message("Aucune action annulable trouvée.", ephemeral=True)

                age = _now() - action.created_at
                if age > UNDO_WINDOW_SECONDS:
                    return await interaction.response.send_message("⛔ Trop tard : fenêtre d'undo dépassée (15 min).", ephemeral=True)

                reverse = {uid: -delta for uid, delta in action.deltas.items()}
                ok, reason = can_apply_deltas(self.store, guild_id, reverse, allow_negative=cfg.bank_allow_negative)
                if not ok:
                    return await interaction.response.send_message(f"⛔ Undo impossible : {reason}", ephemeral=True)

                apply_deltas(self.store, guild_id, reverse)
                action.undone = True
                action.undone_at = _now()
                self.store.bank_mark_action_undone(action.action_id, action.undone_at)
                self.store.save()

            await interaction.response.send_message(f"↩️ Undo OK : action `{action.action_type}` (`{action.action_id}`) annulée.", ephemeral=True)
