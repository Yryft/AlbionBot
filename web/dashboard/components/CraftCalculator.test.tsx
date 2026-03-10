import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import CraftCalculator from './CraftCalculator';

const itemRows = [
  {
    id: 'T4_MAIN_SWORD',
    name: 'Adept Broadsword',
    tier: 4,
    enchant: 0,
    icon: 'https://icons/T4_MAIN_SWORD.png',
    category: 'sword',
    craftable: true,
  },
  {
    id: 'T4_MAIN_SWORD@2',
    name: 'Adept Broadsword .2',
    tier: 4,
    enchant: 2,
    icon: 'https://icons/T4_MAIN_SWORD.png',
    category: 'weapon',
    craftable: true,
  },
];

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

describe('CraftCalculator', () => {
  const originalFetch = global.fetch;
  let simulateCalls = 0;

  beforeEach(() => {
    simulateCalls = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();

      if (url.includes('/api/craft/items?q=')) {
        if (url.includes('item-introuvable')) {
          return jsonResponse([]);
        }
        return jsonResponse(itemRows);
      }
      if (url.includes('/api/user/preferences/craft') && init?.method === 'PUT') {
        return jsonResponse({ ok: true });
      }
      if (url.includes('/api/user/preferences/craft')) {
        return new Response(null, { status: 404 });
      }
      if (url.includes('/api/craft/simulate')) {
        simulateCalls += 1;
        return jsonResponse({
          item_id: itemRows[0].id,
          focus_efficiency: 0.1,
          focus_per_item: 10,
          total_focus: 100,
          items_craftable_with_available_focus: 10,
          base_materials: [],
          intermediate_materials: [],
          applied_yields: {},
        });
      }
      if (url.includes('/api/craft/specializations/')) {
        return jsonResponse([
          {
            item_id: 'T4_MAIN_SWORD',
            item_name: 'Adept Broadsword',
            icon: 'https://icons/T4_MAIN_SWORD.png',
            category: 'weapon',
            tier: 4,
          },
        ]);
      }
      if (url.includes(`/api/craft/items/${itemRows[0].id}`)) {
        return jsonResponse({ metadata: { market_prices: {} } });
      }
      if (url.includes('/api/craft/profitability')) {
        return jsonResponse({
          material_lines: [],
          total_material_cost: 0,
          focus_cost: 0,
          imbuer_journal_cost: 0,
          total_cost: 0,
          gross_revenue: 0,
          market_tax_amount: 0,
          station_fee_amount: 0,
          net_revenue: 0,
          profit: 0,
          margin_pct: 0,
        });
      }

      return new Response(null, { status: 404 });
    }) as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("n'envoie pas de nouvelle simulation quand la recherche autocomplete ne retourne aucun item", async () => {
    render(<CraftCalculator />);

    await waitFor(() => expect(simulateCalls).toBeGreaterThan(0));
    const callsBeforeSearch = simulateCalls;

    const searchInput = screen.getByPlaceholderText('Nom ou ID (ex: Adept Broadsword, T4_MAIN_SWORD)');
    fireEvent.change(searchInput, { target: { value: 'item-introuvable' } });

    expect(await screen.findByText('Aucun item correspondant')).toBeInTheDocument();
    await waitFor(() => expect(simulateCalls).toBe(callsBeforeSearch));
  });
});
