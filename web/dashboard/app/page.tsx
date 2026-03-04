'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  ApiOverviewDTO,
  BalanceEntryDTO,
  BankActionHistoryEntryDTO,
  BankActionType,
  BankBalanceDTO,
  DiscordDirectoryDTO,
  GuildPermissionBindingDTO,
  GuildPermissionKey,
  MeDTO,
  RaidDTO,
  RaidRosterDTO,
  RaidTemplateDTO,
  TicketTranscriptDTO,
  ApiError,
  TemplateMutationResultDTO,
  apiDelete,
  apiGet,
  apiGetSafe,
  apiPost,
  apiPut,
  setCsrfToken,
} from '../lib/api';

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type TabKey = 'active' | 'raids' | 'balances' | 'tickets';
type RaidSort = 'start_desc' | 'start_asc' | 'status';
type LoadState = {
  health: boolean;
  overview: ApiOverviewDTO | null;
  me: MeDTO | null;
  raids: RaidDTO[];
  templates: RaidTemplateDTO[];
  tickets: TicketTranscriptDTO[];
  balances: BalanceEntryDTO[];
  selectedTicket: TicketTranscriptDTO | null;
};

const initialState: LoadState = {
  health: false,
  overview: null,
  me: null,
  raids: [],
  templates: [],
  tickets: [],
  balances: [],
  selectedTicket: null,
};

const statusOrder: Record<string, number> = { OPEN: 0, PINGED: 1, CLOSED: 2 };
const DISCORD_PERM_ADMINISTRATOR = 1 << 3;
const permissionLabels: Record<GuildPermissionKey, string> = {
  raid_manager: 'raid_manager',
  bank_manager: 'bank_manager',
  ticket_manager: 'ticket_manager',
};
function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
}

function guildIconUrl(guild: { id: string; icon?: string | null }): string {
  if (!guild.icon) return '';
  return `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64`;
}

