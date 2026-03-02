export type GuildDTO = { id: number; name: string };

export type ApiOverviewDTO = {
  ok: boolean;
  guild_count: number;
  ticket_count: number;
  raid_count: number;
  template_count: number;
};

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

async function parseJsonSafe<T>(res: Response): Promise<T> {
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`API error (${res.status}) on ${path}`);
  }
  return parseJsonSafe<T>(res);
}

export async function apiGetSafe<T>(path: string): Promise<T | null> {
  try {
    return await apiGet<T>(path);
  } catch {
    return null;
  }
}
