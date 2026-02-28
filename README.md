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


## Deploy on Railway

> Important: on Railway filesystem is ephemeral. With `DATABASE_URL` configured, **bank + templates + raids** are persisted in SQL.

1. Push this repo to GitHub and create a new **Railway Project** from that repo.
2. In Railway service settings:
   - **Build command**: `pip install -r requirements.txt && pip install .`
   - **Start command**: `python -m albionbot`
3. Add environment variables in Railway (**Variables** tab).
4. Redeploy.

### Required variables
- `DISCORD_TOKEN` (required)

### Recommended variables
> Tip commandes: définis `GUILD_IDS` pour enregistrer les slash commands en scope serveur (mise à jour quasi immédiate). Sans `GUILD_IDS`, les commandes globales peuvent prendre du temps à se propager.

- `GUILD_IDS` (comma-separated guild IDs, e.g. `123456789012345678,987654321098765432`)
- `BANK_DATABASE_URL` (PostgreSQL URL). If empty, the bot falls back to `DATABASE_URL`.
- `DATABASE_URL` (auto-provided by Railway when a PostgreSQL plugin is attached)

### Optional variables (with defaults)
- `DATA_PATH` = `data/state.json`
- `BANK_SQLITE_PATH` = `data/bank.sqlite3`
- `RAID_REQUIRE_MANAGE_GUILD` = `true`
- `RAID_MANAGER_ROLE_ID` = *(empty)*
- `BANK_REQUIRE_MANAGE_GUILD` = `true`
- `BANK_MANAGER_ROLE_ID` = *(empty)*
- `BANK_ALLOW_NEGATIVE` = `true`
- `SCHED_TICK_SECONDS` = `15`
- `DEFAULT_PREP_MINUTES` = `10`
- `DEFAULT_CLEANUP_MINUTES` = `30`
- `VOICE_CHECK_AFTER_MINUTES` = `5`

> Yes: on Railway you must set at least `DISCORD_TOKEN`. For persistence, also connect PostgreSQL and use `BANK_DATABASE_URL` (or Railway's `DATABASE_URL`).

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
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
- `/raid_open` — open a raid (template + start, then modal details + confirm)
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
