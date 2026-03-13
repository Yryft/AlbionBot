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
- Crafting Assistant dashboard + endpoint `/crafting/item/{id}`

## Frontend
Le dashboard affiche des onglets:
- Dashboard
- Tous les raids
- Balances & Lootsplit
- Tous les tickets
- Administration (si admin)

## Données crafting offline
`web/backend/data/crafting/` contient les index utilisés pour éviter de spammer GameInfo (catalogue et multi-recettes), les coefficients focus et les modifiers de return rate.
