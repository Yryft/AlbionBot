# Web

Le dossier `web/` contient:
- `backend/`: API FastAPI du dashboard
- `dashboard/`: application Next.js

## API backend
Endpoints principaux:
- Auth/session utilisateur
- Raids (liste, roster, signup/leave)
- Bank/balances
- Tickets
- Permissions de guilde
- Crafting Assistant (`/api/craft/*`)
- Killboard (`/api/killboard/*`)

## Frontend
Le dashboard affiche des onglets:
- Dashboard
- Tous les raids
- Balances & Lootsplit
- Tous les tickets
- Crafting Assistant
- Killboard
- Administration (si admin)

## Variables utiles
- `BANK_DATABASE_URL` / `BANK_SQLITE_PATH`: persistance SQL
- `DASHBOARD_CORS_ORIGINS`: CORS dashboard
