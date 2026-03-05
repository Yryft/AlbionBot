'use client';

import { useEffect, useMemo, useState } from 'react';

type CraftItem = {
  id: string;
  name: string;
  tier: number;
  enchant: number;
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

type ApiErrorDetail = {
  code?: string;
  message?: string;
  details?: unknown;
};

class ApiRequestError extends Error {
  status: number;
  detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail, fallbackMessage: string) {
    super(detail.message || fallbackMessage);
    this.name = 'ApiRequestError';
    this.status = status;
    this.detail = detail;
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || '';

async function readApiError(response: Response, fallbackMessage: string) {
  let detail: ApiErrorDetail = {};
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === 'object' && 'detail' in payload) {
      const candidate = (payload as { detail?: unknown }).detail;
      if (candidate && typeof candidate === 'object') {
        const parsed = candidate as Record<string, unknown>;
        detail = {
          code: typeof parsed.code === 'string' ? parsed.code : undefined,
          message: typeof parsed.message === 'string' ? parsed.message : undefined,
          details: parsed.details,
        };
      }
    }
  } catch {
    detail = {};
  }

  throw new ApiRequestError(response.status, detail, fallbackMessage);
}

function resolveCraftApiErrorMessage(error: unknown) {
  if (!(error instanceof ApiRequestError)) {
    return 'Simulation indisponible. Vérifie la configuration API/provider.';
  }

  switch (error.detail.code) {
    case 'item_not_found':
      return "L'item sélectionné est introuvable. Vérifie l'ID et l'enchantement.";
    case 'missing_focus_cost':
      return 'Le coût du focus est manquant. Renseigne un prix de focus valide.';
    case 'provider_unreachable':
      return 'Le provider de marché est injoignable. Réessaie dans quelques instants.';
    default:
      return error.detail.message || error.message;
  }
}

