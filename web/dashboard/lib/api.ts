export type GuildDTO = { id: number; name: string };
export type TicketMessageDTO = { message_id: number; author_id: number; content: string; created_at: number; event_type: 'message' | 'edit' | 'delete' | 'system' };
export type TicketTranscriptDTO = {
  ticket_id: string;
  guild_id: number;
  owner_user_id: number;
  status: 'open' | 'closed' | 'deleted';
  ticket_type_key: string;
  messages: TicketMessageDTO[];
};

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
