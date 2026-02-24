# Albion Discord Bot (Raids + Bank)

Nextcord-based Discord bot for Albion Online guild organization.

## Features

### Raid module
- Flexible **composition templates** created/edited in a **DM wizard**
- Templates support **unlimited roles** (with slots), per-role **IP requirement**, per-role required Discord roles, and required Discord roles to join the raid.
- `/raid_open` posts a **dynamic embed** + signup UI (select menus + buttons) and auto-creates a **thread**.
- **Waitlist**: users can still sign up when a role is full.
- **Signups close at mass-up** (raid start time). After mass-up, nobody can join or receive the temp role.
- **Temporary role**:
  - Assigned at T-`prep_minutes`
  - Grants access to an existing **private voice channel** via permission overwrites
  - Pinged at mass-up time, then removed and deleted during cleanup
- **Voice attendance report** (T+5):
  - present & expected
  - present but unexpected
  - expected but missing
  - sent to RL via DM (fallback to thread then channel)

### Bank module
- Per-member balances
- Privileged add/remove:
  - single member, by role(s), by mentions list
  - split total across targets
- Undo last action (per manager) within 15 minutes
- Stored in SQL (PostgreSQL on Railway via DATABASE_URL, SQLite fallback). Legacy JSON is auto-migrated on first run.

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m albionbot
```

> If DM wizard doesn't capture messages, enable **Message Content Intent** in the Discord Developer Portal and uncomment `intents.message_content = True` in `src/albionbot/main.py`.

---

## Required Discord permissions for the bot

Recommended:
- Manage Roles (create/assign/delete temp role)
- Manage Channels (set voice overwrites, create threads)
- Create Public Threads
- Send Messages, Embed Links, Read Message History

The bot role must be **above** the temp role it creates.

---

## Commands

### Raid
- `/comp_wizard` — create a template via DM wizard
- `/comp_edit` — edit template via DM wizard (autocomplete)
- `/comp_delete` — delete template (autocomplete)
- `/comp_list` — list templates
- `/raid_open` — open a raid (template autocomplete)
- `/raid_list` — list raids
- `/raid_close` — close a raid immediately

### Bank
- `/bal` — view your balance (or another user if authorized)
- `/bank_add` — add to targets
- `/bank_remove` — remove from targets
- `/bank_add_split` — split total add across targets
- `/bank_remove_split` — split total remove across targets
- `/bank_undo` — undo your last bank action (15 min)

---

## License
MIT (see `LICENSE`)
