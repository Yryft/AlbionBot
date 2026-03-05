from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from albionbot.storage.store import Store


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Importe/maj les base_focus_cost par item_id.")
    parser.add_argument("--input", required=True, help="Chemin CSV ou JSON")
    parser.add_argument("--data-path", default="data/state.json", help="Chemin state.json")
    parser.add_argument("--bank-sqlite-path", default="data/bank.sqlite3", help="Chemin SQLite backend")
    parser.add_argument("--source", default="manual_script", help="Source enregistrée en DB")
    return parser.parse_args()


def _load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("entries", [])
        if not isinstance(payload, list):
            raise ValueError("Le JSON doit contenir une liste ou {'entries': [...]}.")
        return [dict(row) for row in payload if isinstance(row, dict)]

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    raise ValueError("Format non supporté: utilisez .csv ou .json")


def main() -> None:
    args = _parse_args()
    rows = _load_rows(Path(args.input))
    store = Store(path=args.data_path, bank_sqlite_path=args.bank_sqlite_path)

    updated = 0
    for row in rows:
        item_id = str(row.get("item_id", "")).strip()
        if not item_id:
            continue
        focus_cost = int(row.get("base_focus_cost"))
        tier = row.get("tier")
        enchant = row.get("enchant")
        store.craft_upsert_focus_cost(
            item_id=item_id,
            base_focus_cost=focus_cost,
            tier=(int(tier) if tier not in (None, "") else None),
            enchant=(int(enchant) if enchant not in (None, "") else None),
            source=str(row.get("source") or args.source),
        )
        updated += 1

    print(f"Focus costs upsertés: {updated}")


if __name__ == "__main__":
    main()
