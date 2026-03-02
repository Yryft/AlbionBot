'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  ApiOverviewDTO,
  BalanceEntryDTO,
  BankActionType,
  MeDTO,
  RaidDTO,
  RaidRosterDTO,
  RaidTemplateDTO,
  TicketTranscriptDTO,
  apiGet,
  apiGetSafe,
  apiPost,
  apiPut,
  setCsrfToken,
} from '../lib/api';

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type TabKey = 'active' | 'raids' | 'tickets';
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
  const [editingTemplate, setEditingTemplate] = useState('');
  const [editingRaidId, setEditingRaidId] = useState('');
  const [bankActionType, setBankActionType] = useState<BankActionType>('add_split');
  const [bankAmount, setBankAmount] = useState('0');
  const [bankTargets, setBankTargets] = useState('');

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

      if (activeGuild) {
        [raids, templates, tickets, balances] = await Promise.all([
          apiGet<RaidDTO[]>('/api/my/raids'),
          apiGet<RaidTemplateDTO[]>('/api/raid-templates'),
          apiGet<TicketTranscriptDTO[]>(`/api/guilds/${activeGuild}/tickets`),
          apiGet<BalanceEntryDTO[]>(`/api/guilds/${activeGuild}/balances`),
        ]);
      }

      setState({ health: Boolean(health?.ok), overview, me, raids, templates, tickets, balances, selectedTicket: null });
      setSelectedGuildId(activeGuild);
      setSelectedTicketId((prev) => (tickets.some((t) => t.ticket_id === prev) ? prev : ''));
      setRaidTemplate((prev) => prev || templates[0]?.name || '');
      setEditingTemplate((prev) => prev || templates[0]?.name || '');
      setEditingRaidId((prev) => prev || raids[0]?.raid_id || '');
      setSelectedRaidId((prev) => prev || raids[0]?.raid_id || '');
      if (!raidChannelId && raids[0]?.channel_id) setRaidChannelId(String(raids[0].channel_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de chargement');
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

  async function onSelectGuild(guildId: string) { await apiPost(`/me/select-guild/${guildId}`); await loadDashboard(guildId); }

  async function onOpenRaid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedGuildId || !raidTemplate || !raidStartAt || !raidTitle || !raidChannelId) return;
    await apiPost('/api/actions/raids/open', {
      request_id: crypto.randomUUID(), guild_id: selectedGuildId, channel_id: Number(raidChannelId),
      voice_channel_id: raidVoiceChannelId ? Number(raidVoiceChannelId) : null,
      template_name: raidTemplate, title: raidTitle, description: raidDescription, extra_message: raidExtraMessage,
      start_at: Math.floor(new Date(raidStartAt).getTime() / 1000), prep_minutes: 10, cleanup_minutes: 30,
    });
    await loadDashboard(selectedGuildId);
  }

  async function onUpdateRaid() {
    if (!editingRaidId || !raidTitle || !raidStartAt) return;
    await apiPut(`/api/raids/${editingRaidId}`, {
      title: raidTitle, description: raidDescription, extra_message: raidExtraMessage,
      start_at: Math.floor(new Date(raidStartAt).getTime() / 1000), prep_minutes: 10, cleanup_minutes: 30,
    });
    await loadDashboard(selectedGuildId);
  }

  async function onCreateTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedGuildId || !templateName) return;
    await apiPost('/api/actions/comp-wizard', {
      request_id: crypto.randomUUID(), guild_id: selectedGuildId, name: templateName,
      description: templateDescription, content_type: 'pvp', spec: templateSpec, raid_required_role_ids: [],
    });
    setTemplateName('');
    await loadDashboard(selectedGuildId);
  }

  async function onUpdateTemplate() {
    if (!editingTemplate) return;
    await apiPut(`/api/raid-templates/${editingTemplate}`, {
      description: templateDescription, content_type: 'pvp', spec: templateSpec, raid_required_role_ids: [],
    });
    await loadDashboard(selectedGuildId);
  }

  async function onBankAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedGuildId) return;
    const target_user_ids = bankTargets.split(/[\s,]+/).map((id) => Number(id)).filter((v) => Number.isFinite(v) && v > 0);
    await apiPost('/api/actions/bank/apply', {
      request_id: crypto.randomUUID(), guild_id: selectedGuildId, action_type: bankActionType,
      amount: Number(bankAmount), target_user_ids, note: 'dashboard',
    });
    await loadDashboard(selectedGuildId);
  }


  async function onSignupRaid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRaidId || !signupRoleKey) return;
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

  const currentUserAvatar = state.me?.user.avatar ? `https://cdn.discordapp.com/avatars/${state.me.user.id}/${state.me.user.avatar}.png?size=64` : '';

  return (
    <main className="discord-shell">
      <aside className="guild-rail">
        {state.me?.guilds?.map((guild) => (
          <button key={guild.id} className={guild.id === selectedGuildId ? 'guild-btn active pop' : 'guild-btn pop'} onClick={() => void onSelectGuild(guild.id)} type="button" title={guild.name}>
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
          </div>
        </header>

        {error && <p className="error-banner">{error}</p>}

        <div className="tabs">
          <button type="button" className={activeTab === 'active' ? 'tab active' : 'tab'} onClick={() => setActiveTab('active')}>Dashboard</button>
          <button type="button" className={activeTab === 'raids' ? 'tab active' : 'tab'} onClick={() => setActiveTab('raids')}>Tous les raids</button>
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

            <section className="panel split">
              <div>
                <h2>Ouvrir / modifier raid</h2>
                <form onSubmit={onOpenRaid} className="form-grid">
                  <label>Template<select value={raidTemplate} onChange={(e) => setRaidTemplate(e.target.value)}>{state.templates.map((tpl) => <option key={tpl.name} value={tpl.name}>{tpl.name}</option>)}</select></label>
                  <label>Titre<input value={raidTitle} onChange={(e) => setRaidTitle(e.target.value)} /></label>
                  <label>Description<input value={raidDescription} onChange={(e) => setRaidDescription(e.target.value)} /></label>
                  <label>Message additionnel<input value={raidExtraMessage} onChange={(e) => setRaidExtraMessage(e.target.value)} /></label>
                  <label>Date / heure<input type="datetime-local" value={raidStartAt} onChange={(e) => setRaidStartAt(e.target.value)} /></label>
                  <label>Channel text ID (obligatoire)<input value={raidChannelId} onChange={(e) => setRaidChannelId(e.target.value)} placeholder="1234567890" /></label>
                  <label>Voice channel ID (optionnel)<input value={raidVoiceChannelId} onChange={(e) => setRaidVoiceChannelId(e.target.value)} placeholder="1234567890" /></label>
                  <button type="submit">Ouvrir le raid</button>
                </form>
                <label>Raid à modifier<select value={editingRaidId} onChange={(e) => setEditingRaidId(e.target.value)}>{state.raids.map((raid) => <option key={raid.raid_id} value={raid.raid_id}>{raid.title}</option>)}</select></label>
                <button type="button" onClick={() => void onUpdateRaid()}>Modifier le raid</button>
              </div>
              <div>
                <h2>Balances / lootsplit</h2>
                <ul>{state.balances.slice(0, 12).map((b) => <li key={b.user_id} className="raid-item"><span>{b.user_id}</span><small>{b.balance.toLocaleString('fr-FR')}</small></li>)}</ul>
                <form className="form-grid" onSubmit={onBankAction}>
                  <label>Type<select value={bankActionType} onChange={(e) => setBankActionType(e.target.value as BankActionType)}><option value="add_split">Loot split +</option><option value="remove_split">Loot split -</option><option value="add">Add</option><option value="remove">Remove</option></select></label>
                  <label>Montant<input type="number" min={0} value={bankAmount} onChange={(e) => setBankAmount(e.target.value)} /></label>
                  <label>User IDs<input value={bankTargets} onChange={(e) => setBankTargets(e.target.value)} /></label>
                  <button type="submit">Appliquer</button>
                </form>
              </div>
            </section>

            <section className="panel">
              <h2>Templates</h2>
              <form onSubmit={onCreateTemplate} className="form-grid">
                <label>Nom<input value={templateName} onChange={(e) => setTemplateName(e.target.value)} /></label>
                <label>Description<input value={templateDescription} onChange={(e) => setTemplateDescription(e.target.value)} /></label>
                <label>Spec<textarea rows={6} value={templateSpec} onChange={(e) => setTemplateSpec(e.target.value)} /></label>
                <button type="submit">Créer template</button>
              </form>
              <label>Template à modifier<select value={editingTemplate} onChange={(e) => setEditingTemplate(e.target.value)}>{state.templates.map((tpl) => <option key={tpl.name} value={tpl.name}>{tpl.name}</option>)}</select></label>
              <button type="button" onClick={() => void onUpdateTemplate()}>Modifier template</button>
            </section>
          </div>
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
                  <small>{raid.message_id ? '✅ Publié sur Discord' : '⏳ En attente de publication'}</small>
                </li>
              ))}
            </ul>
            {selectedRoster && (
              <div className="panel roster-panel">
                <h3>Inscriptions en ligne</h3>
                <form className="form-grid" onSubmit={onSignupRaid}>
                  <label>Rôle
                    <select value={signupRoleKey} onChange={(e) => setSignupRoleKey(e.target.value)}>
                      {(state.templates.find((t) => t.name === selectedRoster.raid.template_name)?.roles || []).map((r) => (
                        <option key={r.key} value={r.key}>{r.label} ({r.slots})</option>
                      ))}
                    </select>
                  </label>
                  <label>IP (si requis)
                    <input value={signupIp} onChange={(e) => setSignupIp(e.target.value)} placeholder="1200" />
                  </label>
                  <div className="inline-actions">
                    <button type="submit">M'inscrire / Modifier</button>
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
                    </button>
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
        {!state.me && <a className="discord-login" href={`${apiBase}/auth/discord/login`}>Se connecter avec Discord</a>}
      </section>
    </main>
  );
}
