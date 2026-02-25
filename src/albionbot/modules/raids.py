import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Literal

import nextcord
from nextcord.ext import commands, tasks

from ..config import Config
from ..storage.store import Store, CompTemplate, CompRole, RaidEvent, Signup
from ..utils.discord import parse_ids, mention, channel_mention, has_any_role
from ..utils.text import chunk_text_lines, limit_str
from ..utils.timeutil import parse_dt_paris, TZ_PARIS
from ..ui.raid_views import RaidView, IpModal

log = logging.getLogger("albionbot.raids")

MIN_IP = 0
MAX_IP = 2500
AVA_RAID = "ava_raid"


def _now() -> int:
    return int(time.time())

def can_manage_raids(cfg: Config, member: nextcord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if cfg.raid_require_manage_guild and member.guild_permissions.manage_guild:
        return True
    if cfg.raid_manager_role_id is not None:
        return any(r.id == cfg.raid_manager_role_id for r in member.roles)
    return False

def role_map(tpl: CompTemplate):
    return {r.key: r for r in tpl.roles}

def count_main_for_role(raid: RaidEvent, role_key: str) -> int:
    return sum(1 for s in raid.signups.values() if s.role_key == role_key and s.status == "main")

def list_wait_for_role(raid: RaidEvent, role_key: str) -> List[Signup]:
    lst = [s for s in raid.signups.values() if s.role_key == role_key and s.status == "wait"]
    lst.sort(key=lambda x: x.joined_at)
    return lst

def promote_from_waitlist(raid: RaidEvent, tpl: CompTemplate, role_key: str) -> bool:
    rm = role_map(tpl)
    if role_key not in rm:
        return False
    if count_main_for_role(raid, role_key) >= rm[role_key].slots:
        return False
    for s in list_wait_for_role(raid, role_key):
        if s.user_id in raid.absent:
            continue
        s.status = "main"
        return True
    return False

def recompute_promotions(raid: RaidEvent, tpl: CompTemplate) -> None:
    rm = role_map(tpl)
    for key in rm.keys():
        while promote_from_waitlist(raid, tpl, key):
            pass

def raid_status(raid: RaidEvent) -> Literal["OPEN","PINGED","CLOSED"]:
    if raid.cleanup_done:
        return "CLOSED"
    if raid.ping_done:
        return "PINGED"
    return "OPEN"

def raid_status_style(status: str) -> Tuple[nextcord.Color, str]:
    if status == "OPEN":
        return nextcord.Color.green(), "🟢 Ouvert"
    if status == "PINGED":
        return nextcord.Color.red(), "🔴 En cours"
    return nextcord.Color.dark_grey(), "⚪ Terminé"

def build_roster_lines(raid: RaidEvent, tpl: CompTemplate) -> List[str]:
    by_role = {r.key: [] for r in tpl.roles}
    for s in raid.signups.values():
        if s.role_key in by_role:
            by_role[s.role_key].append(s)
    for k in by_role:
        by_role[k].sort(key=lambda x: x.joined_at)

    lines: List[str] = []
    for r in tpl.roles:
        users = by_role.get(r.key, [])
        main = [u for u in users if u.status == "main"]
        wait = [u for u in users if u.status == "wait"]
        header = f"**{r.label}** `{len(main)}/{r.slots}`"
        if wait:
            header += f"  `Prioritaire +{len(wait)}`"
        tags = []
        if r.ip_required:
            tags.append("IP")
        if r.required_role_ids:
            tags.append("req")
        if tags:
            header += f"  `{'/'.join(tags)}`"
        lines.append(header)

        def fmt_user(u: Signup) -> str:
            if r.ip_required:
                ip_txt = f"{u.ip}" if u.ip is not None else "?"
                return f"{mention(u.user_id)}({ip_txt})"
            return f"{mention(u.user_id)}"

        lines.append("• Inscrits: " + (" ".join(fmt_user(u) for u in main) if main else "*(vide)*"))
        if wait:
            lines.append("• Wait: " + " ".join(fmt_user(u) for u in wait))
        lines.append("")
    return lines

def build_raid_embed(guild: nextcord.Guild, raid: RaidEvent, tpl: CompTemplate) -> nextcord.Embed:
    status = raid_status(raid)
    color, status_txt = raid_status_style(status)

    e = nextcord.Embed(
        title=f"{raid.title}",
        description=limit_str(raid.description.strip() if raid.description else "", 1800),
        color=color,
    )

    if raid.extra_message.strip():
        e.add_field(name="", value=limit_str(raid.extra_message.strip(), 1000), inline=False)

    e.add_field(
        name="🕒",
        value=f"<t:{raid.start_at}:F>\n<t:{raid.start_at}:R>",
        inline=True,
    )

    if tpl.raid_required_role_ids:
        req_txt = " ".join(f"<@&{rid}>" for rid in tpl.raid_required_role_ids)
        e.add_field(name="🔒 Accès raid", value=f"Rôle(s) requis : {req_txt}", inline=False)

    roster_chunks = chunk_text_lines(build_roster_lines(raid, tpl), max_len=1000)

    reserved = 1 + (1 if tpl.raid_required_role_ids else 0) + (1 if raid.extra_message.strip() else 0) + (1 if raid.absent else 0)
    max_roster_fields = max(1, 25 - reserved)

    for idx, chunk in enumerate(roster_chunks[:max_roster_fields], start=1):
        e.add_field(
            name=f"📝 Compo & inscriptions ({idx}/{min(len(roster_chunks), max_roster_fields)})",
            value=chunk,
            inline=False,
        )
    if len(roster_chunks) > max_roster_fields:
        e.add_field(name="⚠️ Roster", value="Roster trop long (limite Discord embed).", inline=False)

    if raid.absent:
        abs_lines = [f"• {mention(uid)}" for uid in sorted(raid.absent)]
        e.add_field(name="🚫 Absents", value=limit_str("\n".join(abs_lines), 1000), inline=False)

    e.set_footer(text=f"{status_txt} • Raid ID: {raid.raid_id}")
    return e

def parse_comp_spec(spec: str) -> Tuple[List[CompRole], List[str]]:
    import re

    used_keys: Set[str] = set()
    roles: List[CompRole] = []
    warnings: List[str] = []

    lines = [ln.strip() for ln in (spec or "").splitlines() if ln.strip()]
    if not lines:
        return [], ["Spec vide."]

    for i, ln in enumerate(lines, start=1):
        parts = re.split(r"\s*[;|]\s*", ln)
        if len(parts) < 2:
            warnings.append(f"Ligne {i}: format invalide (min: Label;slots).")
            continue

        label = parts[0].strip()
        slots_raw = parts[1].strip()
        try:
            slots = int(slots_raw)
            if slots < 0:
                raise ValueError()
        except ValueError:
            warnings.append(f"Ligne {i}: slots invalide: '{slots_raw}'.")
            continue

        ip_required = False
        req_role_ids: List[int] = []
        key: Optional[str] = None

        for p in parts[2:]:
            p = p.strip()
            if not p:
                continue
            low = p.lower()

            if low in ("ip", "ip=1", "ip=true", "ip_required", "ip_required=true"):
                ip_required = True
                continue
            if low in ("ip=0", "ip=false", "noip", "ip_required=false"):
                ip_required = False
                continue

            if low.startswith("req=") or low.startswith("require=") or low.startswith("roles="):
                req_role_ids = parse_ids(p.split("=", 1)[1])
                continue

            if low.startswith("key="):
                key = p.split("=", 1)[1].strip()
                continue

            if re.fullmatch(r"[\d,\s<@&>]+", p) and any(ch.isdigit() for ch in p):
                req_role_ids = parse_ids(p)
                continue

            warnings.append(f"Ligne {i}: option inconnue '{p}' ignorée.")

        if not key:
            key = label.strip().lower()
            key = re.sub(r"[^a-z0-9]+", "_", key)
            key = re.sub(r"_+", "_", key).strip("_") or "role"

        base_key = key
        n = 2
        while key in used_keys:
            key = f"{base_key}_{n}"
            n += 1
        used_keys.add(key)

        roles.append(CompRole(
            key=key,
            label=label,
            slots=slots,
            ip_required=ip_required,
            required_role_ids=req_role_ids,
        ))

    if not roles:
        warnings.append("Aucun rôle valide.")
    return roles, warnings


class RaidModule:
    def __init__(self, bot: commands.Bot, store: Store, cfg: Config):
        self.bot = bot
        self.store = store
        self.cfg = cfg
        self._started = False
        self._loot_sessions: Dict[str, dict] = {}
        self._loot_scout_limits: Dict[int, Tuple[int, int]] = {}
        self._register_commands()

    def start(self):
        if not self._started:
            self.scheduler_loop.change_interval(seconds=self.cfg.sched_tick_seconds)
            self.scheduler_loop.start()
            self._started = True

    # ---------- Autocomplete
    def _autocomplete_template_names(self, user_input: str) -> List[str]:
        user_input = (user_input or "").lower().strip()
        names = sorted(self.store.templates.keys(), key=lambda s: s.lower())
        if not user_input:
            return names[:25]
        starts = [n for n in names if n.lower().startswith(user_input)]
        contains = [n for n in names if user_input in n.lower()]
        merged = []
        seen = set()
        for n in starts + contains:
            if n not in seen:
                merged.append(n)
                seen.add(n)
        return merged[:25]

    def _autocomplete_raid_ids(self, user_input: str, *, active_only: bool = True) -> List[str]:
        user_input = (user_input or "").lower().strip()
        raids = sorted(self.store.raids.values(), key=lambda r: r.created_at, reverse=True)
        if active_only:
            raids = [r for r in raids if not r.ping_done and not r.cleanup_done]
        ids = [r.raid_id for r in raids]
        if not user_input:
            return ids[:25]
        return [rid for rid in ids if user_input in rid.lower()][:25]

    def _find_raid_by_thread(self, thread_id: int) -> Optional[RaidEvent]:
        for r in self.store.raids.values():
            if r.thread_id == thread_id:
                return r
        return None

    def _parse_money_int(self, raw: str) -> int:
        txt = (raw or "").strip().replace(" ", "").replace(",", "").replace("_", "")
        if not txt:
            return 0
        return int(float(txt))

    def _get_scout_limits(self, guild_id: int) -> Tuple[int, int]:
        return self._loot_scout_limits.get(guild_id, (2_000_000, 10_000_000))

    def _compute_loot_split(self, *, total_net: int, rl_user_id: Optional[int], scout_user_id: Optional[int], players: List[int], rl_bonus_pct: float, scout_pct: float, scout_min: int, scout_max: int, maps_cost: int) -> dict:
        scout_raw = int(round(total_net * scout_pct / 100.0))
        scout_paid = max(scout_min, min(scout_max, scout_raw)) if scout_user_id else 0
        base_players = [uid for uid in players if uid != scout_user_id]
        post_scout = max(0, total_net - scout_paid)
        post_maps = max(0, post_scout - maps_cost)
        payouts: Dict[int, int] = {}
        rl_paid = 0
        if not base_players:
            share = 0
        else:
            bonus = max(0.0, rl_bonus_pct) / 100.0
            rl_in = rl_user_id in base_players if rl_user_id else False
            denom = (len(base_players) - 1 + (1.0 + bonus)) if rl_in else float(len(base_players))
            share = int(post_maps / denom) if denom > 0 else 0
            for uid in base_players:
                payouts[uid] = share
            if rl_in and rl_user_id is not None:
                rl_paid = int(round(share * (1.0 + bonus)))
                payouts[rl_user_id] = rl_paid
        return {"scout_paid": scout_paid, "post_scout": post_scout, "post_maps": post_maps, "share": share, "payouts": payouts, "rl_paid": rl_paid}


    # ---------- View builder
    def build_view(self, raid: RaidEvent, tpl: CompTemplate) -> RaidView:
        join_disabled = raid.ping_done or (_now() >= raid.start_at) or raid.cleanup_done
        return RaidView(
            bot=self.bot,
            raid=raid,
            template=tpl,
            join_disabled=join_disabled,
            actions_disabled=raid.ping_done or raid.cleanup_done,
            notify_disabled=raid.ping_done or raid.cleanup_done,
            on_select=self._on_select,
            on_absent=self._on_absent,
            on_leave=self._on_leave,
            on_notify=self._on_notify,
        )

    # ---------- Refresh message
    async def refresh_raid_message(self, raid_id: str) -> None:
        raid = self.store.raids.get(raid_id)
        if not raid or not raid.channel_id or not raid.message_id:
            return
        tpl = self.store.templates.get(raid.template_name)
        if not tpl:
            return
        try:
            channel = await self.bot.fetch_channel(raid.channel_id)
            if not isinstance(channel, (nextcord.TextChannel, nextcord.Thread)):
                return
            msg = await channel.fetch_message(raid.message_id)
            embed = build_raid_embed(channel.guild, raid, tpl)
            view = self.build_view(raid, tpl)
            await msg.edit(embed=embed, view=view)
            try:
                self.bot.add_view(view, message_id=raid.message_id)
            except Exception:
                pass
        except Exception:
            log.exception("Failed to refresh raid message")

    # ---------- Temp role / voice overwrites
    async def _ensure_temp_role(self, guild: nextcord.Guild, raid: RaidEvent) -> Optional[nextcord.Role]:
        if raid.temp_role_id:
            role = guild.get_role(raid.temp_role_id)
            if role:
                return role
        try:
            role = await guild.create_role(
                name=f"Raid-{raid.raid_id}",
                mentionable=True,
                reason=f"Temp raid role {raid.raid_id}",
            )
            raid.temp_role_id = role.id
            self.store.save()
            return role
        except Exception:
            log.exception("Failed to create temp role")
            return None

    async def _ensure_voice_overwrite(self, voice: nextcord.VoiceChannel, role: nextcord.Role) -> None:
        try:
            ow = voice.overwrites_for(role)
            ow.view_channel = True
            ow.connect = True
            ow.speak = True
            await voice.set_permissions(role, overwrite=ow, reason="Raid temp role access")
        except Exception:
            pass

    async def _remove_voice_overwrite(self, voice: nextcord.VoiceChannel, role: nextcord.Role) -> None:
        try:
            await voice.set_permissions(role, overwrite=None, reason="Raid cleanup remove overwrite")
        except Exception:
            pass

    async def _assign_temp_role_to_member(self, guild: nextcord.Guild, raid: RaidEvent, member: nextcord.Member) -> None:
        if raid.ping_done or raid.cleanup_done:
            return
        role = await self._ensure_temp_role(guild, raid)
        if not role:
            return
        if raid.voice_channel_id:
            vc = guild.get_channel(raid.voice_channel_id)
            if isinstance(vc, nextcord.VoiceChannel):
                await self._ensure_voice_overwrite(vc, role)
        try:
            await member.add_roles(role, reason=f"Raid late signup {raid.raid_id}")
        except Exception:
            pass

    async def _assign_temp_role_bulk(self, raid: RaidEvent) -> None:
        if not raid.channel_id:
            return
        channel = await self.bot.fetch_channel(raid.channel_id)
        if not isinstance(channel, (nextcord.TextChannel, nextcord.Thread)):
            return
        guild = channel.guild
        role = await self._ensure_temp_role(guild, raid)
        if not role:
            return
        if raid.voice_channel_id:
            vc = guild.get_channel(raid.voice_channel_id)
            if isinstance(vc, nextcord.VoiceChannel):
                await self._ensure_voice_overwrite(vc, role)

        for uid in list(raid.signups.keys()):
            if uid in raid.absent:
                continue
            member = guild.get_member(uid)
            if not member or member.bot:
                continue
            try:
                await member.add_roles(role, reason=f"Raid prep {raid.raid_id}")
            except Exception:
                pass

    async def _ping_raid(self, raid: RaidEvent) -> None:
        if not raid.channel_id:
            return
        ch = await self.bot.fetch_channel(raid.channel_id)
        if not isinstance(ch, (nextcord.TextChannel, nextcord.Thread)):
            return
        guild = ch.guild

        role_mention = ""
        if raid.temp_role_id:
            role = guild.get_role(raid.temp_role_id)
            if role:
                role_mention = role.mention

        msg = f"⏰ **MASS UP** {role_mention}".strip()
        if raid.voice_channel_id:
            msg += f"\n➡️{channel_mention(raid.voice_channel_id)}"


        try:
            await ch.send(msg)
        except Exception:
            pass

        # Optional DM ping for users who enabled notifications on this raid.
        for uid in list(raid.dm_notify_users):
            member = guild.get_member(uid)
            if not member or member.bot:
                continue
            try:
                dm = await member.create_dm()
                dm_msg = f"⏰ **MASS UP** — Raid **{raid.title}** (`{raid.raid_id}`)"
                if raid.voice_channel_id:
                    dm_msg += f"\n➡️ Rejoins le vocal: {channel_mention(raid.voice_channel_id)}"
                await dm.send(dm_msg)
            except Exception:
                pass

        if raid.thread_id:
            try:
                th = await self.bot.fetch_channel(raid.thread_id)
                if isinstance(th, nextcord.Thread):
                    await th.send(msg)
            except Exception:
                pass

    async def _send_voice_report(self, raid: RaidEvent) -> None:
        if not raid.channel_id:
            return
        ch = await self.bot.fetch_channel(raid.channel_id)
        if not isinstance(ch, (nextcord.TextChannel, nextcord.Thread)):
            return
        guild = ch.guild
        leader = guild.get_member(raid.created_by)

        voice_member_ids: Set[int] = set()
        vc = guild.get_channel(raid.voice_channel_id) if raid.voice_channel_id else None
        has_voice = isinstance(vc, nextcord.VoiceChannel)
        if has_voice:
            voice_member_ids = {m.id for m in vc.members if not m.bot}

        expected = set(raid.signups.keys()) - set(raid.absent)
        if has_voice:
            present_expected = sorted(expected.intersection(voice_member_ids))
            present_unexpected = sorted(voice_member_ids - expected)
            missing_expected = sorted(expected - voice_member_ids)
        else:
            present_expected = sorted(expected)
            present_unexpected = []
            missing_expected = []

        raid.last_voice_present_ids = list(present_expected)

        def fmt(ids: List[int]) -> str:
            if not ids:
                return "*(aucun)*"
            return "\n".join(f"• {mention(uid)}" for uid in ids)

        if has_voice:
            content = (
                f"📞 **Appel vocal (T+{self.cfg.voice_check_after_minutes}min)** — Raid **{raid.title}** (`{raid.raid_id}`)\n"
                f"🔊 Vocal: {channel_mention(raid.voice_channel_id)}\n\n"
                f"✅ **Présents attendus** ({len(present_expected)}):\n{fmt(present_expected)}\n\n"
                f"⚠️ **Présents inattendus** ({len(present_unexpected)}):\n{fmt(present_unexpected)}\n\n"
                f"❌ **Attendus manquants** ({len(missing_expected)}):\n{fmt(missing_expected)}"
            )
        else:
            content = (
                f"📝 **Présences (sans vocal défini)** — Raid **{raid.title}** (`{raid.raid_id}`)\n\n"
                f"✅ **Inscrits pris comme présents** ({len(present_expected)}):\n{fmt(present_expected)}"
            )

        report_embed = nextcord.Embed(
            title=("📞 Appel vocal" if has_voice else "📝 Présences (sans vocal)"),
            description=limit_str(content, 3900),
            color=nextcord.Color.dark_teal(),
        )

        sent = False
        if leader:
            try:
                dm = await leader.create_dm()
                await dm.send(embed=report_embed)
                sent = True
            except Exception:
                sent = False

        if not sent and raid.thread_id:
            try:
                th = await self.bot.fetch_channel(raid.thread_id)
                if isinstance(th, nextcord.Thread):
                    await th.send(embed=report_embed)
                    sent = True
            except Exception:
                pass

        if not sent:
            try:
                await ch.send(embed=report_embed)
            except Exception:
                pass

    async def _cleanup_raid(self, raid: RaidEvent) -> None:
        # Temp roles are intentionally kept after raid end for later payout/accounting workflows.
        return

    async def _cleanup_temp_role_after_split(self, raid: RaidEvent) -> None:
        if not raid.channel_id or not raid.temp_role_id:
            return
        try:
            ch = await self.bot.fetch_channel(raid.channel_id)
        except Exception:
            return
        if not isinstance(ch, (nextcord.TextChannel, nextcord.Thread)):
            return
        guild = ch.guild
        role = guild.get_role(raid.temp_role_id)
        if not role:
            raid.temp_role_id = None
            self.store.save()
            return
        for uid in list(raid.signups.keys()):
            m = guild.get_member(uid)
            if not m or m.bot:
                continue
            try:
                await m.remove_roles(role, reason=f"Loot split cleanup {raid.raid_id}")
            except Exception:
                pass
        if raid.voice_channel_id:
            vc = guild.get_channel(raid.voice_channel_id)
            if isinstance(vc, nextcord.VoiceChannel):
                await self._remove_voice_overwrite(vc, role)
        try:
            await role.delete(reason=f"Loot split cleanup {raid.raid_id}")
        except Exception:
            pass
        raid.temp_role_id = None
        self.store.save()

    # ---------- UI callbacks
    async def _on_select(self, interaction: nextcord.Interaction, raid_id: str, role_key: str):
        raid = self.store.raids.get(raid_id)
        if not raid:
            return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
        if raid.ping_done or _now() >= raid.start_at or raid.cleanup_done:
            return await interaction.response.send_message("⛔ Inscriptions fermées (Mass-up déjà envoyé).", ephemeral=True)
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Contexte serveur requis.", ephemeral=True)

        tpl = self.store.templates.get(raid.template_name)
        if not tpl:
            return await interaction.response.send_message("Template introuvable.", ephemeral=True)

        member = interaction.user

        if tpl.raid_required_role_ids and not has_any_role(member, tpl.raid_required_role_ids):
            req_txt = " ".join(f"<@&{rid}>" for rid in tpl.raid_required_role_ids)
            return await interaction.response.send_message(f"🔒 Accès raid requis : {req_txt}", ephemeral=True)

        rm = role_map(tpl)
        role_def = rm.get(role_key)
        if not role_def:
            return await interaction.response.send_message("Rôle invalide.", ephemeral=True)
        if role_key == "raid_leader":
            return await interaction.response.send_message("⛔ Le rôle Raid Leader est réservé au créateur du raid.", ephemeral=True)

        if role_def.required_role_ids and not has_any_role(member, role_def.required_role_ids):
            req_txt = " ".join(f"<@&{rid}>" for rid in role_def.required_role_ids)
            return await interaction.response.send_message(f"🔒 Pour ce rôle : {req_txt}", ephemeral=True)

        async with self.store.lock:
            raid = self.store.raids.get(raid_id)
            if not raid:
                return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            cur_signup = raid.signups.get(member.id)
            if cur_signup and cur_signup.role_key == "raid_leader" and role_key != "raid_leader":
                return await interaction.response.send_message("⛔ Le Raid Leader ne peut pas s'inscrire sur un autre rôle.", ephemeral=True)
            raid.absent.discard(member.id)
            self.store.save()

        if role_def.ip_required:
            modal = IpModal(bot=self.bot, raid_id=raid_id, role_key=role_key, role_label=role_def.label, on_submit=self._ip_modal_submit)
            return await interaction.response.send_modal(modal)

        await self._finalize_join(interaction, raid_id, role_key, ip=None)

    async def _ip_modal_submit(self, interaction: nextcord.Interaction, raid_id: str, role_key: str, ip_raw: str):
        try:
            ip = int(ip_raw)
        except ValueError:
            return await interaction.response.send_message("IP invalide (entier attendu).", ephemeral=True)
        if ip < MIN_IP or ip > MAX_IP:
            return await interaction.response.send_message(f"IP hors limites ({MIN_IP}–{MAX_IP}).", ephemeral=True)
        await self._finalize_join(interaction, raid_id, role_key, ip=ip)

    async def _finalize_join(self, interaction: nextcord.Interaction, raid_id: str, role_key: str, ip: Optional[int]):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Contexte serveur requis.", ephemeral=True)
        member = interaction.user
        late_assign = False

        async with self.store.lock:
            raid = self.store.raids.get(raid_id)
            if not raid:
                return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            tpl = self.store.templates.get(raid.template_name)
            if not tpl:
                return await interaction.response.send_message("Template introuvable.", ephemeral=True)

            if raid.ping_done or _now() >= raid.start_at or raid.cleanup_done:
                return await interaction.response.send_message("⛔ Inscriptions fermées.", ephemeral=True)

            rm = role_map(tpl)
            role_def = rm.get(role_key)
            if not role_def:
                return await interaction.response.send_message("Rôle invalide.", ephemeral=True)
            if role_key == "raid_leader":
                return await interaction.response.send_message("⛔ Le rôle Raid Leader est réservé au créateur du raid.", ephemeral=True)
            cur_signup = raid.signups.get(member.id)
            if cur_signup and cur_signup.role_key == "raid_leader" and role_key != "raid_leader":
                return await interaction.response.send_message("⛔ Le Raid Leader ne peut pas s'inscrire sur un autre rôle.", ephemeral=True)

            main_count = count_main_for_role(raid, role_key)
            status = "main" if main_count < role_def.slots else "wait"

            raid.signups[member.id] = Signup(user_id=member.id, role_key=role_key, status=status, ip=ip, joined_at=_now())
            recompute_promotions(raid, tpl)

            if raid.prep_done and not raid.ping_done:
                late_assign = True

            self.store.save()

        if late_assign:
            raid = self.store.raids.get(raid_id)
            if raid:
                await self._assign_temp_role_to_member(interaction.guild, raid, member)

        await interaction.response.send_message(f"✅ Inscrit sur **{role_def.label}** ({'PRIORITAIRE' if status=='main' else 'WAITLIST'}).", ephemeral=True)
        await self.refresh_raid_message(raid_id)

    async def _on_notify(self, interaction: nextcord.Interaction, raid_id: str):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Contexte serveur requis.", ephemeral=True)
        uid = interaction.user.id
        async with self.store.lock:
            raid = self.store.raids.get(raid_id)
            if not raid:
                return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            if raid.ping_done or raid.cleanup_done:
                return await interaction.response.send_message("⛔ Notifications closes après mass-up.", ephemeral=True)
            if uid in raid.dm_notify_users:
                raid.dm_notify_users.discard(uid)
                self.store.save()
                msg = "🔕 Notifications DM désactivées pour ce raid."
            else:
                raid.dm_notify_users.add(uid)
                self.store.save()
                msg = "🔔 Notifications DM activées pour ce raid."
        await interaction.response.send_message(msg, ephemeral=True)

    async def _on_absent(self, interaction: nextcord.Interaction, raid_id: str):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Contexte serveur requis.", ephemeral=True)
        uid = interaction.user.id

        async with self.store.lock:
            raid = self.store.raids.get(raid_id)
            if not raid:
                return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            tpl = self.store.templates.get(raid.template_name)
            if not tpl:
                return await interaction.response.send_message("Template introuvable.", ephemeral=True)
            if raid.ping_done or raid.cleanup_done:
                return await interaction.response.send_message("⛔ Actions indisponibles après mass-up.", ephemeral=True)

            cur = raid.signups.get(uid)
            if cur and cur.role_key == "raid_leader":
                return await interaction.response.send_message("⛔ Le Raid Leader ne peut pas se mettre absent.", ephemeral=True)

            if uid in raid.absent:
                raid.absent.discard(uid)
                self.store.save()
                await interaction.response.send_message("✅ Absent retiré.", ephemeral=True)
            else:
                raid.absent.add(uid)
                if uid in raid.signups:
                    del raid.signups[uid]
                recompute_promotions(raid, tpl)
                self.store.save()
                await interaction.response.send_message("🚫 Marqué absent (retiré roster/waitlist).", ephemeral=True)

        await self.refresh_raid_message(raid_id)

    async def _on_leave(self, interaction: nextcord.Interaction, raid_id: str):
        if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
            return await interaction.response.send_message("Contexte serveur requis.", ephemeral=True)
        uid = interaction.user.id
        changed = False

        async with self.store.lock:
            raid = self.store.raids.get(raid_id)
            if not raid:
                return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            tpl = self.store.templates.get(raid.template_name)
            if not tpl:
                return await interaction.response.send_message("Template introuvable.", ephemeral=True)
            if raid.ping_done or raid.cleanup_done:
                return await interaction.response.send_message("⛔ Actions indisponibles après mass-up.", ephemeral=True)

            cur = raid.signups.get(uid)
            if cur and cur.role_key == "raid_leader":
                return await interaction.response.send_message("⛔ Le Raid Leader ne peut pas quitter le raid.", ephemeral=True)

            if uid in raid.signups:
                del raid.signups[uid]
                changed = True
            if uid in raid.absent:
                raid.absent.discard(uid)
                changed = True

            if changed:
                recompute_promotions(raid, tpl)
                self.store.save()

        if not changed:
            return await interaction.response.send_message("Tu n'es ni inscrit ni absent.", ephemeral=True)

        await interaction.response.send_message("✅ Retiré.", ephemeral=True)
        await self.refresh_raid_message(raid_id)

    # ---------- DM wizard
    async def _dm_wizard_template(self, member: nextcord.Member, mode: Literal["create","edit"], template_name: Optional[str] = None) -> None:
        dm = await member.create_dm()

        def check_msg(m: nextcord.Message) -> bool:
            return m.author.id == member.id and m.channel.id == dm.id

        async def ask(prompt: str, timeout: int = 600) -> Optional[str]:
            await dm.send(prompt)
            try:
                m = await self.bot.wait_for("message", check=check_msg, timeout=timeout)
                if m.content.strip().lower() in ("cancel", "stop", "annule", "annuler"):
                    await dm.send("❌ Wizard annulé.")
                    return None
                return m.content
            except asyncio.TimeoutError:
                await dm.send("⌛ Timeout. Relance la commande si besoin.")
                return None

        base: Optional[CompTemplate] = None
        if mode == "edit":
            if not template_name or template_name not in self.store.templates:
                await dm.send("❌ Template introuvable pour édition.")
                return
            base = self.store.templates[template_name]

        await dm.send(
            "🧩 **Wizard Template** (tape `cancel` pour arrêter)\n"
            + ("Mode: **Création**" if mode == "create" else f"Mode: **Édition** (`{base.name}`)")
        )

        if mode == "create":
            name = await ask("1) Nom du template ?")
            if not name:
                return
            name = name.strip()
        else:
            name = await ask(f"1) Nom du template ? (envoie `.` pour garder: `{base.name}`)")
            if name is None:
                return
            name = base.name if name.strip() == "." else name.strip()

        desc_prompt = "2) Description du template ? (emojis OK) (ou `-` pour vide)"
        if mode == "edit":
            desc_prompt = f"2) Description ? (`.` pour garder)\nActuelle:\n```{limit_str(base.description, 800)}```"
        desc = await ask(desc_prompt)
        if desc is None:
            return
        if mode == "edit" and desc.strip() == ".":
            desc = base.description
        else:
            desc = "" if desc.strip() == "-" else desc.strip()

        type_prompt = "2b) Type de contenu ? (`ava_raid`, `pvp`, `pve`)"
        if mode == "edit":
            cur_type = getattr(base, "content_type", "pvp")
            type_prompt = f"2b) Type de contenu ? (`.` pour garder) Actuel: `{cur_type}`"
        content_type_raw = await ask(type_prompt)
        if content_type_raw is None:
            return
        if mode == "edit" and content_type_raw.strip() == ".":
            content_type = getattr(base, "content_type", "pvp")
        else:
            content_type = content_type_raw.strip().lower()
            if content_type not in ("ava_raid", "pvp", "pve"):
                await dm.send("❌ Type invalide. Utilise `ava_raid`, `pvp` ou `pve`.")
                return

        raid_req_prompt = "3) Rôle(s) Discord requis pour rejoindre le RAID ? (IDs/mentions) (ou `-` pour aucun)"
        if mode == "edit":
            cur = ", ".join(map(str, base.raid_required_role_ids)) if base.raid_required_role_ids else "-"
            raid_req_prompt = f"3) Rôle(s) requis RAID ? (`.` pour garder) Actuel: `{cur}`"
        raid_req = await ask(raid_req_prompt)
        if raid_req is None:
            return
        if mode == "edit" and raid_req.strip() == ".":
            raid_req_ids = list(base.raid_required_role_ids)
        else:
            raid_req_ids = [] if raid_req.strip() == "-" else parse_ids(raid_req)

        scout_req_ids: List[int] = []
        if content_type == AVA_RAID:
            cur_scout_req: List[int] = []
            if mode == "edit" and base:
                for rr in base.roles:
                    if rr.key == "scout":
                        cur_scout_req = list(rr.required_role_ids)
                        break
            scout_prompt = "3b) Rôle(s) Discord requis pour rejoindre **Scout** ? (IDs/mentions) (`-` pour aucun)"
            if mode == "edit":
                cur = ", ".join(map(str, cur_scout_req)) if cur_scout_req else "-"
                scout_prompt = f"3b) Rôle(s) requis pour Scout ? (`.` pour garder) Actuel: `{cur}`"
            scout_req = await ask(scout_prompt)
            if scout_req is None:
                return
            if mode == "edit" and scout_req.strip() == ".":
                scout_req_ids = cur_scout_req
            else:
                scout_req_ids = [] if scout_req.strip() == "-" else parse_ids(scout_req)

        await dm.send(
            "4) **Spec des rôles** (1 ligne = 1 rôle). Format:\n"
            "`Label ; slots ; [ip] ; [req=<role ids/mentions>] ; [key=...]`\n"
            "Ex:\n```RL;1\nOffTank;1\nSC;1;ip\nDPS;3;ip```\n"
            + ("(envoie `.` pour garder le spec actuel)" if mode == "edit" else "")
        )
        spec = await ask("(colle ici ton bloc de rôles)")
        if not spec:
            return

        if mode == "edit" and spec.strip() == ".":
            roles = list(base.roles)
            warnings = []
        else:
            roles, warnings = parse_comp_spec(spec)
            if not roles:
                await dm.send("❌ Spec invalide.")
                return

        if content_type == AVA_RAID:
            roles = [r for r in roles if r.key not in ("raid_leader", "scout")]
            forced = [
                CompRole(key="raid_leader", label="Raid Leader", slots=1, ip_required=False, required_role_ids=[]),
                CompRole(key="scout", label="Scout", slots=1, ip_required=False, required_role_ids=scout_req_ids),
            ]
            roles = [forced[0]] + roles + [forced[1]]

        async with self.store.lock:
            if mode == "edit" and base and name != base.name and base.name in self.store.templates:
                del self.store.templates[base.name]
            self.store.templates[name] = CompTemplate(
                name=name,
                description=desc,
                created_by=member.id,
                content_type=content_type,
                raid_required_role_ids=raid_req_ids,
                roles=roles,
            )
            self.store.save()

        wtxt = ""
        if warnings:
            wtxt = "\n⚠️ Warnings:\n" + "\n".join(f"• {w}" for w in warnings[:10])
        await dm.send(f"✅ Template **{name}** enregistré. Rôles: **{len(roles)}**.{wtxt}")

    # ---------- Scheduler
    @tasks.loop(seconds=15)
    async def scheduler_loop(self):
        now = _now()
        for raid in list(self.store.raids.values()):
            if raid.cleanup_done:
                continue

            prep_at = raid.start_at - raid.prep_minutes * 60
            if not raid.prep_done and now >= prep_at:
                async with self.store.lock:
                    r = self.store.raids.get(raid.raid_id)
                    if r and not r.prep_done and not r.ping_done:
                        try:
                            await self._assign_temp_role_bulk(r)
                        except Exception:
                            log.exception("Prep failed")
                        r.prep_done = True
                        self.store.save()
                await self.refresh_raid_message(raid.raid_id)

            if not raid.ping_done and now >= raid.start_at:
                async with self.store.lock:
                    r = self.store.raids.get(raid.raid_id)
                    if r and not r.ping_done:
                        try:
                            await self._ping_raid(r)
                        except Exception:
                            log.exception("Ping failed")
                        r.ping_done = True
                        self.store.save()
                await self.refresh_raid_message(raid.raid_id)

            check_at = raid.start_at + self.cfg.voice_check_after_minutes * 60
            if not raid.voice_check_done and now >= check_at:
                async with self.store.lock:
                    r = self.store.raids.get(raid.raid_id)
                    if r and not r.voice_check_done:
                        try:
                            await self._send_voice_report(r)
                        except Exception:
                            log.exception("Voice report failed")
                        r.voice_check_done = True
                        self.store.save()

            cleanup_at = raid.start_at + raid.cleanup_minutes * 60
            if not raid.cleanup_done and now >= cleanup_at:
                async with self.store.lock:
                    r = self.store.raids.get(raid.raid_id)
                    if r and not r.cleanup_done:
                        try:
                            await self._cleanup_raid(r)
                        except Exception:
                            log.exception("Cleanup failed")
                        r.cleanup_done = True
                        self.store.save()
                await self.refresh_raid_message(raid.raid_id)

    # ---------- Commands
    def _register_commands(self):
        bot = self.bot
        cfg = self.cfg
        guild_kwargs = {"guild_ids": cfg.guild_ids} if cfg.guild_ids else {}

        @bot.slash_command(name="comp_wizard", description="Créer un template via DM", **guild_kwargs)
        async def comp_wizard(interaction: nextcord.Interaction):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)
            await interaction.response.send_message("✅ Wizard envoyé en DM.", ephemeral=True)
            await self._dm_wizard_template(interaction.user, "create")

        @bot.slash_command(name="comp_edit", description="Modifier un template via DM", **guild_kwargs)
        async def comp_edit(interaction: nextcord.Interaction, name: str = nextcord.SlashOption(description="Template", autocomplete=True)):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)
            if name not in self.store.templates:
                return await interaction.response.send_message("Template introuvable.", ephemeral=True)
            await interaction.response.send_message("✅ Wizard d’édition envoyé en DM.", ephemeral=True)
            await self._dm_wizard_template(interaction.user, "edit", template_name=name)

        @comp_edit.on_autocomplete("name")
        async def _comp_edit_ac(interaction: nextcord.Interaction, user_input: str):
            return self._autocomplete_template_names(user_input)

        @bot.slash_command(name="comp_delete", description="Supprimer un template", **guild_kwargs)
        async def comp_delete(interaction: nextcord.Interaction, name: str = nextcord.SlashOption(description="Template", autocomplete=True)):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)
            async with self.store.lock:
                if name not in self.store.templates:
                    return await interaction.response.send_message("Template introuvable.", ephemeral=True)
                del self.store.templates[name]
                self.store.save()
            await interaction.response.send_message(f"🗑️ Template **{name}** supprimé.", ephemeral=True)

        @comp_delete.on_autocomplete("name")
        async def _comp_delete_ac(interaction: nextcord.Interaction, user_input: str):
            return self._autocomplete_template_names(user_input)

        @bot.slash_command(name="comp_list", description="Lister les templates", **guild_kwargs)
        async def comp_list(interaction: nextcord.Interaction):
            if not self.store.templates:
                return await interaction.response.send_message("Aucun template.", ephemeral=True)
            lines = [f"• **{tp.name}** — rôles: {len(tp.roles)}" for tp in sorted(self.store.templates.values(), key=lambda x: x.created_at, reverse=True)]
            embed = nextcord.Embed(title="🧩 Templates", description=limit_str("\n".join(lines[:40]), 3900), color=nextcord.Color.blurple())
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @bot.slash_command(name="raid_open", description="Ouvrir un raid depuis un template", **guild_kwargs)
        async def raid_open(
            interaction: nextcord.Interaction,
            template: str = nextcord.SlashOption(description="Template", autocomplete=True),
            start: str = nextcord.SlashOption(description="Date/heure Paris: YYYY-MM-DD HH:MM"),
            voice_channel: Optional[nextcord.VoiceChannel] = nextcord.SlashOption(
                description="Vocal privé existant",
                required=False,
                channel_types=[nextcord.ChannelType.voice],
            ),
            title: str = nextcord.SlashOption(description="Titre (optionnel)", required=False, default=""),
            description: str = nextcord.SlashOption(description="Description (optionnel)", required=False, default=""),
            extra_message: str = nextcord.SlashOption(description="Message RL (optionnel)", required=False, default=""),
            prep_minutes: int = nextcord.SlashOption(description="Rôle temp X min avant", required=False, default=cfg.default_prep_minutes, min_value=0, max_value=120),
            cleanup_minutes: int = nextcord.SlashOption(description="Cleanup X min après", required=False, default=cfg.default_cleanup_minutes, min_value=0, max_value=240),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)

            tpl = self.store.templates.get(template)
            if not tpl:
                return await interaction.response.send_message("Template introuvable.", ephemeral=True)

            try:
                start_at = parse_dt_paris(start)
            except Exception:
                return await interaction.response.send_message("Format date invalide. Ex: 2026-02-24 20:30", ephemeral=True)

            raid_id = f"R{int(time.time()*1000)}"
            raid = RaidEvent(
                raid_id=raid_id,
                template_name=tpl.name,
                title=title.strip() or tpl.name,
                description=description.strip() or tpl.description,
                extra_message=extra_message.strip(),
                start_at=start_at,
                created_by=interaction.user.id,
                prep_minutes=prep_minutes,
                cleanup_minutes=cleanup_minutes,
                voice_channel_id=(voice_channel.id if voice_channel else None),
            )

            if getattr(tpl, "content_type", "pvp") == AVA_RAID:
                if any(r.key == "raid_leader" for r in tpl.roles):
                    raid.signups[interaction.user.id] = Signup(
                        user_id=interaction.user.id,
                        role_key="raid_leader",
                        status="main",
                        ip=None,
                        joined_at=_now(),
                    )

            embed = build_raid_embed(interaction.guild, raid, tpl)
            view = self.build_view(raid, tpl)

            await interaction.response.send_message(embed=embed, view=view)
            msg = await interaction.original_message()

            # thread auto
            thread = None
            try:
                thread_name = limit_str(f"{raid.title} • {datetime.fromtimestamp(raid.start_at, TZ_PARIS).strftime('%d/%m %H:%M')}", 95)
                thread = await msg.create_thread(name=thread_name, auto_archive_duration=1440)
            except Exception:
                thread = None

            async with self.store.lock:
                raid.channel_id = msg.channel.id
                raid.message_id = msg.id
                raid.thread_id = thread.id if thread else None
                self.store.raids[raid_id] = raid
                self.store.save()

            try:
                self.bot.add_view(view, message_id=msg.id)
            except Exception:
                pass

            if thread:
                try:
                    await thread.send(
                        f"**{raid.title}**\n"
                        f"🕒 <t:{raid.start_at}:F>\n"
                    )
                except Exception:
                    pass

        @raid_open.on_autocomplete("template")
        async def _raid_open_ac(interaction: nextcord.Interaction, user_input: str):
            return self._autocomplete_template_names(user_input)

        @bot.slash_command(name="raid_list", description="Lister les raids", **guild_kwargs)
        async def raid_list(interaction: nextcord.Interaction):
            if not self.store.raids:
                return await interaction.response.send_message("Aucun raid.", ephemeral=True)
            lines = []
            for r in sorted(self.store.raids.values(), key=lambda x: x.created_at, reverse=True):
                st = raid_status(r)
                _, st_txt = raid_status_style(st)
                lines.append(f"• **{r.raid_id}** — {r.title} — <t:{r.start_at}:F> — {st_txt}")
            embed = nextcord.Embed(title="📋 Raids", description=limit_str("\n".join(lines[:40]), 3900), color=nextcord.Color.blurple())
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @bot.slash_command(name="raid_edit", description="Modifier un raid en cours", **guild_kwargs)
        async def raid_edit(
            interaction: nextcord.Interaction,
            raid_id: str = nextcord.SlashOption(description="Raid ID"),
            title: str = nextcord.SlashOption(description="Nouveau titre", required=False, default=""),
            start: str = nextcord.SlashOption(description="Nouvelle date Paris: YYYY-MM-DD HH:MM", required=False, default=""),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)
            if not title.strip() and not start.strip():
                return await interaction.response.send_message("Renseigne au moins un champ à modifier (title et/ou start).", ephemeral=True)

            new_start_at = None
            if start.strip():
                try:
                    new_start_at = parse_dt_paris(start)
                except Exception:
                    return await interaction.response.send_message("Format date invalide. Ex: 2026-02-24 20:30", ephemeral=True)

            async with self.store.lock:
                raid = self.store.raids.get(raid_id)
                if not raid:
                    return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
                if raid.cleanup_done:
                    return await interaction.response.send_message("⛔ Raid terminé, modification impossible.", ephemeral=True)

                if title.strip():
                    raid.title = title.strip()
                if new_start_at is not None:
                    raid.start_at = new_start_at
                self.store.save()

            await self.refresh_raid_message(raid_id)

            raid = self.store.raids.get(raid_id)
            if raid and raid.thread_id:
                try:
                    th = await self.bot.fetch_channel(raid.thread_id)
                    if isinstance(th, nextcord.Thread):
                        thread_name = limit_str(f"{raid.title} • {datetime.fromtimestamp(raid.start_at, TZ_PARIS).strftime('%d/%m %H:%M')}", 95)
                        await th.edit(name=thread_name)
                except Exception:
                    pass

            await interaction.response.send_message("✅ Raid modifié.", ephemeral=True)

        @raid_edit.on_autocomplete("raid_id")
        async def _raid_edit_ac(interaction: nextcord.Interaction, user_input: str):
            return self._autocomplete_raid_ids(user_input)

        @bot.slash_command(name="raid_close", description="Fermer un raid (stop inscriptions immédiatement)", **guild_kwargs)
        async def raid_close(interaction: nextcord.Interaction, raid_id: str = nextcord.SlashOption(description="Raid ID")):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)
            async with self.store.lock:
                raid = self.store.raids.get(raid_id)
                if not raid:
                    return await interaction.response.send_message("Raid introuvable.", ephemeral=True)
                raid.ping_done = True
                self.store.save()
            await self.refresh_raid_message(raid_id)
            await interaction.response.send_message("🔒 Raid fermé.", ephemeral=True)

        @raid_close.on_autocomplete("raid_id")
        async def _raid_close_ac(interaction: nextcord.Interaction, user_input: str):
            return self._autocomplete_raid_ids(user_input)

        @bot.slash_command(name="loot_scout_limits", description="Définir min/max de part scout", **guild_kwargs)
        async def loot_scout_limits(
            interaction: nextcord.Interaction,
            min_amount: int = nextcord.SlashOption(description="Minimum scout", min_value=0),
            max_amount: int = nextcord.SlashOption(description="Maximum scout", min_value=0),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not can_manage_raids(cfg, interaction.user):
                return await interaction.response.send_message("⛔ Permission insuffisante.", ephemeral=True)
            if min_amount > max_amount:
                return await interaction.response.send_message("Min doit être <= max.", ephemeral=True)
            self._loot_scout_limits[interaction.guild.id] = (int(min_amount), int(max_amount))
            await interaction.response.send_message(f"✅ Limites scout: {min_amount:,} - {max_amount:,}", ephemeral=True)

        @bot.slash_command(name="loot_split", description="Préparer la répartition loot (thread raid)", **guild_kwargs)
        async def loot_split(
            interaction: nextcord.Interaction,
            coffre_value: str = nextcord.SlashOption(description="Valeur coffre"),
            silver_bags: str = nextcord.SlashOption(description="Valeur sacs d'argent"),
            tax_percent: float = nextcord.SlashOption(description="Tax coffre %", required=False, default=10.0),
            rl_bonus_percent: float = nextcord.SlashOption(description="Bonus RL %", required=False, default=7.5),
            scout_percent: float = nextcord.SlashOption(description="Part scout %", required=False, default=10.0),
            maps: str = nextcord.SlashOption(description="Maps (lignes: tier;prix;finish[1/0])", required=False, default=""),
            add_players: str = nextcord.SlashOption(description="Ajouter joueurs (mentions/ids)", required=False, default=""),
            remove_players: str = nextcord.SlashOption(description="Retirer joueurs (mentions/ids)", required=False, default=""),
            rl_override: str = nextcord.SlashOption(description="Override RL (mention/id)", required=False, default=""),
            scout_override: str = nextcord.SlashOption(description="Override Scout (mention/id)", required=False, default=""),
        ):
            if not interaction.guild or not isinstance(interaction.user, nextcord.Member):
                return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
            if not isinstance(interaction.channel, nextcord.Thread):
                return await interaction.response.send_message("Commande utilisable uniquement dans un thread de raid.", ephemeral=True)

            raid = self._find_raid_by_thread(interaction.channel.id)
            if not raid:
                return await interaction.response.send_message("Thread non lié à un raid.", ephemeral=True)

            if not can_manage_raids(cfg, interaction.user):
                s = raid.signups.get(interaction.user.id)
                if not (s and s.role_key == "raid_leader"):
                    return await interaction.response.send_message("⛔ Seul le Raid Leader ou un manager peut lancer la répartition.", ephemeral=True)

            try:
                coffre_raw = self._parse_money_int(coffre_value)
                bags_raw = self._parse_money_int(silver_bags)
            except Exception:
                return await interaction.response.send_message("Montants invalides.", ephemeral=True)

            rl_user_id = raid.created_by
            scout_user_id = None
            for uid, s in raid.signups.items():
                if s.role_key == "raid_leader":
                    rl_user_id = uid
                if s.role_key == "scout":
                    scout_user_id = uid

            rl_ids = parse_ids(rl_override)
            scout_ids = parse_ids(scout_override)
            if rl_ids:
                rl_user_id = rl_ids[0]
            if scout_ids:
                scout_user_id = scout_ids[0]

            players = list(raid.last_voice_present_ids or [])
            if not players:
                players = sorted([uid for uid in raid.signups.keys() if uid not in raid.absent])
            for uid in parse_ids(add_players):
                if uid not in players:
                    players.append(uid)
            to_remove = set(parse_ids(remove_players))
            players = [uid for uid in players if uid not in to_remove]

            maps_lines = [ln.strip() for ln in maps.splitlines() if ln.strip()]
            map_rows = []
            maps_cost = 0
            finished_maps_count = 0
            for ln in maps_lines:
                parts = [x.strip() for x in ln.split(";")]
                if len(parts) < 2:
                    continue
                tier = parts[0]
                try:
                    price = self._parse_money_int(parts[1])
                except Exception:
                    continue
                finished = True
                if len(parts) >= 3:
                    finished = parts[2] not in ("0", "false", "non", "no")
                effective = price if finished else int(round(price * 0.10))
                maps_cost += effective
                if finished:
                    finished_maps_count += 1
                map_rows.append((tier, price, finished, effective))

            coffre_net = int(round(coffre_raw * (1 - (tax_percent / 100.0))))
            total_net = coffre_net + bags_raw
            scout_min, scout_max = self._get_scout_limits(interaction.guild.id)
            mult = max(1, finished_maps_count)
            scout_min *= mult
            scout_max *= mult

            calc = self._compute_loot_split(
                total_net=total_net,
                rl_user_id=rl_user_id,
                scout_user_id=scout_user_id,
                players=players,
                rl_bonus_pct=rl_bonus_percent,
                scout_pct=scout_percent,
                scout_min=scout_min,
                scout_max=scout_max,
                maps_cost=maps_cost,
            )

            calc_payouts: Dict[int, int] = dict(calc["payouts"])
            if scout_user_id and calc["scout_paid"] > 0:
                calc_payouts[scout_user_id] = calc_payouts.get(scout_user_id, 0) + int(calc["scout_paid"])

            def m(uid: Optional[int]) -> str:
                return mention(uid) if uid else "*(non défini)*"

            lines = [
                "✅ **Processed 💸**",
                "Vérifiez les calculs puis validez avec le bouton.",
                f"**Raid**: `{raid.raid_id}`",
                f"**RL**: {m(rl_user_id)}",
                f"**Scout**: {m(scout_user_id)}",
                f"**Total Pot**: `{total_net:,}`",
                "",
                "📊 **Financial Summary**",
                f"Coffre brut: `{coffre_raw:,}`",
                f"Coffre net ({tax_percent:.1f}% tax): `{coffre_net:,}`",
                f"Silver bags: `{bags_raw:,}`",
                f"Total net: `{total_net:,}`",
                "",
                "👑 **RL / Scout**",
                f"RL bonus: `{rl_bonus_percent:.2f}%`",
                f"Scout part: `{scout_percent:.2f}%` clamp `{scout_min:,}`-`{scout_max:,}` => `{calc['scout_paid']:,}`",
                "",
                "🗺️ **Maps**",
                f"Total maps cost: `{maps_cost:,}`",
            ]
            for tier, price, finished, effective in map_rows[:20]:
                status = "Finish" if finished else "Cancel(-90%)"
                lines.append(f"• {tier}: `{price:,}` => `{effective:,}` ({status})")
            lines += [
                "",
                "👥 **Sharing**",
                f"Post-scout: `{calc['post_scout']:,}`",
                f"Post-maps: `{calc['post_maps']:,}`",
                f"Share normal: `{calc['share']:,}`",
                f"Joueurs split ({len(calc_payouts)}): " + " ".join(mention(uid) for uid in list(calc_payouts.keys())[:25]),
                "",
                "📋 **Payouts**",
            ]
            for uid, amt in list(calc_payouts.items())[:60]:
                lines.append(f"• {mention(uid)}: `+{amt:,}`")

            token = f"loot:{interaction.guild.id}:{interaction.channel.id}:{interaction.user.id}:{int(time.time())}"
            self._loot_sessions[token] = {"author_id": interaction.user.id, "summary": "\n".join(lines), "raid_id": raid.raid_id, "payouts": calc_payouts}

            class LootConfirmView(nextcord.ui.View):
                def __init__(self, mod: "RaidModule", tkn: str):
                    super().__init__(timeout=900)
                    self.mod = mod
                    self.tkn = tkn

                @nextcord.ui.button(label="✅ Procéder", style=nextcord.ButtonStyle.success)
                async def proceed(self, button: nextcord.ui.Button, inter: nextcord.Interaction):
                    data = self.mod._loot_sessions.get(self.tkn)
                    if not data:
                        return await inter.response.send_message("Session expirée.", ephemeral=True)
                    if not inter.guild or not isinstance(inter.user, nextcord.Member):
                        return await inter.response.send_message("Contexte serveur requis.", ephemeral=True)
                    if inter.user.id != data["author_id"] and not can_manage_raids(self.mod.cfg, inter.user):
                        return await inter.response.send_message("⛔ Non autorisé.", ephemeral=True)
                    for c in self.children:
                        c.disabled = True
                    await inter.message.edit(view=self)

                    raid_obj = self.mod.store.raids.get(data.get("raid_id", ""))
                    payouts = data.get("payouts", {})
                    if inter.guild and payouts:
                        async with self.mod.store.lock:
                            for uid, amt in payouts.items():
                                cur = self.mod.store.bank_get_balance(inter.guild.id, int(uid))
                                self.mod.store.bank_set_balance(inter.guild.id, int(uid), cur + int(amt))
                            self.mod.store.save()

                    if raid_obj:
                        await self.mod._cleanup_temp_role_after_split(raid_obj)

                    ping_targets = " ".join(mention(int(uid)) for uid in payouts.keys()) if payouts else ""
                    if ping_targets:
                        try:
                            await inter.channel.send(f"💰 Paiement split effectué pour: {ping_targets}")
                        except Exception:
                            pass

                    await inter.response.send_message("✅ Répartition validée et paiements appliqués.", ephemeral=True)

                @nextcord.ui.button(label="❌ Annuler", style=nextcord.ButtonStyle.danger)
                async def cancel(self, button: nextcord.ui.Button, inter: nextcord.Interaction):
                    data = self.mod._loot_sessions.get(self.tkn)
                    if not data:
                        return await inter.response.send_message("Session expirée.", ephemeral=True)
                    if not inter.guild or not isinstance(inter.user, nextcord.Member):
                        return await inter.response.send_message("Contexte serveur requis.", ephemeral=True)
                    if inter.user.id != data["author_id"] and not can_manage_raids(self.mod.cfg, inter.user):
                        return await inter.response.send_message("⛔ Non autorisé.", ephemeral=True)
                    for c in self.children:
                        c.disabled = True
                    await inter.message.edit(view=self)
                    await inter.response.send_message("❌ Répartition annulée.", ephemeral=True)

            await interaction.response.send_message("Résumé prêt, publié dans le thread.", ephemeral=True)
            summary_embed = nextcord.Embed(
                title="✅ Processed 💸",
                description=limit_str(self._loot_sessions[token]["summary"], 3900),
                color=nextcord.Color.green(),
            )
            await interaction.channel.send(embed=summary_embed, view=LootConfirmView(self, token))
