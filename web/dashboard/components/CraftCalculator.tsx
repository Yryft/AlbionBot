'use client';

import { useEffect, useMemo, useState } from 'react';

type CraftItem = {
  id: string;
  name: string;
  tier: number;
  category: string;
  craftable: boolean;
};

type MaterialRow = {
  item_id: string;
  item_name: string;
  gross_quantity: number;
  net_quantity: number;
};

type SimulationResponse = {
  item_id: string;
  focus_efficiency: number;
  focus_per_item: number;
  total_focus: number;
  items_craftable_with_available_focus: number;
  base_materials: MaterialRow[];
  intermediate_materials: MaterialRow[];
  applied_yields: Record<string, number>;
};

type ProfitabilityLine = {
  item_id: string;
  item_name: string;
  quantity: number;
  unit_price: number;
  total_cost: number;
  source: string;
};

type ProfitabilityResponse = {
  material_lines: ProfitabilityLine[];
  total_material_cost: number;
  focus_cost: number;
  imbuer_journal_cost: number;
  total_cost: number;
  gross_revenue: number;
  market_tax_amount: number;
  net_revenue: number;
  profit: number;
  margin_pct: number;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || '';

export default function CraftCalculator() {
  const [items, setItems] = useState<CraftItem[]>([]);
  const [search, setSearch] = useState('');
  const [selectedItemId, setSelectedItemId] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [masteryLevel, setMasteryLevel] = useState(0);
  const [specializationLevel, setSpecializationLevel] = useState(0);
  const [locationKey, setLocationKey] = useState('city');
  const [availableFocus, setAvailableFocus] = useState(30000);
  const [useFocus, setUseFocus] = useState(true);
  const [taxRate, setTaxRate] = useState(6.5);
  const [focusUnitPrice, setFocusUnitPrice] = useState(0);
  const [journalUnitPrice, setJournalUnitPrice] = useState(0);
  const [saleUnitPrice, setSaleUnitPrice] = useState(0);
  const [pricingMode, setPricingMode] = useState<'manual' | 'prefilled'>('manual');
  const [materialPrices, setMaterialPrices] = useState<Record<string, number>>({});
  const [marketPriceHints, setMarketPriceHints] = useState<Record<string, number>>({});
  const [simulation, setSimulation] = useState<SimulationResponse | null>(null);
  const [profitability, setProfitability] = useState<ProfitabilityResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/craft/items?q=&limit=25`, { signal: controller.signal })
      .then((r) => r.json())
      .then((rows: CraftItem[]) => {
        setItems(rows);
        if (!selectedItemId && rows.length > 0) setSelectedItemId(rows[0].id);
      })
      .catch(() => setError('Impossible de charger les items craft.'));
    return () => controller.abort();
  }, [selectedItemId]);

  const filteredItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => `${item.name} ${item.id} T${item.tier}`.toLowerCase().includes(q));
  }, [items, search]);

  useEffect(() => {
    if (!selectedItemId) return;
    setError('');

    async function run() {
      const simulationRes = await fetch(`${API_BASE}/api/craft/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: selectedItemId,
          quantity,
          mastery_level: masteryLevel,
          specialization_level: specializationLevel,
          location_key: locationKey,
          available_focus: availableFocus,
          use_focus: useFocus,
        }),
      });
      if (!simulationRes.ok) throw new Error('simulation_failed');
      const simulationPayload: SimulationResponse = await simulationRes.json();
      setSimulation(simulationPayload);

      const detailRes = await fetch(`${API_BASE}/api/craft/items/${selectedItemId}`);
      if (detailRes.ok) {
        const detail = await detailRes.json();
        const hintedPrices: Record<string, number> = detail?.metadata?.market_prices ?? {};
        setMarketPriceHints(hintedPrices);
        if (pricingMode === 'prefilled' && Object.keys(hintedPrices).length > 0) {
          setMaterialPrices((prev) => ({ ...hintedPrices, ...prev }));
        }
      }

      const profitabilityRes = await fetch(`${API_BASE}/api/craft/profitability`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          simulation: simulationPayload,
          material_unit_prices: materialPrices,
          imbuer_journal_unit_price: journalUnitPrice,
          item_sale_unit_price: saleUnitPrice,
          crafted_quantity: quantity,
          market_tax_rate: taxRate,
          focus_unit_price: focusUnitPrice,
          include_focus_cost: useFocus,
          pricing_mode: pricingMode,
        }),
      });
      if (!profitabilityRes.ok) throw new Error('profitability_failed');
      setProfitability(await profitabilityRes.json());
    }

    run().catch(() => {
      setProfitability(null);
      setError('Simulation indisponible. Vérifie la configuration API/provider.');
    });
  }, [selectedItemId, quantity, masteryLevel, specializationLevel, locationKey, availableFocus, useFocus, pricingMode, materialPrices, journalUnitPrice, saleUnitPrice, taxRate, focusUnitPrice]);

  const marketPrefillAvailable = Object.keys(marketPriceHints).length > 0;

  return (
    <div className="craft-calculator">
      <div className="craft-controls">
        <label className="craft-search">
          Rechercher un item
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Ex: cleric, sword, T6..." />
        </label>
        <label>
          Item
          <select value={selectedItemId} onChange={(e) => setSelectedItemId(e.target.value)}>
            {filteredItems.map((item) => (
              <option key={item.id} value={item.id}>{item.name} · T{item.tier} · {item.category}</option>
            ))}
          </select>
        </label>
        <label>
          Quantité
          <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))} />
        </label>
        <label>
          Mode prix
          <select value={pricingMode} onChange={(e) => setPricingMode(e.target.value as 'manual' | 'prefilled')}>
            <option value="manual">Prix manuel</option>
            <option value="prefilled" disabled={!marketPrefillAvailable}>Prérempli (API marché)</option>
          </select>
        </label>
      </div>

      <div className="craft-controls craft-bonus-grid">
        <label>Mastery <input type="number" min={0} max={100} value={masteryLevel} onChange={(e) => setMasteryLevel(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Specialization <input type="number" min={0} max={100} value={specializationLevel} onChange={(e) => setSpecializationLevel(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Location
          <select value={locationKey} onChange={(e) => setLocationKey(e.target.value)}>
            <option value="none">Sans bonus</option>
            <option value="city">Ville</option>
            <option value="hideout">Hideout</option>
            <option value="hideout_quality">Hideout qualité</option>
          </select>
        </label>
        <label>Focus dispo <input type="number" min={0} value={availableFocus} onChange={(e) => setAvailableFocus(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Taxe marché (%) <input type="number" min={0} max={20} step={0.1} value={taxRate} onChange={(e) => setTaxRate(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Prix focus unitaire <input type="number" min={0} value={focusUnitPrice} onChange={(e) => setFocusUnitPrice(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Livre d'imbuer / unité <input type="number" min={0} value={journalUnitPrice} onChange={(e) => setJournalUnitPrice(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Prix vente item / unité <input type="number" min={0} value={saleUnitPrice} onChange={(e) => setSaleUnitPrice(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label className="craft-checkbox"><input type="checkbox" checked={useFocus} onChange={(e) => setUseFocus(e.target.checked)} /> Valoriser le focus</label>
      </div>

      {error && <p className="muted">{error}</p>}

      <div className="craft-results">
        <section>
          <h3>Breakdown matériaux</h3>
          <div className="craft-table">
            <div className="craft-row craft-head">
              <span>Matériau</span><span>Qté brute</span><span>Qté nette</span><span>Prix unitaire</span><span>Ligne</span>
            </div>
            {(simulation?.base_materials ?? []).map((row) => {
              const unitPrice = materialPrices[row.item_id] ?? marketPriceHints[row.item_id] ?? 0;
              const line = profitability?.material_lines.find((l) => l.item_id === row.item_id);
              return (
                <div key={row.item_id} className="craft-row">
                  <span>{row.item_name}</span>
                  <span>{row.gross_quantity}</span>
                  <span>{row.net_quantity}</span>
                  <label>
                    <input
                      type="number"
                      min={0}
                      value={unitPrice}
                      onChange={(e) => setMaterialPrices((prev) => ({ ...prev, [row.item_id]: Math.max(0, Number(e.target.value) || 0) }))}
                    />
                  </label>
                  <span>{Math.round(line?.total_cost ?? 0).toLocaleString('fr-FR')}</span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="craft-profit">
          <h3>Récap rentabilité</h3>
          <dl>
            <div><dt>Coût total matériaux</dt><dd>{Math.round(profitability?.total_material_cost ?? 0).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Coût focus implicite</dt><dd>{Math.round(profitability?.focus_cost ?? 0).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Coût livres d'imbuer</dt><dd>{Math.round(profitability?.imbuer_journal_cost ?? 0).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Revenu brut</dt><dd>{Math.round(profitability?.gross_revenue ?? 0).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Revenu net</dt><dd>{Math.round(profitability?.net_revenue ?? 0).toLocaleString('fr-FR')}</dd></div>
            <div className={(profitability?.profit ?? 0) >= 0 ? 'profit-positive' : 'profit-negative'}><dt>Profit</dt><dd>{Math.round(profitability?.profit ?? 0).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Marge</dt><dd>{(profitability?.margin_pct ?? 0).toFixed(1)}%</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}
