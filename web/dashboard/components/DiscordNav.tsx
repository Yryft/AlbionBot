'use client';

import type { GuildDTO, TicketTranscriptDTO } from '../lib/api';

type Props = {
  guilds: GuildDTO[];
  selectedGuildId?: string;
  tickets: TicketTranscriptDTO[];
  selectedTicketId?: string;
};

export function DiscordNav({ guilds, selectedGuildId, tickets, selectedTicketId }: Props) {
  return (
    <div className="layout">
      <aside className="guilds">
        {guilds.map((g) => (
          <a key={g.id} className={selectedGuildId === g.id ? 'guild active' : 'guild'} href={`/?guild=${g.id}`}>
            {g.name.slice(0, 2).toUpperCase()}
          </a>
        ))}
      </aside>
      <aside className="channels">
        <h3>Tickets</h3>
        {tickets.map((t) => (
          <a
            key={t.ticket_id}
            className={selectedTicketId === t.ticket_id ? 'channel active' : 'channel'}
            href={`/?guild=${t.guild_id}&ticket=${t.ticket_id}`}
          >
            #{t.ticket_id}
          </a>
        ))}
      </aside>
    </div>
  );
}
