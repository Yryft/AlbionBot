export type RoleDTO = { id: string; name: string };

export type GuildDTO = { id: string; name: string; roles?: RoleDTO[] };

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
  id: string;
  name: string;
  icon?: string | null;
  owner?: boolean;
  permissions?: string;
};

export type MeDTO = {
  user: DiscordUserDTO;
  csrf_token: string;
  selected_guild_id?: string | null;
  guilds: DiscordGuildDTO[];
};

export type DiscordChannelDTO = { id: string; name: string; type: number };
export type DiscordMemberDTO = { id: string; display_name: string };
export type DiscordDirectoryDTO = {
  channels: DiscordChannelDTO[];
  roles: RoleDTO[];
  members: DiscordMemberDTO[];
};

export type TicketMessageDTO = {
  message_id: string;
  author_id: string;
  author_name?: string;
  author_avatar_url?: string;
  content: string;
  created_at: number;
  event_type: 'message' | 'edit' | 'delete' | 'system';
  embeds?: Record<string, unknown>[];
  attachments?: Record<string, unknown>[];
};

export type TicketTranscriptDTO = {
  ticket_id: string;
  guild_id: string;
  owner_user_id: string;
  status: 'open' | 'closed' | 'deleted';
  ticket_type_key: string;
  channel_id?: string | null;
  thread_id?: string | null;
  created_at: number;
  updated_at: number;
  messages: TicketMessageDTO[];
};

export type RaidRoleDTO = {
  key: string;
  label: string;
  slots: number;
  ip_required: boolean;
  required_role_ids: string[];
};

export type RaidTemplateDTO = {
  name: string;
  description: string;
  content_type: 'ava_raid' | 'pvp' | 'pve';
  created_by: string;
  created_at: number;
  raid_required_role_ids: string[];
  roles: RaidRoleDTO[];
};

export type RaidDTO = {
  raid_id: string;
  template_name: string;
  title: string;
  description: string;
  extra_message: string;
  start_at: number;
  created_by: string;
  created_at: number;
  channel_id?: string | null;
  message_id?: string | null;
  publish_status: 'pending' | 'delivered' | 'failed';
  publish_error: string;
  voice_channel_id?: string | null;
  status: 'OPEN' | 'PINGED' | 'CLOSED';
};



export type RaidParticipantDTO = {
  user_id: string;
  role_key: string;
  status: 'main' | 'wait';
  ip?: number | null;
  joined_at: number;
};

export type RaidRosterDTO = {
  raid: RaidDTO;
  participants: RaidParticipantDTO[];
  absent_user_ids: string[];
};

export type BalanceEntryDTO = {
  user_id: string;
  balance: number;
  rank?: number;
};

export type BankActionType = 'add' | 'remove' | 'add_split' | 'remove_split';

export type BankBalanceDTO = {
  guild_id: string;
  user_id: string;
  balance: number;
};

export type BankActionHistoryEntryDTO = {
  action_id: string;
  guild_id: string;
  actor_id: string;
  created_at: number;
  action_type: BankActionType;
  total_delta: number;
  impacted_users: number;
  note: string;
  undone: boolean;
  undone_at?: number | null;
};

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

let csrfTokenCache = "";

export function setCsrfToken(token: string): void {
  csrfTokenCache = token;
}

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

async function buildApiError(res: Response, path: string): Promise<Error> {
  try {
    const payload = (await res.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return new Error(payload.detail);
    }
  } catch {
    // ignore parsing issues and fallback to status-based error
  }
  return new Error(`API error (${res.status}) on ${path}`);
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    cache: 'no-store',
    credentials: 'include',
  });
  if (!res.ok) {
    throw await buildApiError(res, path);
  }
  return parseJsonSafe<T>(res);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const csrfToken = getCookie('albion_dash_csrf') || csrfTokenCache;
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
    throw await buildApiError(res, path);
  }
  if (res.status === 204) {
    return {} as T;
  }
  return parseJsonSafe<T>(res);
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const csrfToken = getCookie('albion_dash_csrf') || csrfTokenCache;
  const res = await fetch(`${baseUrl}${path}`, {
    method: 'PUT',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    throw await buildApiError(res, path);
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

export async function apiDelete<T>(path: string): Promise<T> {
  const csrfToken = getCookie('albion_dash_csrf') || csrfTokenCache;
  const res = await fetch(`${baseUrl}${path}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {},
  });
  if (!res.ok) {
    throw await buildApiError(res, path);
  }
  return parseJsonSafe<T>(res);
}
