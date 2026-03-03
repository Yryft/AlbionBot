from __future__ import annotations

import json
from types import SimpleNamespace

from albionbot.storage.store import Store
from albionbot.modules.tickets import TicketModule


def test_extract_message_content_falls_back_to_system_content() -> None:
    msg = SimpleNamespace(content="", system_content="Texte système")
    assert TicketModule._extract_message_content(msg) == "Texte système"


def test_store_loads_legacy_ticket_message_field(tmp_path) -> None:
    path = tmp_path / "state.json"
    raw = {
        "tickets": {
            "records": {
                "T1": {
                    "ticket_id": "T1",
                    "guild_id": 1,
                    "owner_user_id": 42,
                    "status": "open",
                    "created_at": 1,
                    "updated_at": 1,
                }
            },
            "messages": {
                "T1": [
                    {
                        "id": 999,
                        "author": 42,
                        "message": "Bonjour legacy",
                        "timestamp": 123,
                    }
                ]
            },
        }
    }
    path.write_text(json.dumps(raw), encoding="utf-8")

    store = Store(path=str(path), bank_database_url="", bank_sqlite_path=str(tmp_path / "bank.sqlite3"))
    snaps = store.ticket_get_transcript("T1")
    assert len(snaps) == 1
    assert snaps[0].content == "Bonjour legacy"
    assert snaps[0].message_id == 999
