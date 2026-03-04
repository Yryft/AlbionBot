'use client';

import { useMemo, useState } from 'react';

type MaterialRequirement = {
  key: string;
  label: string;
  qty: number;
};

type CraftItem = {
  key: string;
  name: string;
  tier: number;
  category: string;
  sellPrice: number;
  defaultCraftFee: number;
  recipe: MaterialRequirement[];
};

const craftItems: CraftItem[] = [
  {
    key: 'adept_cleric_robe',
    name: 'Adept Cleric Robe',
    tier: 4,
    category: 'Armor',
    sellPrice: 37500,
    defaultCraftFee: 1800,
    recipe: [
      { key: 'cloth_t4', label: 'Cloth T4', qty: 16 },
      { key: 'plank_t4', label: 'Planks T4', qty: 8 },
    ],
  },
  {
    key: 'expert_soldier_boots',
    name: 'Expert Soldier Boots',
    tier: 5,
    category: 'Armor',
    sellPrice: 61200,
    defaultCraftFee: 2400,
    recipe: [
      { key: 'leather_t5', label: 'Leather T5', qty: 18 },
      { key: 'cloth_t5', label: 'Cloth T5', qty: 6 },
    ],
  },
  {
    key: 'master_broadsword',
    name: 'Master Broadsword',
    tier: 6,
    category: 'Weapon',
    sellPrice: 148000,
    defaultCraftFee: 3600,
    recipe: [
      { key: 'metalbar_t6', label: 'Metal Bars T6', qty: 16 },
      { key: 'plank_t6', label: 'Planks T6', qty: 12 },
    ],
  },
  {
    key: 'grandmaster_mercenary_jacket',
    name: 'Grandmaster Mercenary Jacket',
    tier: 7,
    category: 'Armor',
    sellPrice: 325000,
    defaultCraftFee: 5200,
    recipe: [
      { key: 'leather_t7', label: 'Leather T7', qty: 22 },
      { key: 'cloth_t7', label: 'Cloth T7', qty: 10 },
    ],
  },
];

