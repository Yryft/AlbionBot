'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  ApiOverviewDTO,
  MeDTO,
  RaidDTO,
  RaidTemplateDTO,
  TicketTranscriptDTO,
  apiGet,
  apiGetSafe,
  apiPost,
} from '../lib/api';

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

type LoadState = {
  health: boolean;
  overview: ApiOverviewDTO | null;
  me: MeDTO | null;
  raids: RaidDTO[];
  templates: RaidTemplateDTO[];
  tickets: TicketTranscriptDTO[];
  selectedTicket: TicketTranscriptDTO | null;
};

const initialState: LoadState = {
  health: false,
  overview: null,
  me: null,
  raids: [],
  templates: [],
  tickets: [],
  selectedTicket: null,
};

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
}

export default function HomePage() {
  const [state, setState] = useState<LoadState>(initialState);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>('');
  const [selectedGuildId, setSelectedGuildId] = useState<number | null>(null);
  const [selectedTicketId, setSelectedTicketId] = useState<string>('');
  const [raidTitle, setRaidTitle] = useState('');
  const [raidTemplate, setRaidTemplate] = useState('');
  const [raidStartAt, setRaidStartAt] = useState('');

  async function loadDashboard(guildId?: number | null) {
    setBusy(true);
    setError('');
    try {
      const [health, overview, me] = await Promise.all([
        apiGetSafe<{ ok: boolean }>('/health'),
        apiGetSafe<ApiOverviewDTO>('/api/public/overview'),
        apiGetSafe<MeDTO>('/me'),
      ]);

      const activeGuild = guildId ?? me?.selected_guild_id ?? me?.guilds?.[0]?.id ?? null;
      let raids: RaidDTO[] = [];
      let templates: RaidTemplateDTO[] = [];
      let tickets: TicketTranscriptDTO[] = [];

      if (activeGuild) {
        const [loadedRaids, loadedTemplates, loadedTickets] = await Promise.all([
          apiGetSafe<RaidDTO[]>('/api/raids'),
          apiGetSafe<RaidTemplateDTO[]>('/api/raid-templates'),
          apiGetSafe<TicketTranscriptDTO[]>(`/api/guilds/${activeGuild}/tickets`),
        ]);
        raids = loadedRaids ?? [];
        templates = loadedTemplates ?? [];
        tickets = loadedTickets ?? [];
      }

      setState({
        health: Boolean(health?.ok),
        overview,
        me,
        raids,
        templates,
        tickets,
        selectedTicket: null,
      });
      setSelectedGuildId(activeGuild);
      setSelectedTicketId((prev) => (tickets.some((t) => t.ticket_id === prev) ? prev : ''));
      setRaidTemplate((prev) => prev || templates[0]?.name || '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de chargement');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedGuildId || !selectedTicketId) {
      setState((prev) => ({ ...prev, selectedTicket: null }));
      return;
    }
    void apiGet<TicketTranscriptDTO>(`/api/guilds/${selectedGuildId}/tickets/${selectedTicketId}`)
      .then((ticket) => setState((prev) => ({ ...prev, selectedTicket: ticket })))
      .catch(() => setState((prev) => ({ ...prev, selectedTicket: null })));
  }, [selectedGuildId, selectedTicketId]);

  const canUseDashboard = Boolean(state.me?.guilds?.length);

  const sortedTickets = useMemo(
    () => [...state.tickets].sort((a, b) => b.updated_at - a.updated_at),
    [state.tickets]
  );

  async function onSelectGuild(guildId: number) {
    setBusy(true);
    setError('');
    try {
      await apiPost(`/me/select-guild/${guildId}`);
      await loadDashboard(guildId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Impossible de changer de serveur');
      setBusy(false);
    }
  }

  async function onLogout() {
    setBusy(true);
    setError('');
    try {
      await apiPost('/auth/logout');
      setState(initialState);
      setSelectedGuildId(null);
      setSelectedTicketId('');
      await loadDashboard(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Déconnexion impossible');
      setBusy(false);
    }
  }

  async function onOpenRaid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedGuildId || !raidTemplate || !raidStartAt || !raidTitle) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await apiPost('/api/actions/raids/open', {
        request_id: crypto.randomUUID(),
        guild_id: selectedGuildId,
        template_name: raidTemplate,
        title: raidTitle,
        description: '',
        extra_message: '',
        start_at: Math.floor(new Date(raidStartAt).getTime() / 1000),
        prep_minutes: 10,
        cleanup_minutes: 30,
      });
      setRaidTitle('');
      await loadDashboard(selectedGuildId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ouverture de raid impossible');
      setBusy(false);
    }
  }

  return (
    <main className="discord-shell">
      <aside className="guild-rail">
        {state.me?.guilds?.map((guild) => (
          <button
            key={guild.id}
            className={guild.id === selectedGuildId ? 'guild-btn active' : 'guild-btn'}
            onClick={() => void onSelectGuild(guild.id)}
            type="button"
          >
            {guild.name.slice(0, 2).toUpperCase()}
          </button>
        ))}
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div>
            <h1>AlbionBot Dashboard</h1>
            <p>{state.health ? 'API en ligne' : 'API indisponible'} · UI style Discord</p>
          </div>
          {state.me ? (
            <div className="session-actions">
              <span>{state.me.user.global_name || state.me.user.username}</span>
              <button type="button" onClick={() => void onLogout()}>
                Déconnexion
              </button>
            </div>
          ) : (
            <a className="discord-login" href={`${apiBase}/auth/discord/login`}>
              Se connecter avec Discord
            </a>
          )}
        </header>

        {error && <p className="error-banner">{error}</p>}

        <section className="status-grid">
          <article><h3>Guilds</h3><strong>{state.overview?.guild_count ?? 0}</strong></article>
          <article><h3>Tickets</h3><strong>{state.overview?.ticket_count ?? 0}</strong></article>
          <article><h3>Raids</h3><strong>{state.overview?.raid_count ?? 0}</strong></article>
          <article><h3>Templates</h3><strong>{state.overview?.template_count ?? 0}</strong></article>
        </section>

        {canUseDashboard ? (
          <div className="workspace-grid">
            <section className="panel">
              <h2>Transcripts tickets</h2>
              <div className="ticket-columns">
                <ul>
                  {sortedTickets.map((ticket) => (
                    <li key={ticket.ticket_id}>
                      <button
                        type="button"
                        className={selectedTicketId === ticket.ticket_id ? 'row active' : 'row'}
                        onClick={() => setSelectedTicketId(ticket.ticket_id)}
                      >
                        <span>#{ticket.ticket_id}</span>
                        <small>{fmtDate(ticket.updated_at)}</small>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="transcript-viewer">
                  {!state.selectedTicket ? (
                    <p>Sélectionne un ticket pour afficher la copie complète.</p>
                  ) : (
                    state.selectedTicket.messages.map((message) => (
                      <article key={message.message_id} className="message-row">
                        <strong>{message.author_id}</strong>
                        <p>{message.content}</p>
                        <small>{fmtDate(message.created_at)} · {message.event_type}</small>
                      </article>
                    ))
                  )}
                </div>
              </div>
            </section>

            <section className="panel split">
              <div>
                <h2>Commande web · raid_open</h2>
                <form onSubmit={onOpenRaid} className="form-grid">
                  <label>
                    Template
                    <select value={raidTemplate} onChange={(e) => setRaidTemplate(e.target.value)}>
                      {state.templates.map((tpl) => (
                        <option value={tpl.name} key={tpl.name}>{tpl.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Titre
                    <input value={raidTitle} onChange={(e) => setRaidTitle(e.target.value)} placeholder="AVA ZvZ 20h" />
                  </label>
                  <label>
                    Date / heure
                    <input type="datetime-local" value={raidStartAt} onChange={(e) => setRaidStartAt(e.target.value)} />
                  </label>
                  <button type="submit">Ouvrir le raid</button>
                </form>
              </div>
              <div>
                <h2>Raids en ligne</h2>
                <ul>
                  {state.raids.map((raid) => (
                    <li key={raid.raid_id} className="raid-item">
                      <span>{raid.title}</span>
                      <small>{raid.status} · {fmtDate(raid.start_at)}</small>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          </div>
        ) : (
          <section className="panel">
            <h2>Connexion requise</h2>
            <p>Connecte-toi avec Discord pour synchroniser les permissions et gérer le bot par serveur.</p>
          </section>
        )}

        {busy && <p className="muted">Synchronisation en cours…</p>}
      </section>
    </main>
  );
}
