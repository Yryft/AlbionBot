import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import HomePage from './page';
import { apiGet, apiGetSafe } from '../lib/api';

vi.mock('../lib/api', () => {
  class ApiError extends Error {
    code?: string;
    details?: Record<string, unknown>;

    constructor(message: string, payload?: { code?: string; details?: Record<string, unknown> }) {
      super(message);
      this.name = 'ApiError';
      this.code = payload?.code;
      this.details = payload?.details;
    }
  }

  return {
    ApiError,
    apiGet: vi.fn(),
    apiGetSafe: vi.fn(),
    apiPost: vi.fn(),
    apiPut: vi.fn(),
    apiDelete: vi.fn(),
    setCsrfToken: vi.fn(),
  };
});

describe('Dashboard auth CTA links', () => {
  const mockedApiGetSafe = vi.mocked(apiGetSafe);
  const mockedApiGet = vi.mocked(apiGet);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('affiche les deux CTA invités avec les href reprise et force=1', async () => {
    mockedApiGetSafe.mockImplementation(async (path: string) => {
      if (path === '/health') return { ok: true };
      if (path === '/api/public/overview') {
        return { ok: true, guild_count: 0, ticket_count: 0, raid_count: 0, template_count: 0 };
      }
      if (path === '/me') return null;
      return null;
    });

    render(<HomePage />);

    const continueLink = await screen.findByRole('link', { name: 'Continuer avec Discord' });
    const switchLink = await screen.findByRole('link', { name: 'Utiliser un autre compte' });

    expect(continueLink).toHaveAttribute('href', 'http://localhost:8000/auth/discord/login');
    expect(switchLink).toHaveAttribute('href', 'http://localhost:8000/auth/discord/login?force=1');
  });

  it('affiche le bouton session "Changer de compte" avec le flux force=1', async () => {
    mockedApiGetSafe.mockImplementation(async (path: string) => {
      if (path === '/health') return { ok: true };
      if (path === '/api/public/overview') {
        return { ok: true, guild_count: 1, ticket_count: 1, raid_count: 1, template_count: 1 };
      }
      if (path === '/me') {
        return {
          user: { id: '1', username: 'alice', global_name: 'Alice', avatar: null },
          csrf_token: 'csrf',
          selected_guild_id: 'guild-1',
          guilds: [{ id: 'guild-1', name: 'Guild One', owner: true, permissions: '8', icon: null }],
        };
      }
      return null;
    });

    mockedApiGet.mockResolvedValue([]);
    render(<HomePage />);

    const changeAccountLink = await screen.findByRole('link', { name: 'Changer de compte' });
    expect(changeAccountLink).toHaveAttribute('href', 'http://localhost:8000/auth/discord/login?force=1');

    await waitFor(() => {
      expect(mockedApiGet).toHaveBeenCalled();
    });
  });
});
