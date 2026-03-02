export type RoleDTO = { id: number; name: string };

export type GuildDTO = { id: number; name: string; roles?: RoleDTO[] };

export type ApiOverviewDTO = {
  ok: boolean;
  guild_count: number;
  ticket_count: number;
  raid_count: number;
  template_count: number;
};

export type DiscordUserDTO = {
  id: string;
  username: string;
  global_name?: string | null;
  avatar?: string | null;
};

export type DiscordGuildDTO = {
  id: number;
  name: string;
  icon?: string | null;
  owner?: boolean;
  permissions?: string;
};

export type MeDTO = {
  user: DiscordUserDTO;
  selected_guild_id?: number | null;
  guilds: DiscordGuildDTO[];
};

export type TicketMessageDTO = {
  message_id: number;
  author_id: number;
  content: string;
  created_at: number;
  event_type: 'message' | 'edit' | 'delete' | 'system';
};

export type TicketTranscriptDTO = {
  ticket_id: string;
  guild_id: number;
  owner_user_id: number;
  status: 'open' | 'closed' | 'deleted';
  ticket_type_key: string;
  channel_id?: number | null;
  thread_id?: number | null;
  created_at: number;
  updated_at: number;
  messages: TicketMessageDTO[];
};

export type RaidRoleDTO = {
  key: string;
  label: string;
  slots: number;
  ip_required: boolean;
  required_role_ids: number[];
};

export type RaidTemplateDTO = {
  name: string;
  description: string;
  content_type: 'ava_raid' | 'pvp' | 'pve';
  created_by: number;
  created_at: number;
  raid_required_role_ids: number[];
  roles: RaidRoleDTO[];
};

export type RaidDTO = {
  raid_id: string;
  template_name: string;
  title: string;
  description: string;
  extra_message: string;
  start_at: number;
  created_by: number;
  created_at: number;
  status: 'OPEN' | 'PINGED' | 'CLOSED';
};

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

function getCookie(name: string): string {
  if (typeof document === 'undefined') {
    return '';
  }
  const row = document.cookie
    .split('; ')
    .find((entry) => entry.startsWith(`${name}=`));
  return row ? decodeURIComponent(row.slice(name.length + 1)) : '';
}

async function parseJsonSafe<T>(res: Response): Promise<T> {
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    cache: 'no-store',
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`API error (${res.status}) on ${path}`);
  }
  return parseJsonSafe<T>(res);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const csrfToken = getCookie('albion_dash_csrf');
  const res = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`API error (${res.status}) on ${path}`);
  }
  if (res.status === 204) {
    return {} as T;
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
