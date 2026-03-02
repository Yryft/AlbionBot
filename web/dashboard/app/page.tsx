import { DiscordNav } from '../components/DiscordNav';
import { apiGet, GuildDTO, TicketTranscriptDTO } from '../lib/api';

export default async function Home({ searchParams }: { searchParams: { guild?: string; ticket?: string } }) {
  const guilds = await apiGet<GuildDTO[]>('/api/guilds');
  const selectedGuild = Number(searchParams.guild || guilds[0]?.id || 0);
  const tickets = selectedGuild ? await apiGet<TicketTranscriptDTO[]>(`/api/guilds/${selectedGuild}/tickets`) : [];
  const selectedTicketId = searchParams.ticket || tickets[0]?.ticket_id;
  const selectedTicket = tickets.find((t) => t.ticket_id === selectedTicketId);

  return (
    <main className="screen">
      <DiscordNav guilds={guilds} selectedGuildId={selectedGuild} tickets={tickets} selectedTicketId={selectedTicketId} />
      <section className="transcript">
        <h2>Transcript</h2>
        {selectedTicket ? (
          <>
            <p>
              Ticket <strong>{selectedTicket.ticket_id}</strong> • statut: <strong>{selectedTicket.status}</strong>
            </p>
            <div className="messages">
              {selectedTicket.messages.map((m) => (
                <article key={`${m.message_id}-${m.created_at}`} className={`msg ${m.event_type}`}>
                  <header>
                    <span>user:{m.author_id}</span>
                    <span>{new Date(m.created_at * 1000).toLocaleString('fr-FR')}</span>
                    <span className="badge">{m.event_type}</span>
                  </header>
                  <pre>{m.content}</pre>
                </article>
              ))}
            </div>
          </>
        ) : (
          <p>Aucun transcript disponible.</p>
        )}
      </section>
    </main>
  );
}
