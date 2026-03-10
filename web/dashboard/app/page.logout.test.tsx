import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import HomePage from './page';
import { ApiError, apiGet, apiGetSafe, apiPost, clearCsrfToken } from '../lib/api';

vi.mock('../lib/api', () => {
  class ApiError extends Error {
    code?: string;
    details?: Record<string, unknown>;
    status?: number;

    constructor(message: string, payload?: { code?: string; details?: Record<string, unknown>; status?: number }) {
      super(message);
      this.name = 'ApiError';
      this.code = payload?.code;
      this.details = payload?.details;
      this.status = payload?.status;
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
    clearCsrfToken: vi.fn(),
  };
});

describe('Dashboard logout error handling', () => {
  const mockedApiGetSafe = vi.mocked(apiGetSafe);
  const mockedApiGet = vi.mocked(apiGet);
  const mockedApiPost = vi.mocked(apiPost);
  const mockedClearCsrfToken = vi.mocked(clearCsrfToken);

  beforeEach(() => {
    vi.clearAllMocks();
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
  });

  it('force la déconnexion locale et affiche un message session expirée sur 401/403', async () => {
    mockedApiPost.mockRejectedValueOnce(new ApiError('expired', { status: 401 }));

    render(<HomePage />);

    const logoutButton = await screen.findByRole('button', { name: 'Déconnexion' });
    fireEvent.click(logoutButton);

    expect(await screen.findByText('Session expirée, reconnexion nécessaire')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Connecte-toi avec Discord' })).toBeInTheDocument();
    expect(mockedClearCsrfToken).toHaveBeenCalledTimes(1);
  });

  it('affiche une bannière non bloquante avec retry sur erreur serveur inattendue', async () => {
    mockedApiPost.mockRejectedValueOnce(new Error('network down'));

    render(<HomePage />);

    const logoutButton = await screen.findByRole('button', { name: 'Déconnexion' });
    fireEvent.click(logoutButton);

    expect(await screen.findByText('Impossible de terminer la déconnexion côté serveur')).toBeInTheDocument();
    const retryButton = screen.getByRole('button', { name: 'Réessayer la déconnexion' });
    expect(retryButton).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'AlbionBot Dashboard' }).length).toBeGreaterThan(0);

    fireEvent.click(retryButton);
    await waitFor(() => {
      expect(mockedApiPost).toHaveBeenCalledTimes(2);
    });
  });
});