export default function HomePage() {
  const [state, setState] = useState<LoadState>(initialState);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selectedGuildId, setSelectedGuildId] = useState<string | null>(null);
  const [selectedTicketId, setSelectedTicketId] = useState('');
  const [selectedRaidId, setSelectedRaidId] = useState('');
  const [selectedRoster, setSelectedRoster] = useState<RaidRosterDTO | null>(null);
  const [signupRoleKey, setSignupRoleKey] = useState('');
  const [signupIp, setSignupIp] = useState('');
  const [activeTab, setActiveTab] = useState<TabKey>('active');
  const [showClosedRaids, setShowClosedRaids] = useState(false);
  const [showClosedTickets, setShowClosedTickets] = useState(false);
  const [raidSort, setRaidSort] = useState<RaidSort>('start_desc');

  const [raidTemplate, setRaidTemplate] = useState('');
  const [raidTitle, setRaidTitle] = useState('');
  const [raidDescription, setRaidDescription] = useState('');
  const [raidExtraMessage, setRaidExtraMessage] = useState('');
  const [raidStartAt, setRaidStartAt] = useState('');
  const [raidChannelId, setRaidChannelId] = useState('');
  const [raidVoiceChannelId, setRaidVoiceChannelId] = useState('');

  const [templateName, setTemplateName] = useState('');
  const [templateDescription, setTemplateDescription] = useState('');
  const [templateSpec, setTemplateSpec] = useState('Tank;2\nHealer;2\nDPS;8');
  const [templateContentType, setTemplateContentType] = useState<'ava_raid' | 'pvp' | 'pve'>('pvp');
  const [templateRequiredRoleIds, setTemplateRequiredRoleIds] = useState('');
  const [templateFeedback, setTemplateFeedback] = useState('');
  const [editingTemplate, setEditingTemplate] = useState('');
  const [editingRaidId, setEditingRaidId] = useState('');

  const [bankActionType, setBankActionType] = useState<BankActionType>('add_split');
  const [bankAmount, setBankAmount] = useState('0');
  const [bankTargetIds, setBankTargetIds] = useState<string[]>([]);
  const [bankTargetsManual, setBankTargetsManual] = useState('');
  const [selectedBalanceUserId, setSelectedBalanceUserId] = useState('');
  const [quickAmount, setQuickAmount] = useState('0');
  const [lookupUserId, setLookupUserId] = useState('');
  const [lookupBalance, setLookupBalance] = useState<BankBalanceDTO | null>(null);
  const [payTargetUserId, setPayTargetUserId] = useState('');
  const [payAmount, setPayAmount] = useState('0');
  const [payNote, setPayNote] = useState('');
  const [bankHistory, setBankHistory] = useState<BankActionHistoryEntryDTO[]>([]);

  const [discordDirectory, setDiscordDirectory] = useState<DiscordDirectoryDTO | null>(null);
  const [manualRaidChannelId, setManualRaidChannelId] = useState('');
  const [manualRaidVoiceChannelId, setManualRaidVoiceChannelId] = useState('');
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});


  const [permissionBindings, setPermissionBindings] = useState<GuildPermissionBindingDTO[]>([]);
  const [permissionRoleInputs, setPermissionRoleInputs] = useState<Record<string, string>>({});
  const [permissionUserInputs, setPermissionUserInputs] = useState<Record<string, string>>({});


  async function loadDashboard(guildId?: string | null) {
    setBusy(true);
    setError('');
    try {
      const [health, overview, me] = await Promise.all([
        apiGetSafe<{ ok: boolean }>('/health'),
        apiGetSafe<ApiOverviewDTO>('/api/public/overview'),
        apiGetSafe<MeDTO>('/me'),
      ]);
      if (me?.csrf_token) setCsrfToken(me.csrf_token);

      const activeGuild = guildId ?? me?.selected_guild_id ?? me?.guilds?.[0]?.id ?? null;
      let raids: RaidDTO[] = [];
      let templates: RaidTemplateDTO[] = [];
      let tickets: TicketTranscriptDTO[] = [];
      let balances: BalanceEntryDTO[] = [];
      let directory: DiscordDirectoryDTO | null = null;
      let history: BankActionHistoryEntryDTO[] = [];
      let permissions: GuildPermissionBindingDTO[] = [];

      if (activeGuild) {
        [raids, templates, tickets, balances, directory, history] = await Promise.all([
          apiGet<RaidDTO[]>('/api/my/raids'),
          apiGet<RaidTemplateDTO[]>('/api/raid-templates'),
          apiGet<TicketTranscriptDTO[]>(`/api/guilds/${activeGuild}/tickets`),
          apiGet<BalanceEntryDTO[]>(`/api/guilds/${activeGuild}/balances`),
          apiGet<DiscordDirectoryDTO>(`/api/guilds/${activeGuild}/discord-directory`),
          apiGet<BankActionHistoryEntryDTO[]>(`/api/guilds/${activeGuild}/bank/actions?limit=25`),
        ]);
        const activeGuildMeta = me?.guilds?.find((g) => g.id === activeGuild);
        const permissionBits = Number(activeGuildMeta?.permissions || '0');
        const isAdmin = Boolean(activeGuildMeta?.owner) || Boolean(permissionBits & DISCORD_PERM_ADMINISTRATOR);
        if (isAdmin) {
          permissions = await apiGet<GuildPermissionBindingDTO[]>(`/api/guilds/${activeGuild}/permissions`);
        }
      }

      setDiscordDirectory(directory);
      setPermissionBindings(permissions);
      setPermissionRoleInputs(Object.fromEntries(permissions.map((item) => [item.permission_key, item.role_ids.join(",")])));
      setPermissionUserInputs(Object.fromEntries(permissions.map((item) => [item.permission_key, item.user_ids.join(",")])));
      setState({ health: Boolean(health?.ok), overview, me, raids, templates, tickets, balances, selectedTicket: null });
      setBankHistory(history);
      setSelectedGuildId(activeGuild);
      setTemplateFeedback('');
      setSelectedTicketId((prev) => (tickets.some((t) => t.ticket_id === prev) ? prev : ''));
      setRaidTemplate((prev) => prev || templates[0]?.name || '');
      setEditingTemplate((prev) => prev || templates[0]?.name || '');
      setEditingRaidId((prev) => prev || raids[0]?.raid_id || '');
      setSelectedRaidId((prev) => prev || raids[0]?.raid_id || '');
      setSelectedBalanceUserId((prev) => prev || balances[0]?.user_id || '');
      setLookupUserId((prev) => prev || balances[0]?.user_id || me?.user.id || '');
      setPayTargetUserId((prev) => prev || balances[0]?.user_id || '');
      if (!raidChannelId && raids[0]?.channel_id) setRaidChannelId(raids[0].channel_id);
    } catch (err) {
      if (err instanceof ApiError) {
        const warnings = (err.details?.warnings as string[] | undefined) || [];
        const errors = (err.details?.errors as string[] | undefined) || [];
        const detailText = [...errors, ...warnings].join(' | ');
        setError(detailText ? `${err.message} — ${detailText}` : err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Erreur de chargement');
      }
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void loadDashboard(); }, []);

  useEffect(() => {
    if (!selectedGuildId || !selectedTicketId) {
      setState((prev) => ({ ...prev, selectedTicket: null }));
      return;
    }
    void apiGet<TicketTranscriptDTO>(`/api/guilds/${selectedGuildId}/tickets/${selectedTicketId}`)
      .then((ticket) => setState((prev) => ({ ...prev, selectedTicket: ticket })))
      .catch((err) => setError(err instanceof Error ? err.message : 'Lecture ticket impossible'));
  }, [selectedGuildId, selectedTicketId]);

  useEffect(() => {
    if (!selectedRaidId) {
      setSelectedRoster(null);
      return;
    }
    void apiGet<RaidRosterDTO>(`/api/raids/${selectedRaidId}/roster`)
      .then((roster) => {
        setSelectedRoster(roster);
        setSignupRoleKey((prev) => prev || roster.participants[0]?.role_key || '');
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Chargement roster impossible'));
  }, [selectedRaidId]);



  const canUseDashboard = Boolean(state.me?.guilds?.length);

  function setFieldError(key: string, message: string) {
    setFormErrors((prev) => ({ ...prev, [key]: message }));
  }

  function clearFieldError(key: string) {
    setFormErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  function readPositiveAmount(value: string): number | null {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return parsed;
  }

  function isValidFutureDate(value: string): boolean {
    const ts = new Date(value).getTime();
    return Number.isFinite(ts) && ts > Date.now();
  }

  useEffect(() => {
    const template = state.templates.find((tpl) => tpl.name === editingTemplate);
    if (!template) return;
    setTemplateDescription(template.description);
    setTemplateContentType(template.content_type);
    setTemplateRequiredRoleIds(template.raid_required_role_ids.join(','));
    setTemplateSpec(formatSpecFromTemplate(template));
  }, [editingTemplate, state.templates]);


  const visibleRaids = useMemo(() => {
    let raids = [...state.raids];
    if (!showClosedRaids) raids = raids.filter((r) => r.status !== 'CLOSED');
    if (raidSort === 'start_desc') raids.sort((a, b) => b.start_at - a.start_at);
    if (raidSort === 'start_asc') raids.sort((a, b) => a.start_at - b.start_at);
    if (raidSort === 'status') raids.sort((a, b) => (statusOrder[a.status] ?? 99) - (statusOrder[b.status] ?? 99) || b.start_at - a.start_at);
    return raids;
  }, [state.raids, showClosedRaids, raidSort]);

  const visibleTickets = useMemo(() => {
    const tickets = [...state.tickets].sort((a, b) => b.updated_at - a.updated_at);
    if (showClosedTickets) return tickets;
    return tickets.filter((t) => t.status === 'open');
  }, [state.tickets, showClosedTickets]);

  const memberNameById = useMemo(() => new Map((discordDirectory?.members || []).map((m) => [m.id, m.display_name])), [discordDirectory]);
  const textChannels = useMemo(() => (discordDirectory?.channels || []).filter((c) => c.type === 0), [discordDirectory]);
  const voiceChannels = useMemo(() => (discordDirectory?.channels || []).filter((c) => c.type === 2), [discordDirectory]);
  const memberIds = useMemo(() => new Set((discordDirectory?.members || []).map((m) => m.id)), [discordDirectory]);
  const channelIds = useMemo(() => new Set((discordDirectory?.channels || []).map((c) => c.id)), [discordDirectory]);

  function publishStatusLabel(raid: RaidDTO): string {
    if (raid.publish_status === 'delivered') return '✅ Publié sur Discord';
    if (raid.publish_status === 'failed') return '❌ Échec de publication';
    return '⏳ En attente de publication';
  }


  async function onSelectGuild(guildId: string) { await apiPost(`/me/select-guild/${guildId}`); await loadDashboard(guildId); }

  async function onOpenRaid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!selectedGuildId) nextErrors.openRaidGuild = 'Sélectionne un serveur avant de créer un raid.';
    if (!raidTemplate) nextErrors.openRaidTemplate = 'Le template est requis.';
    if (!raidTitle.trim()) nextErrors.openRaidTitle = 'Le titre est requis.';
    if (!raidStartAt) {
      nextErrors.openRaidStartAt = 'La date du raid est requise.';
    } else if (!isValidFutureDate(raidStartAt)) {
      nextErrors.openRaidStartAt = 'Date invalide ou passée. Choisis une date future.';
    }
    const effectiveRaidChannelId = manualRaidChannelId.trim() || raidChannelId;
    const effectiveRaidVoiceChannelId = manualRaidVoiceChannelId.trim() || raidVoiceChannelId;
    if (!effectiveRaidChannelId) nextErrors.openRaidChannel = 'Le salon texte est requis.';
    if (!channelIds.has(effectiveRaidChannelId)) {
      nextErrors.openRaidChannel = `ID de salon textuel invalide (absent du répertoire local): ${effectiveRaidChannelId}`;
    }
    if (effectiveRaidVoiceChannelId && !channelIds.has(effectiveRaidVoiceChannelId)) {
      nextErrors.openRaidVoiceChannel = `ID de salon vocal invalide (absent du répertoire local): ${effectiveRaidVoiceChannelId}`;
    }
    if (Object.keys(nextErrors).length) {
      setFormErrors((prev) => ({ ...prev, ...nextErrors }));
      return;
    }
    await apiPost('/api/actions/raids/open', {
      request_id: crypto.randomUUID(), guild_id: selectedGuildId, channel_id: effectiveRaidChannelId,
      voice_channel_id: effectiveRaidVoiceChannelId || null,
      template_name: raidTemplate, title: raidTitle, description: raidDescription, extra_message: raidExtraMessage,
      start_at: Math.floor(new Date(raidStartAt).getTime() / 1000), prep_minutes: 10, cleanup_minutes: 30,
    });
    await loadDashboard(selectedGuildId);
  }

  async function onUpdateRaid() {
    const nextErrors: Record<string, string> = {};
    if (!editingRaidId) nextErrors.updateRaidId = 'Sélectionne un raid à modifier.';
    if (!raidTitle.trim()) nextErrors.updateRaidTitle = 'Le titre est requis pour modifier un raid.';
    if (!raidStartAt) {
      nextErrors.updateRaidStartAt = 'La date du raid est requise.';
    } else if (!isValidFutureDate(raidStartAt)) {
      nextErrors.updateRaidStartAt = 'Date invalide ou passée. Choisis une date future.';
    }
    if (Object.keys(nextErrors).length) {
      setFormErrors((prev) => ({ ...prev, ...nextErrors }));
      return;
    }
    await apiPut(`/api/raids/${editingRaidId}`, {
      title: raidTitle, description: raidDescription, extra_message: raidExtraMessage,
      start_at: Math.floor(new Date(raidStartAt).getTime() / 1000), prep_minutes: 10, cleanup_minutes: 30,
    });
    await loadDashboard(selectedGuildId);
  }

  function parseRoleIds(raw: string): string[] {
    return raw
      .split(/[\s,]+/)
      .map((value) => value.trim())
      .filter((value) => /^([1-9]\d*)$/.test(value));
  }

  function formatSpecFromTemplate(template: RaidTemplateDTO): string {
    return template.roles
      .map((role) => {
        const options: string[] = [];
        options.push(`key=${role.key}`);
        if (role.ip_required) options.push('ip=true');
        if (role.required_role_ids.length) options.push(`req=${role.required_role_ids.join(',')}`);
        return [role.label, String(role.slots), ...options].join(';');
      })
      .join('\n');
  }

  function readTemplateWarnings(result: TemplateMutationResultDTO): string {
    return result.spec_warnings.length ? `Warnings spec: ${result.spec_warnings.join(' | ')}` : '';
  }

  async function onCreateTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedGuildId || !templateName) return;
    try {
      const result = await apiPost<TemplateMutationResultDTO>('/api/actions/comp-wizard', {
        request_id: crypto.randomUUID(), guild_id: selectedGuildId, name: templateName,
        description: templateDescription,
        content_type: templateContentType,
        spec: templateSpec,
        raid_required_role_ids: parseRoleIds(templateRequiredRoleIds),
      });
      setTemplateFeedback(readTemplateWarnings(result) || 'Template créé.');
      setTemplateName('');
      await loadDashboard(selectedGuildId);
    } catch (err) {
      if (err instanceof ApiError) {
        const warnings = (err.details?.warnings as string[] | undefined) || [];
        const errors = (err.details?.errors as string[] | undefined) || [];
        const details = [...errors, ...warnings].join(' | ');
        setTemplateFeedback(details ? `${err.message} — ${details}` : err.message);
        return;
      }
      setTemplateFeedback(err instanceof Error ? err.message : 'Erreur template');
    }
  }

  async function onUpdateTemplate() {
    if (!editingTemplate) return;
    try {
      const result = await apiPut<TemplateMutationResultDTO>(`/api/raid-templates/${editingTemplate}`, {
        description: templateDescription,
        content_type: templateContentType,
        spec: templateSpec,
        raid_required_role_ids: parseRoleIds(templateRequiredRoleIds),
      });
      setTemplateFeedback(readTemplateWarnings(result) || 'Template mis à jour.');
      await loadDashboard(selectedGuildId);
    } catch (err) {
      if (err instanceof ApiError) {
        const warnings = (err.details?.warnings as string[] | undefined) || [];
        const errors = (err.details?.errors as string[] | undefined) || [];
        const details = [...errors, ...warnings].join(' | ');
        setTemplateFeedback(details ? `${err.message} — ${details}` : err.message);
        return;
      }
      setTemplateFeedback(err instanceof Error ? err.message : 'Erreur template');
    }
  }


  async function onDeleteTemplate() {
    if (!editingTemplate) return;
    try {
      await apiDelete(`/api/raid-templates/${editingTemplate}`);
      setTemplateFeedback('Template supprimé.');
      await loadDashboard(selectedGuildId);
    } catch (err) {
      setTemplateFeedback(err instanceof Error ? err.message : 'Suppression impossible');
    }
  }

  async function onBankAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!selectedGuildId) nextErrors.bankGuild = 'Sélectionne un serveur pour utiliser la banque.';
    const amount = readPositiveAmount(bankAmount);
    if (!amount) nextErrors.bankAmount = 'Le montant doit être strictement supérieur à 0.';
    const manualTargets = bankTargetsManual.split(/[\s,]+/).map((id) => id.trim()).filter((id) => /^([1-9]\d*)$/.test(id));
    const target_user_ids = Array.from(new Set([...bankTargetIds, ...manualTargets]));
    if (!target_user_ids.length) nextErrors.bankTargets = 'Sélectionne au moins un utilisateur cible.';
    const unknownTargets = target_user_ids.filter((id) => !memberIds.has(id));
    if (unknownTargets.length) {
      nextErrors.bankTargets = `IDs utilisateur inconnus dans le répertoire local: ${unknownTargets.join(', ')}`;
    }
    if (Object.keys(nextErrors).length) {
      setFormErrors((prev) => ({ ...prev, ...nextErrors }));
      return;
    }
    await apiPost('/api/actions/bank/apply', {
      request_id: crypto.randomUUID(), guild_id: selectedGuildId, action_type: bankActionType,
      amount, target_user_ids, note: 'dashboard',
    });
    await loadDashboard(selectedGuildId);
  }


  async function onQuickBalanceAction(action: 'add' | 'remove') {
    const amount = readPositiveAmount(quickAmount);
    if (!selectedGuildId) {
      setFieldError('quickBalanceGuild', 'Sélectionne un serveur pour utiliser la banque.');
      return;
    }
    if (!selectedBalanceUserId) {
      setFieldError('quickBalanceUser', 'Sélectionne un membre cible.');
      return;
    }
    if (!amount) {
      setFieldError('quickBalanceAmount', 'Le montant doit être strictement supérieur à 0.');
      return;
    }
    await apiPost('/api/actions/bank/apply', {
      request_id: crypto.randomUUID(),
      guild_id: selectedGuildId,
      action_type: action,
      amount,
      target_user_ids: [selectedBalanceUserId],
      note: 'dashboard-quick',
    });
    await loadDashboard(selectedGuildId);
  }

  async function onLookupBalance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!selectedGuildId) nextErrors.lookupGuild = 'Sélectionne un serveur pour consulter une balance.';
    if (!lookupUserId) nextErrors.lookupUserId = 'Un user ID est requis.';
    if (!memberIds.has(lookupUserId)) {
      nextErrors.lookupUserId = `ID utilisateur invalide (absent du répertoire local): ${lookupUserId}`;
    }
    if (Object.keys(nextErrors).length) {
      setFormErrors((prev) => ({ ...prev, ...nextErrors }));
      return;
    }
    const balance = await apiGet<BankBalanceDTO>(`/api/guilds/${selectedGuildId}/balances/${lookupUserId}`);
    setLookupBalance(balance);
  }

  async function onPay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!selectedGuildId) nextErrors.payGuild = 'Sélectionne un serveur pour effectuer un transfert.';
    if (!payTargetUserId) nextErrors.payTarget = 'Le destinataire est requis.';
    const amount = readPositiveAmount(payAmount);
    if (!amount) nextErrors.payAmount = 'Le montant doit être strictement supérieur à 0.';
    if (Object.keys(nextErrors).length) {
      setFormErrors((prev) => ({ ...prev, ...nextErrors }));
      return;
    }
    await apiPost('/api/actions/bank/pay', {
      guild_id: selectedGuildId,
      to_user_id: payTargetUserId,
      amount,
      note: payNote,
    });
    setPayNote('');
    await loadDashboard(selectedGuildId);
  }

  async function onUndoBankAction() {
    if (!selectedGuildId) return;
    await apiPost('/api/actions/bank/undo', { guild_id: selectedGuildId });
    await loadDashboard(selectedGuildId);
  }

  async function onSignupRaid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!selectedRaidId) nextErrors.signupRaid = 'Sélectionne un raid avant de t’inscrire.';
    if (!signupRoleKey) nextErrors.signupRole = 'Le rôle est requis.';
    if (signupIp && (!/^\d+$/.test(signupIp) || Number(signupIp) <= 0)) {
      nextErrors.signupIp = 'IP invalide: saisir un entier strictement positif.';
    }
    if (Object.keys(nextErrors).length) {
      setFormErrors((prev) => ({ ...prev, ...nextErrors }));
      return;
    }
    const payload: Record<string, unknown> = { role_key: signupRoleKey };
    if (signupIp) payload.ip = Number(signupIp);
    const roster = await apiPost<RaidRosterDTO>(`/api/raids/${selectedRaidId}/signup`, payload);
    setSelectedRoster(roster);
    await loadDashboard(selectedGuildId);
  }

  async function onLeaveRaid() {
    if (!selectedRaidId) return;
    const roster = await apiPost<RaidRosterDTO>(`/api/raids/${selectedRaidId}/leave`);
    setSelectedRoster(roster);
    await loadDashboard(selectedGuildId);
  }

  async function onCloseRaid(raidId: string) {
    await apiPost(`/api/raids/${raidId}/state`, { action: 'close' });
    await loadDashboard(selectedGuildId);
  }

  function onPrepareRaidEdit(raid: RaidDTO) {
    setEditingRaidId(raid.raid_id);
    setRaidTitle(raid.title);
    setRaidDescription(raid.description);
    setRaidExtraMessage(raid.extra_message);
    setRaidStartAt(new Date(raid.start_at * 1000).toISOString().slice(0, 16));
    setActiveTab('active');
  }

  async function onDeleteTicket(ticketId: string) {
    if (!selectedGuildId) return;
    await apiDelete(`/api/guilds/${selectedGuildId}/tickets/${ticketId}`);
    await loadDashboard(selectedGuildId);
  }

  async function onLogout() {
    await apiPost('/auth/logout');
    setDiscordDirectory(null);
    setState(initialState);
  }

  const currentUserAvatar = state.me?.user.avatar ? `https://cdn.discordapp.com/avatars/${state.me.user.id}/${state.me.user.avatar}.png?size=64` : '';
  const canOpenRaid = Boolean(selectedGuildId && raidTemplate && raidTitle.trim() && raidStartAt && (manualRaidChannelId.trim() || raidChannelId));
  const canUpdateRaid = Boolean(editingRaidId && raidTitle.trim() && raidStartAt);
  const canApplyBankAction = Boolean(selectedGuildId && readPositiveAmount(bankAmount) && (bankTargetIds.length || bankTargetsManual.trim()));
  const canQuickAction = Boolean(selectedGuildId && selectedBalanceUserId && readPositiveAmount(quickAmount));
  const canLookupBalance = Boolean(selectedGuildId && lookupUserId.trim());
  const canPay = Boolean(selectedGuildId && payTargetUserId && readPositiveAmount(payAmount));
  const canSignupRaid = Boolean(selectedRaidId && signupRoleKey && (!signupIp || (/^\d+$/.test(signupIp) && Number(signupIp) > 0)));

  function parseDiscordIds(raw: string): string[] {
    return Array.from(new Set(raw.split(/[\s,]+/).map((value) => value.trim()).filter((value) => /^([1-9]\d*)$/.test(value))));
  }

  const selectedGuild = state.me?.guilds?.find((guild) => guild.id === selectedGuildId);
  const selectedGuildPermissionBits = Number(selectedGuild?.permissions || '0');
  const isSelectedGuildAdmin = Boolean(selectedGuild?.owner) || Boolean(selectedGuildPermissionBits & DISCORD_PERM_ADMINISTRATOR);

  async function onSavePermissionBinding(permissionKey: GuildPermissionKey) {
    if (!selectedGuildId) return;
    const role_ids = parseDiscordIds(permissionRoleInputs[permissionKey] || '');
    const user_ids = parseDiscordIds(permissionUserInputs[permissionKey] || '');
    const updated = await apiPut<GuildPermissionBindingDTO>(`/api/guilds/${selectedGuildId}/permissions/${permissionKey}`, { role_ids, user_ids });
    setPermissionBindings((prev) => prev.map((item) => (item.permission_key === permissionKey ? updated : item)));
    setPermissionRoleInputs((prev) => ({ ...prev, [permissionKey]: updated.role_ids.join(',') }));
    setPermissionUserInputs((prev) => ({ ...prev, [permissionKey]: updated.user_ids.join(',') }));
  }

  const raidPreview = useMemo(() => ({
    title: raidTitle.trim() || 'Titre du raid',
    template: raidTemplate || 'Template',
    startAt: raidStartAt ? new Date(raidStartAt).toLocaleString('fr-FR') : 'Date non définie',
    description: raidDescription.trim() || 'Pas de description',
    extra: raidExtraMessage.trim() || 'Aucun message additionnel',
  }), [raidTitle, raidTemplate, raidStartAt, raidDescription, raidExtraMessage]);

  if (!state.me) {
    return (
      <main className="discord-shell">
        <section className="main-panel" style={{ marginLeft: 0 }}>
          <header className="topbar">
            <div>
              <h1>AlbionBot Dashboard</h1>
              <p>Gestion centralisée des raids, tickets et balances Albion.</p>
            </div>
          </header>
          <section className="panel fade-in">
            <h2>Connecte-toi avec Discord</h2>
            <p>Accède au dashboard pour prévisualiser tes actions avant confirmation, piloter les raids et gérer les permissions du bot sur ton serveur.</p>
            <a className="discord-login" href={`${apiBase}/auth/discord/login`}>Se connecter avec Discord</a>
          </section>
        </section>
      </main>
    );
  }

  return (
    <main className="discord-shell">
      <aside className="guild-rail">
        {state.me?.guilds?.map((guild) => (
          <button
            key={guild.id}
            className={guild.id === selectedGuildId ? 'guild-btn active pop' : 'guild-btn pop'}
            onClick={() => void onSelectGuild(guild.id)}
            type="button"
            title={guild.name}
            aria-label={`Sélectionner le serveur ${guild.name}`}
            aria-pressed={guild.id === selectedGuildId}
          >
            {guildIconUrl(guild) ? <img src={guildIconUrl(guild)} alt={guild.name} className="avatar" /> : guild.name.slice(0, 2).toUpperCase()}
          </button>
        ))}
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div>
            <h1>AlbionBot Dashboard</h1>
            <p>{state.health ? 'API en ligne' : 'API indisponible'} · {selectedGuildId ? `Serveur ${selectedGuildId}` : 'Aucun serveur'}</p>
          </div>
          <div className="session-actions">
            {currentUserAvatar && <img src={currentUserAvatar} alt="avatar" className="avatar user-avatar" />}
            <span>{state.me?.user.global_name || state.me?.user.username}</span>
            {state.me && <button type="button" onClick={() => void onLogout()}>Déconnexion</button>}
          </div>
        </header>

        {error && <p className="error-banner">{error}</p>}
        <p className="info-banner">
          Les actions du dashboard pilotent le bot Discord: chaque changement demandé ici est synchronisé et exécuté côté bot.
        </p>

        <div className="tabs">
          <button type="button" className={activeTab === 'active' ? 'tab active' : 'tab'} onClick={() => setActiveTab('active')}>Dashboard</button>
          <button type="button" className={activeTab === 'raids' ? 'tab active' : 'tab'} onClick={() => setActiveTab('raids')}>Tous les raids</button>
          <button type="button" className={activeTab === 'balances' ? 'tab active' : 'tab'} onClick={() => setActiveTab('balances')}>Balances & Lootsplit</button>
          <button type="button" className={activeTab === 'tickets' ? 'tab active' : 'tab'} onClick={() => setActiveTab('tickets')}>Tous les tickets</button>
        </div>

        {canUseDashboard && activeTab === 'active' && (
          <div className="workspace-grid fade-in">
            <section className="status-grid">
              <article><h3>Guilds</h3><strong>{state.overview?.guild_count ?? 0}</strong></article>
              <article><h3>Tickets</h3><strong>{state.overview?.ticket_count ?? 0}</strong></article>
              <article><h3>Raids</h3><strong>{state.overview?.raid_count ?? 0}</strong></article>
              <article><h3>Templates</h3><strong>{state.overview?.template_count ?? 0}</strong></article>
            </section>

            {isSelectedGuildAdmin && (
              <section className="panel fade-in">
                <h2>Permissions bot (admin)</h2>
                <p>Définis les rôles et membres autorisés pour chaque permission manager.</p>
                <div className="form-grid">
                  {permissionBindings.map((binding) => (
                    <article key={binding.permission_key} className="preview-box">
                      <h3>{permissionLabels[binding.permission_key]}</h3>
                      <label>Rôles (IDs séparés par virgule/espace)
                        <input
                          value={permissionRoleInputs[binding.permission_key] || ''}
                          onChange={(e) => setPermissionRoleInputs((prev) => ({ ...prev, [binding.permission_key]: e.target.value }))}
                        />
                      </label>
                      <label>Membres (IDs séparés par virgule/espace)
                        <input
                          value={permissionUserInputs[binding.permission_key] || ''}
                          onChange={(e) => setPermissionUserInputs((prev) => ({ ...prev, [binding.permission_key]: e.target.value }))}
                        />
                      </label>
                      <button type="button" onClick={() => void onSavePermissionBinding(binding.permission_key)}>Enregistrer</button>
                    </article>
                  ))}
                </div>
              </section>
            )}

            <section className="panel split">
              <div>
                <h2>Raid opener</h2>
                <form onSubmit={onOpenRaid} className="form-grid">
                  <label>Template<select value={raidTemplate} onChange={(e) => { setRaidTemplate(e.target.value); clearFieldError('openRaidTemplate'); }} required>{state.templates.map((tpl) => <option key={tpl.name} value={tpl.name}>{tpl.name}</option>)}</select></label>
                  {formErrors.openRaidTemplate && <small className="error-banner">{formErrors.openRaidTemplate}</small>}
                  <label>Titre<input value={raidTitle} onChange={(e) => { setRaidTitle(e.target.value); clearFieldError('openRaidTitle'); }} required /></label>
                  {formErrors.openRaidTitle && <small className="error-banner">{formErrors.openRaidTitle}</small>}
                  <label>Description<input value={raidDescription} onChange={(e) => setRaidDescription(e.target.value)} /></label>
                  <label>Message additionnel<input value={raidExtraMessage} onChange={(e) => setRaidExtraMessage(e.target.value)} /></label>
                  <label>Date / heure<input type="datetime-local" value={raidStartAt} onChange={(e) => { setRaidStartAt(e.target.value); clearFieldError('openRaidStartAt'); }} required /></label>
                  {formErrors.openRaidStartAt && <small className="error-banner">{formErrors.openRaidStartAt}</small>}
                  <label>Salon texte
                    <select value={raidChannelId} onChange={(e) => { setRaidChannelId(e.target.value); clearFieldError('openRaidChannel'); }} required>
                      <option value="">Sélectionner un salon texte</option>
                      {textChannels.map((c) => <option key={c.id} value={c.id}>#{c.name} ({c.id})</option>)}
                    </select>
                  </label>
                  {formErrors.openRaidChannel && <small className="error-banner">{formErrors.openRaidChannel}</small>}
                  <label>Salon vocal
                    <select value={raidVoiceChannelId} onChange={(e) => { setRaidVoiceChannelId(e.target.value); clearFieldError('openRaidVoiceChannel'); }}>
                      <option value="">Aucun</option>
                      {voiceChannels.map((c) => <option key={c.id} value={c.id}>#{c.name} ({c.id})</option>)}
                    </select>
                  </label>
                  {formErrors.openRaidVoiceChannel && <small className="error-banner">{formErrors.openRaidVoiceChannel}</small>}
                  <details>
                    <summary>Mode ID manuel (dépannage)</summary>
                    <label>ID salon texte manuel
                      <input value={manualRaidChannelId} onChange={(e) => { setManualRaidChannelId(e.target.value); clearFieldError('openRaidChannel'); }} inputMode="numeric" />
                    </label>
                    <label>ID salon vocal manuel
                      <input value={manualRaidVoiceChannelId} onChange={(e) => { setManualRaidVoiceChannelId(e.target.value); clearFieldError('openRaidVoiceChannel'); }} inputMode="numeric" />
                    </label>
                  </details>
                  <article className="preview-box">
                    <strong>Prévisualisation Discord</strong>
                    <p><strong>{raidPreview.title}</strong></p>
                    <p>Template: {raidPreview.template}</p>
                    <p>Départ: {raidPreview.startAt}</p>
                    <p>{raidPreview.description}</p>
                    <p>{raidPreview.extra}</p>
                  </article>
                  <button type="submit" disabled={!canOpenRaid}>Ouvrir le raid</button>
                </form>
                <label>Raid à modifier<select value={editingRaidId} onChange={(e) => setEditingRaidId(e.target.value)}>{state.raids.map((raid) => <option key={raid.raid_id} value={raid.raid_id}>{raid.title}</option>)}</select></label>
                {formErrors.updateRaidTitle && <small className="error-banner">{formErrors.updateRaidTitle}</small>}
                {formErrors.updateRaidStartAt && <small className="error-banner">{formErrors.updateRaidStartAt}</small>}
                <button type="button" onClick={() => void onUpdateRaid()} disabled={!canUpdateRaid}>Modifier le raid</button>
              </div>
            </section>

            <section className="panel split">
              <div>
                <h2>Templates</h2>
                <form onSubmit={onCreateTemplate} className="form-grid">
                  <label>Nom<input value={templateName} onChange={(e) => setTemplateName(e.target.value)} /></label>
                  <label>Description<input value={templateDescription} onChange={(e) => setTemplateDescription(e.target.value)} /></label>
                  <label>Content type
                    <select value={templateContentType} onChange={(e) => setTemplateContentType(e.target.value as 'ava_raid' | 'pvp' | 'pve')}>
                      <option value="pvp">pvp</option>
                      <option value="pve">pve</option>
                      <option value="ava_raid">ava_raid</option>
                    </select>
                  </label>
                  <label>Roles requis raid (IDs, séparés par virgule/espace)<input value={templateRequiredRoleIds} onChange={(e) => setTemplateRequiredRoleIds(e.target.value)} /></label>
                  <label>Spec<textarea rows={8} value={templateSpec} onChange={(e) => setTemplateSpec(e.target.value)} /></label>
                  <button type="submit">Créer template</button>
                </form>
                <label>Template à modifier<select value={editingTemplate} onChange={(e) => setEditingTemplate(e.target.value)}>{state.templates.map((tpl) => <option key={tpl.name} value={tpl.name}>{tpl.name}</option>)}</select></label>
                <div className="inline-actions">
                  <button type="button" onClick={() => void onUpdateTemplate()}>Modifier template</button>
                  <button type="button" onClick={() => void onDeleteTemplate()}>Supprimer template</button>
                </div>
                {templateFeedback ? <p>{templateFeedback}</p> : null}
              </div>
              <div>
                <h3>Format spec complet</h3>
                <p>Chaque ligne: <code>Label;slots;options</code>. Options supportées: <code>key=...</code>, <code>ip=true|false</code>, <code>req=roleId1,roleId2</code>.</p>
                <pre className="preview-box">{`Tank;2;key=tank
Healer;2;ip=true
DPS Melee;4;req=123456789012345678
Support;2;ip=false;roles=234567890123456789,345678901234567890`}</pre>
              </div>
            </section>
          </div>
        )}

        {canUseDashboard && activeTab === 'balances' && (
          <section className="panel fade-in">
            <h2>Banque</h2>
            <div className="split">
              <div>
                <h3>Leaderboard</h3>
                <ul>{state.balances.slice(0, 30).map((b, index) => (
                  <li key={b.user_id} className="raid-item">
                    <span>#{b.rank || index + 1} · {memberNameById.get(b.user_id) || b.user_id}</span>
                    <small>{b.balance.toLocaleString('fr-FR')}</small>
                  </li>
                ))}</ul>
                <div className="inline-actions">
                  <button type="button" onClick={() => void onUndoBankAction()}>/bank_undo</button>
                </div>
                <div className="form-grid">
                  <label>Membre
                    <select value={selectedBalanceUserId} onChange={(e) => setSelectedBalanceUserId(e.target.value)}>
                      {(discordDirectory?.members || []).map((m) => <option key={m.id} value={m.id}>{m.display_name} ({m.id})</option>)}
                    </select>
                  </label>
                  <label>Montant
                    <input type="number" min={1} step="1" inputMode="numeric" required value={quickAmount} onChange={(e) => { setQuickAmount(e.target.value); clearFieldError('quickBalanceAmount'); }} />
                  </label>
                  {formErrors.quickBalanceAmount && <small className="error-banner">{formErrors.quickBalanceAmount}</small>}
                  <div className="inline-actions">
                    <button type="button" onClick={() => void onQuickBalanceAction('add')} disabled={!canQuickAction}>/bank_add</button>
                    <button type="button" onClick={() => void onQuickBalanceAction('remove')} disabled={!canQuickAction}>/bank_remove</button>
                  </div>
                </div>
                <form className="form-grid" onSubmit={onBankAction}>
                  <label>Type<select value={bankActionType} onChange={(e) => setBankActionType(e.target.value as BankActionType)}><option value="add_split">/bank_add_split</option><option value="remove_split">/bank_remove_split</option><option value="add">/bank_add</option><option value="remove">/bank_remove</option></select></label>
                  <label>Montant<input type="number" min={1} step="1" inputMode="numeric" required value={bankAmount} onChange={(e) => { setBankAmount(e.target.value); clearFieldError('bankAmount'); }} /></label>
                  {formErrors.bankAmount && <small className="error-banner">{formErrors.bankAmount}</small>}
                  <label>Utilisateurs cibles
                    <select multiple size={6} value={bankTargetIds} onChange={(e) => { setBankTargetIds(Array.from(e.target.selectedOptions, (option) => option.value)); clearFieldError('bankTargets'); }} required>
                      {(discordDirectory?.members || []).map((m) => <option key={m.id} value={m.id}>{m.display_name} ({m.id})</option>)}
                    </select>
                  </label>
                  {formErrors.bankTargets && <small className="error-banner">{formErrors.bankTargets}</small>}
                  <details>
                    <summary>Mode ID manuel (dépannage)</summary>
                    <label>User IDs manuels
                      <input value={bankTargetsManual} onChange={(e) => { setBankTargetsManual(e.target.value); clearFieldError('bankTargets'); }} placeholder="id1,id2,id3" inputMode="numeric" />
                    </label>
                  </details>
                  <button type="submit" disabled={!canApplyBankAction}>Appliquer action manager</button>
                </form>
              </div>
              <div>
                <h3>Consultation ciblée & transfert</h3>
                <form className="form-grid" onSubmit={onLookupBalance}>
                  <label>User ID
                    <input list="member-ids" value={lookupUserId} onChange={(e) => { setLookupUserId(e.target.value); clearFieldError('lookupUserId'); }} inputMode="numeric" required />
                  </label>
                  {formErrors.lookupUserId && <small className="error-banner">{formErrors.lookupUserId}</small>}
                  <datalist id="member-ids">{(discordDirectory?.members || []).map((m) => <option key={m.id} value={m.id} label={`${m.display_name} (${m.id})`} />)}</datalist>
                  <button type="submit" disabled={!canLookupBalance}>/bal</button>
                </form>
                {lookupBalance && <p>Balance: <strong>{lookupBalance.balance.toLocaleString('fr-FR')}</strong></p>}
                <form className="form-grid" onSubmit={onPay}>
                  <label>Destinataire
                    <select value={payTargetUserId} onChange={(e) => { setPayTargetUserId(e.target.value); clearFieldError('payTarget'); }} required>
                      {(discordDirectory?.members || []).map((m) => <option key={m.id} value={m.id}>{m.display_name} ({m.id})</option>)}
                    </select>
                  </label>
                  {formErrors.payTarget && <small className="error-banner">{formErrors.payTarget}</small>}
                  <label>Montant<input type="number" min={1} step="1" inputMode="numeric" required value={payAmount} onChange={(e) => { setPayAmount(e.target.value); clearFieldError('payAmount'); }} /></label>
                  {formErrors.payAmount && <small className="error-banner">{formErrors.payAmount}</small>}
                  <label>Note<input value={payNote} onChange={(e) => setPayNote(e.target.value)} /></label>
                  <button type="submit" disabled={!canPay}>/pay</button>
                </form>
                <h4>Historique actions manager</h4>
                <ul>{bankHistory.map((action) => (
                  <li key={action.action_id} className="raid-item">
                    <span>{action.action_type} · {fmtDate(action.created_at)}</span>
                    <small>Δ {action.total_delta.toLocaleString('fr-FR')} · {action.impacted_users} cible(s){action.undone ? ' · undo' : ''}</small>
                  </li>
                ))}</ul>
              </div>
            </div>
          </section>
        )}

        {canUseDashboard && activeTab === 'raids' && (
          <section className="panel fade-in">
            <h2>Raids</h2>
            <div className="inline-filters">
              <label>Trier<select value={raidSort} onChange={(e) => setRaidSort(e.target.value as RaidSort)}><option value="start_desc">Date ↓</option><option value="start_asc">Date ↑</option><option value="status">Statut</option></select></label>
              <label className="check"><input type="checkbox" checked={showClosedRaids} onChange={(e) => setShowClosedRaids(e.target.checked)} />Afficher raids clos</label>
            </div>
            <ul>
              {visibleRaids.map((raid) => (
                <li key={raid.raid_id} className="raid-item">
                  <button type="button" className={selectedRaidId === raid.raid_id ? 'row active' : 'row'} onClick={() => setSelectedRaidId(raid.raid_id)}>
                    <span>{raid.title}</span>
                    <small>{raid.status} · {fmtDate(raid.start_at)}</small>
                  </button>
                  <small>Template: {raid.template_name}</small>
                  <small>{publishStatusLabel(raid)}</small>
                  {raid.publish_status === 'failed' && (
                    <small>⚠️ La publication Discord a échoué{raid.publish_error ? `: ${raid.publish_error}` : '.'}</small>
                  )}
                  <div className="inline-actions">
                    <button type="button" onClick={() => onPrepareRaidEdit(raid)}>Éditer</button>
                    <button type="button" onClick={() => setSelectedRaidId(raid.raid_id)}>Gérer roster</button>
                    <button type="button" onClick={() => void onCloseRaid(raid.raid_id)} disabled={raid.status === 'CLOSED'}>Fermer raid</button>
                  </div>
                </li>
              ))}
            </ul>
            {selectedRoster && (
              <div className="panel roster-panel">
                <h3>Inscriptions en ligne</h3>
                <form className="form-grid" onSubmit={onSignupRaid}>
                  <label>Rôle
                    <select value={signupRoleKey} onChange={(e) => { setSignupRoleKey(e.target.value); clearFieldError('signupRole'); }} required>
                      {(state.templates.find((t) => t.name === selectedRoster.raid.template_name)?.roles || []).map((r) => (
                        <option key={r.key} value={r.key}>{r.label} ({r.slots})</option>
                      ))}
                    </select>
                  </label>
                  {formErrors.signupRole && <small className="error-banner">{formErrors.signupRole}</small>}
                  <label>IP (si requis)
                    <input type="number" min={1} step="1" inputMode="numeric" value={signupIp} onChange={(e) => { setSignupIp(e.target.value); clearFieldError('signupIp'); }} placeholder="1200" />
                  </label>
                  {formErrors.signupIp && <small className="error-banner">{formErrors.signupIp}</small>}
                  <div className="inline-actions">
                    <button type="submit" disabled={!canSignupRaid}>M'inscrire / Modifier</button>
                    <button type="button" onClick={() => void onLeaveRaid()}>Quitter le raid</button>
                  </div>
                </form>
                <ul>
                  {selectedRoster.participants.map((p) => (
                    <li key={`${p.user_id}-${p.joined_at}`} className="raid-item">
                      <span>{p.user_id}</span>
                      <small>{p.role_key} · {p.status}{p.ip ? ` · IP ${p.ip}` : ''}</small>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        {canUseDashboard && activeTab === 'tickets' && (
          <section className="panel fade-in">
            <h2>Tickets</h2>
            <div className="inline-filters"><label className="check"><input type="checkbox" checked={showClosedTickets} onChange={(e) => setShowClosedTickets(e.target.checked)} />Afficher fermés/supprimés</label></div>
            <div className="ticket-columns">
              <ul>
                {visibleTickets.map((ticket) => (
                  <li key={ticket.ticket_id}>
                    <button type="button" className={selectedTicketId === ticket.ticket_id ? 'row active' : 'row'} onClick={() => setSelectedTicketId(ticket.ticket_id)}>
                      <span>#{ticket.ticket_id}</span>
                      <small>{ticket.status} · {fmtDate(ticket.updated_at)}</small>
                    </button><button type="button" onClick={() => void onDeleteTicket(ticket.ticket_id)}>Supprimer log</button>
                  </li>
                ))}
              </ul>
              <div className="transcript-viewer">
                {!state.selectedTicket ? <p>Sélectionne un ticket.</p> : state.selectedTicket.messages.map((message) => (
                  <article key={`${message.message_id}-${message.created_at}`} className="message-row">
                    <div className="msg-head">
                      {message.author_avatar_url ? <img src={message.author_avatar_url} alt={message.author_name || 'avatar'} className="avatar msg-avatar" /> : <div className="avatar msg-avatar placeholder" />}
                      <strong>{message.author_name || `Utilisateur ${message.author_id}`}</strong>
                    </div>
                    <p>{message.content}</p>
                    {message.attachments?.length > 0 && <small>📎 {message.attachments.length} pièce(s) jointe(s)</small>}
                    <small>{fmtDate(message.created_at)} · {message.event_type}</small>
                  </article>
                ))}
              </div>
            </div>
          </section>
        )}

        {busy && <p className="muted">Synchronisation en cours…</p>}
      </section>
    </main>
  );
}
