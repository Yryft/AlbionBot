import { ApiOverviewDTO, GuildDTO, apiGetSafe } from '../lib/api';

export default async function HomePage() {
  const [health, overview, guilds] = await Promise.all([
    apiGetSafe<{ ok: boolean }>('/health'),
    apiGetSafe<ApiOverviewDTO>('/api/public/overview'),
    apiGetSafe<GuildDTO[]>('/api/guilds'),
  ]);

  const apiOnline = Boolean(health?.ok);

  return (
    <main className="page">
      <header>
        <h1>AlbionBot Dashboard</h1>
        <p>Version web simplifiée basée sur l'API.</p>
      </header>

      <section className="status-card">
        <h2>État API</h2>
        <p className={apiOnline ? 'ok' : 'ko'}>{apiOnline ? 'En ligne' : 'Indisponible'}</p>
      </section>

      <section className="status-grid">
        <article>
          <h3>Guilds</h3>
          <strong>{overview?.guild_count ?? guilds?.length ?? 0}</strong>
        </article>
        <article>
          <h3>Tickets</h3>
          <strong>{overview?.ticket_count ?? 0}</strong>
        </article>
        <article>
          <h3>Raids</h3>
          <strong>{overview?.raid_count ?? 0}</strong>
        </article>
        <article>
          <h3>Templates</h3>
          <strong>{overview?.template_count ?? 0}</strong>
        </article>
      </section>

      <section className="status-card">
        <h2>Guilds détectées</h2>
        {!guilds?.length ? (
          <p>Aucune guild trouvée pour le moment.</p>
        ) : (
          <ul>
            {guilds.map((guild) => (
              <li key={guild.id}>
                <span>{guild.name}</span>
                <small>ID: {guild.id}</small>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
