# AlbionBot Web

Structure proposée:

- `web/backend`: API FastAPI dédiée dashboard.
- `web/dashboard`: Frontend Next.js (navigation style Discord).

## Principe de contrôle

- Le dashboard sert de **console de pilotage** du bot.
- Les actions faites depuis le dashboard (raids, compo, banque, tickets) doivent être considérées comme des commandes au bot Discord.
- Le bot recharge l'état partagé et applique ensuite les effets côté Discord (publication, édition, suppression, synchronisation des vues).

## Lancer en local

### 1) Backend

```bash
pip install -r requirements.txt
pip install -r web/backend/requirements.txt
uvicorn web.backend.app:app --host 0.0.0.0 --port 8000
```

Variables utiles backend:

- `DATA_PATH` (ex: `data/state.json`)
- `BANK_DATABASE_URL` ou `DATABASE_URL`
- `BANK_SQLITE_PATH`
- `DASHBOARD_CORS_ORIGINS` (CSV)
- `DISCORD_OAUTH_CLIENT_ID`
- `DISCORD_OAUTH_CLIENT_SECRET`
- `DISCORD_OAUTH_REDIRECT_URI`
- `DASHBOARD_COOKIE_SECURE` (`true` en prod)
- `DASHBOARD_COOKIE_SAMESITE` (`none` en prod cross-domain, `lax` en local)
- `DASHBOARD_POST_LOGIN_REDIRECT` (URL frontend après login)
- `DISCORD_TOKEN` (requis pour récupérer members/channels/roles Discord et autocomplétions dashboard)
  - Sert aussi de **fallback** pour lire les rôles du membre connecté si le scope OAuth `guilds.members.read` échoue côté token utilisateur.

### 2) Frontend

```bash
cd web/dashboard
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

## Déploiement Railway (services séparés)

Créer **2 services** dans le même projet Railway.

### Service 1: bot Discord

- Build: `pip install -r requirements.txt && pip install .`
- Start: `python -m albionbot`
- Variables: `DISCORD_TOKEN`, `GUILD_IDS`, `DATA_PATH`, `BANK_DATABASE_URL`...

### Service 2: dashboard backend (FastAPI)

- Build: `pip install -r requirements.txt && pip install -r web/backend/requirements.txt && pip install .`
- Start: `uvicorn web.backend.app:app --host 0.0.0.0 --port $PORT`
- Variables: `DATA_PATH`, `BANK_DATABASE_URL` (optionnel), `DASHBOARD_CORS_ORIGINS`

### Service 3 (optionnel mais recommandé): dashboard frontend Next

- Root directory: `web/dashboard`
- Build: `npm install && npm run build`
- Start: `npm run start`
- Variables: `NEXT_PUBLIC_API_BASE_URL=https://<service-backend>.up.railway.app`

> Le bot et le dashboard ont des variables d'environnement distinctes. Partager uniquement l'accès lecture/écriture aux données (`DATA_PATH` volume ou DB commune) selon votre architecture.

> Le bot recharge l'état partagé périodiquement (5s) afin d'appliquer dans Discord les actions faites depuis le dashboard (raids publiés/édités/supprimés, état banque et tickets rafraîchi).

## Dépannage: `OAuth Discord non configuré`

Si le dashboard affiche cette erreur, configure les variables côté **backend FastAPI** (pas sur le bot) :

```bash
export DISCORD_OAUTH_CLIENT_ID=...
export DISCORD_OAUTH_CLIENT_SECRET=...
export DISCORD_OAUTH_REDIRECT_URI=http://localhost:8000/auth/discord/callback
```

Ensuite, dans le portail Discord Developer:

1. Crée une application puis un lien OAuth2.
2. Dans **OAuth2 > Redirects**, ajoute exactement la valeur de `DISCORD_OAUTH_REDIRECT_URI`.
3. Active les scopes `identify`, `guilds`, `guilds.members.read`.
4. Redémarre l'API backend.

En local, pense aussi à démarrer le frontend avec `NEXT_PUBLIC_API_BASE_URL` qui pointe vers le backend.


## Nouveautés dashboard

- Bouton **Déconnexion** côté interface.
- Suppression définitive des raids et des logs de tickets.
- Endpoint `GET /api/guilds/{guild_id}/discord-directory` pour alimenter les autocomplétions (channels text/voice + membres).
- Affichage des balances avec pseudo Discord quand disponible.
- **Preview temps réel** pour le raid opener et les templates avant publication.
- **Builder personnalisable** (menus + cases à cocher) pour réordonner/activer/supprimer des sections de message.
- **Onglet séparé Balances & Lootsplit** avec un simulateur de split de raid puis application directe en banque (`add_split`).
- Cache de permissions/roles membre côté backend dashboard pour éviter de re-fetch Discord à chaque commande.
- Normalisation des IDs raid (`channel_id`/`message_id`) pour fiabiliser la publication Discord des raids en attente.
- Leaderboard balances aligné avec Discord + actions rapides `/bank_add` et `/bank_remove` depuis le dashboard.
- Correction transcript tickets: conservation du contenu réel des messages (y compris fallback `system_content`) et lecture des anciens snapshots legacy.