export default function CraftCalculator() {
  const [search, setSearch] = useState('');
  const [selectedItemKey, setSelectedItemKey] = useState<string>(craftItems[0]?.key ?? '');
  const [quantity, setQuantity] = useState(1);
  const [cityBonus, setCityBonus] = useState(15);
  const [hideoutBonus, setHideoutBonus] = useState(0);
  const [taxRate, setTaxRate] = useState(6.5);
  const [craftFee, setCraftFee] = useState(craftItems[0]?.defaultCraftFee ?? 0);
  const [salePrice, setSalePrice] = useState(craftItems[0]?.sellPrice ?? 0);
  const [materialPrices, setMaterialPrices] = useState<Record<string, number>>({
    cloth_t4: 640,
    plank_t4: 520,
    leather_t5: 1230,
    cloth_t5: 980,
    metalbar_t6: 3350,
    plank_t6: 2740,
    leather_t7: 7900,
    cloth_t7: 6840,
  });

  const filteredItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return craftItems;
    return craftItems.filter((item) =>
      `${item.name} ${item.category} T${item.tier}`.toLowerCase().includes(query),
    );
  }, [search]);

  const selectedItem = useMemo(
    () => craftItems.find((item) => item.key === selectedItemKey) ?? null,
    [selectedItemKey],
  );

  const displayedItems = useMemo(() => {
    if (filteredItems.length > 0) return filteredItems;
    return selectedItem ? [selectedItem] : [];
  }, [filteredItems, selectedItem]);

  const materialRows = useMemo(() => {
    if (!selectedItem) return [];
    const returnRate = Math.min((cityBonus + hideoutBonus) / 100, 0.95);

    return selectedItem.recipe.map((material) => {
      const baseQty = material.qty * quantity;
      const effectiveQty = baseQty * (1 - returnRate);
      const unitPrice = materialPrices[material.key] ?? 0;
      const totalCost = effectiveQty * unitPrice;
      return {
        ...material,
        baseQty,
        effectiveQty,
        unitPrice,
        totalCost,
      };
    });
  }, [cityBonus, hideoutBonus, materialPrices, quantity, selectedItem]);

  const summary = useMemo(() => {
    const materialsCost = materialRows.reduce((sum, row) => sum + row.totalCost, 0);
    const craftCost = craftFee * quantity;
    const grossRevenue = salePrice * quantity;
    const taxAmount = grossRevenue * (taxRate / 100);
    const netRevenue = grossRevenue - taxAmount;
    const totalCost = materialsCost + craftCost;
    const profit = netRevenue - totalCost;
    return {
      materialsCost,
      craftCost,
      grossRevenue,
      taxAmount,
      netRevenue,
      totalCost,
      profit,
      marginPct: netRevenue > 0 ? (profit / netRevenue) * 100 : 0,
    };
  }, [craftFee, materialRows, quantity, salePrice, taxRate]);

  function onSelectItem(itemKey: string) {
    const found = craftItems.find((item) => item.key === itemKey);
    if (!found) return;
    setSelectedItemKey(itemKey);
    setSalePrice(found.sellPrice);
    setCraftFee(found.defaultCraftFee);
  }

  return (
    <div className="craft-calculator">
      <div className="craft-controls">
        <label className="craft-search">
          Rechercher un item
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Ex: cleric, sword, T6..."
          />
        </label>

        <label>
          Item
          <select value={selectedItemKey} onChange={(e) => onSelectItem(e.target.value)}>
            {displayedItems.map((item) => (
              <option key={item.key} value={item.key}>
                {item.name} · T{item.tier} · {item.category}
              </option>
            ))}
          </select>
          {filteredItems.length === 0 && <small className="muted">Aucun résultat, item courant conservé.</small>}
        </label>

        <label>
          Quantité
          <input
            type="number"
            min={1}
            step={1}
            value={quantity}
            onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>
      </div>

      <div className="craft-controls craft-bonus-grid">
        <label>
          Bonus ville (%)
          <input
            type="number"
            min={0}
            max={65}
            step={0.1}
            value={cityBonus}
            onChange={(e) => setCityBonus(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
        <label>
          Bonus hideout (%)
          <input
            type="number"
            min={0}
            max={45}
            step={0.1}
            value={hideoutBonus}
            onChange={(e) => setHideoutBonus(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
        <label>
          Taxe marché (%)
          <input
            type="number"
            min={0}
            max={20}
            step={0.1}
            value={taxRate}
            onChange={(e) => setTaxRate(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
        <label>
          Frais craft / item
          <input
            type="number"
            min={0}
            step={100}
            value={craftFee}
            onChange={(e) => setCraftFee(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
        <label>
          Prix de vente / item
          <input
            type="number"
            min={0}
            step={100}
            value={salePrice}
            onChange={(e) => setSalePrice(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
      </div>

      <div className="craft-results">
        <section>
          <h3>Matériaux estimés</h3>
          <div className="craft-table">
            <div className="craft-row craft-head">
              <span>Matériau</span>
              <span>Qté brute</span>
              <span>Qté après bonus</span>
              <span>Prix unitaire</span>
              <span>Coût total</span>
            </div>
            {materialRows.map((row) => (
              <div key={row.key} className="craft-row">
                <span>{row.label}</span>
                <span>{row.baseQty.toFixed(2)}</span>
                <span>{row.effectiveQty.toFixed(2)}</span>
                <label>
                  <input
                    type="number"
                    min={0}
                    step={1}
                    value={row.unitPrice}
                    onChange={(e) =>
                      setMaterialPrices((prev) => ({
                        ...prev,
                        [row.key]: Math.max(0, Number(e.target.value) || 0),
                      }))
                    }
                  />
                </label>
                <span>{Math.round(row.totalCost).toLocaleString('fr-FR')}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="craft-profit">
          <h3>Profit estimé</h3>
          <dl>
            <div><dt>Coût matériaux</dt><dd>{Math.round(summary.materialsCost).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Frais de craft</dt><dd>{Math.round(summary.craftCost).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Coût total</dt><dd>{Math.round(summary.totalCost).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Vente brute</dt><dd>{Math.round(summary.grossRevenue).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Taxe marché</dt><dd>-{Math.round(summary.taxAmount).toLocaleString('fr-FR')}</dd></div>
            <div><dt>Vente nette</dt><dd>{Math.round(summary.netRevenue).toLocaleString('fr-FR')}</dd></div>
            <div className={summary.profit >= 0 ? 'profit-positive' : 'profit-negative'}>
              <dt>Profit</dt>
              <dd>{Math.round(summary.profit).toLocaleString('fr-FR')}</dd>
            </div>
            <div><dt>Marge nette</dt><dd>{summary.marginPct.toFixed(1)}%</dd></div>
          </dl>
        </section>
      </div>
    </div>
  );
}