export default function CraftCalculator() {
  const [items, setItems] = useState<CraftItem[]>([]);
  const [search, setSearch] = useState('');
  const [selectedItemId, setSelectedItemId] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [categoryMasteryLevel, setCategoryMasteryLevel] = useState(0);
  const [targetSpecializationLevel, setTargetSpecializationLevel] = useState(0);
  const [enchantmentLevel, setEnchantmentLevel] = useState(0);
  const [locationKey, setLocationKey] = useState('city');
  const [cityKey, setCityKey] = useState('lymhurst');
  const [hideoutBiomeKey, setHideoutBiomeKey] = useState('mountain');
  const [hideoutTerritoryLevel, setHideoutTerritoryLevel] = useState(9);
  const [hideoutZoneQuality, setHideoutZoneQuality] = useState(1);
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
  const [prefsLoaded, setPrefsLoaded] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/craft/items?q=&limit=25`, { signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(`items_${r.status}`);
        const payload: unknown = await r.json();
        if (!Array.isArray(payload)) throw new Error('items_invalid_payload');
        return payload as CraftItem[];
      })
      .then((rows) => {
        setItems(rows);
        setSelectedItemId((prev) => (prev || rows.length === 0 ? prev : rows[0].id));
      })
      .catch(() => {
        setItems([]);
        setError('API craft indisponible (items). Réessaie dans quelques instants.');
      });
    return () => controller.abort();
  }, []);


  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/user/preferences/craft`, { credentials: 'include', signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) return null;
        return (await r.json()) as Record<string, unknown>;
      })
      .then((prefs) => {
        if (!prefs) return;
        if (typeof prefs.item_id === 'string') setSelectedItemId(prefs.item_id);
        if (typeof prefs.enchantment_level === 'number') setEnchantmentLevel(Math.max(0, Math.min(4, Math.floor(prefs.enchantment_level))));
        if (typeof prefs.quantity === 'number') setQuantity(Math.max(1, Math.floor(prefs.quantity)));
        if (typeof prefs.category_mastery_level === 'number') setCategoryMasteryLevel(Math.max(0, Math.min(100, Math.floor(prefs.category_mastery_level))));
        if (typeof prefs.target_specialization_level === 'number') setTargetSpecializationLevel(Math.max(0, Math.min(100, Math.floor(prefs.target_specialization_level))));
        if (typeof prefs.location_key === 'string') setLocationKey(prefs.location_key);
        if (typeof prefs.city_key === 'string') setCityKey(prefs.city_key);
        if (typeof prefs.hideout_biome_key === 'string') setHideoutBiomeKey(prefs.hideout_biome_key);
        if (typeof prefs.hideout_territory_level === 'number') setHideoutTerritoryLevel(Math.max(1, Math.min(9, Math.floor(prefs.hideout_territory_level))));
        if (typeof prefs.hideout_zone_quality === 'number') setHideoutZoneQuality(Math.max(1, Math.min(6, Math.floor(prefs.hideout_zone_quality))));
        if (typeof prefs.available_focus === 'number') setAvailableFocus(Math.max(0, Math.floor(prefs.available_focus)));
        if (typeof prefs.use_focus === 'boolean') setUseFocus(prefs.use_focus);
        if (typeof prefs.tax_rate === 'number') setTaxRate(Math.max(0, prefs.tax_rate));
        if (typeof prefs.focus_unit_price === 'number') setFocusUnitPrice(Math.max(0, prefs.focus_unit_price));
        if (typeof prefs.journal_unit_price === 'number') setJournalUnitPrice(Math.max(0, prefs.journal_unit_price));
        if (typeof prefs.sale_unit_price === 'number') setSaleUnitPrice(Math.max(0, prefs.sale_unit_price));
        if (prefs.pricing_mode === 'manual' || prefs.pricing_mode === 'prefilled') setPricingMode(prefs.pricing_mode);
      })
      .finally(() => setPrefsLoaded(true))
      .catch(() => setPrefsLoaded(true));

    return () => controller.abort();
  }, []);

  const filteredItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => `${item.name} ${item.id} T${item.tier} @${item.enchant}`.toLowerCase().includes(q));
  }, [items, search]);

  const availableEnchantments = useMemo(() => {
    const selected = items.find((row) => row.id === selectedItemId);
    if (!selected) return [0];
    const baseId = selected.id.split("@")[0];
    const levels = new Set<number>([0]);
    for (const row of items) {
      if (row.id.split("@")[0] === baseId) levels.add(Number(row.enchant) || 0);
    }
    return Array.from(levels).sort((a, b) => a - b);
  }, [items, selectedItemId]);

  useEffect(() => {
    if (!availableEnchantments.includes(enchantmentLevel)) {
      setEnchantmentLevel(availableEnchantments[0] ?? 0);
    }
  }, [availableEnchantments, enchantmentLevel]);


  useEffect(() => {
    if (!prefsLoaded) return;
    const timer = setTimeout(() => {
      fetch(`${API_BASE}/api/user/preferences/craft`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: selectedItemId || null,
          enchantment_level: enchantmentLevel,
          quantity,
          category_mastery_level: categoryMasteryLevel,
          target_specialization_level: targetSpecializationLevel,
          location_key: locationKey,
          city_key: cityKey,
          hideout_biome_key: hideoutBiomeKey,
          hideout_territory_level: hideoutTerritoryLevel,
          hideout_zone_quality: hideoutZoneQuality,
          available_focus: availableFocus,
          use_focus: useFocus,
          tax_rate: taxRate,
          focus_unit_price: focusUnitPrice,
          journal_unit_price: journalUnitPrice,
          sale_unit_price: saleUnitPrice,
          pricing_mode: pricingMode,
        }),
      }).catch(() => undefined);
    }, 500);
    return () => clearTimeout(timer);
  }, [prefsLoaded, selectedItemId, enchantmentLevel, quantity, categoryMasteryLevel, targetSpecializationLevel, locationKey, cityKey, hideoutBiomeKey, hideoutTerritoryLevel, hideoutZoneQuality, availableFocus, useFocus, taxRate, focusUnitPrice, journalUnitPrice, saleUnitPrice, pricingMode]);

  useEffect(() => {
    if (!selectedItemId) return;
    setError('');

    async function run() {
      const simulationRes = await fetch(`${API_BASE}/api/craft/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          item_id: selectedItemId,
          enchantment_level: enchantmentLevel,
          quantity,
          category_mastery_level: categoryMasteryLevel,
          item_specializations: { [selectedItemId]: targetSpecializationLevel },
          location_key: locationKey,
          city_key: cityKey,
          hideout_biome_key: hideoutBiomeKey,
          hideout_territory_level: hideoutTerritoryLevel,
          hideout_zone_quality: hideoutZoneQuality,
          available_focus: availableFocus,
          use_focus: useFocus,
        }),
      });
      if (!simulationRes.ok) {
        await readApiError(simulationRes, 'Échec de la simulation de craft.');
      }
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
      if (!profitabilityRes.ok) {
        await readApiError(profitabilityRes, 'Échec du calcul de rentabilité.');
      }
      setProfitability(await profitabilityRes.json());
    }

    run().catch((caughtError: unknown) => {
      setProfitability(null);
      setError(resolveCraftApiErrorMessage(caughtError));
    });
  }, [selectedItemId, enchantmentLevel, quantity, categoryMasteryLevel, targetSpecializationLevel, locationKey, cityKey, hideoutBiomeKey, hideoutTerritoryLevel, hideoutZoneQuality, availableFocus, useFocus, pricingMode, materialPrices, journalUnitPrice, saleUnitPrice, taxRate, focusUnitPrice]);

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
              <option key={item.id} value={item.id}>{item.name} · T{item.tier} · @{item.enchant} · {item.category}</option>
            ))}
          </select>
        </label>
        <label>
          Quantité
          <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))} />
        </label>
        <label>
          Enchantement
          <select value={enchantmentLevel} onChange={(e) => setEnchantmentLevel(Number(e.target.value) || 0)}>
            {availableEnchantments.map((level) => (
              <option key={level} value={level}>.{level} (@{level})</option>
            ))}
          </select>
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
        <label>Mastery catégorie <input type="number" min={0} max={100} value={categoryMasteryLevel} onChange={(e) => setCategoryMasteryLevel(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Spécialisation item cible <input type="number" min={0} max={100} value={targetSpecializationLevel} onChange={(e) => setTargetSpecializationLevel(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label>Location
          <select value={locationKey} onChange={(e) => setLocationKey(e.target.value)}>
            <option value="none">Sans bonus</option>
            <option value="city">Ville (bonus de ville/catégorie)</option>
            <option value="hideout">Hideout (niveau + qualité map)</option>
          </select>
        </label>
        {locationKey === 'city' && (
          <label>Ville
            <select value={cityKey} onChange={(e) => setCityKey(e.target.value)}>
              <option value="bridgewatch">Bridgewatch</option>
              <option value="martlock">Martlock</option>
              <option value="fort_sterling">Fort Sterling</option>
              <option value="thetford">Thetford</option>
              <option value="lymhurst">Lymhurst</option>
              <option value="caerleon">Caerleon</option>
            </select>
          </label>
        )}
        {locationKey === 'hideout' && (
          <>
            <label>Biome
              <select value={hideoutBiomeKey} onChange={(e) => setHideoutBiomeKey(e.target.value)}>
                <option value="mountain">Mountain</option>
                <option value="forest">Forest</option>
                <option value="swamp">Swamp</option>
                <option value="highland">Highland</option>
                <option value="steppe">Steppe</option>
              </select>
            </label>
            <label>Qualité zone
              <select value={hideoutZoneQuality} onChange={(e) => setHideoutZoneQuality(Number(e.target.value) || 1)}>
                <option value={1}>Q1</option>
                <option value={2}>Q2</option>
                <option value={3}>Q3</option>
                <option value={4}>Q4</option>
                <option value={5}>Q5</option>
                <option value={6}>Q6</option>
              </select>
            </label>
            <label>Niveau territoire
              <select value={hideoutTerritoryLevel} onChange={(e) => setHideoutTerritoryLevel(Number(e.target.value) || 1)}>
                <option value={1}>Niv 1</option>
                <option value={2}>Niv 2</option>
                <option value={3}>Niv 3</option>
                <option value={4}>Niv 4</option>
                <option value={5}>Niv 5</option>
                <option value={6}>Niv 6</option>
                <option value={7}>Niv 7</option>
                <option value={8}>Niv 8</option>
                <option value={9}>Niv 9</option>
              </select>
            </label>
          </>
        )}
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
