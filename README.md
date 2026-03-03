# AlbionBot (Discord) — Raids, Banque, Tickets

Bot Discord basé sur **Nextcord** pour la gestion de guilde Albion Online.

## Ce qui a été fiabilisé
- Permissions manager unifiées via clés explicites (`raid_manager`, `bank_manager`, `ticket_manager`).
- Commande `/help` réalignée sur les commandes réellement présentes dans le code.
- Suivi ticket stabilisé (snapshots messages/edits/deletes + fermeture automatique selon événements).
- Structure `main.py` simplifiée (génération d'aide isolée, variables cohérentes, moins de duplication).

---

## Fonctionnalités

### 1) Raids
- Templates de composition (wizard DM, édition, suppression, listing).
- Ouverture de raid depuis template avec UI interactive.
- Gestion des inscriptions/absents/waitlist.
- Outils manager raid : édition, fermeture, listing, split loot.
- Dashboard web: aperçu temps réel raid/template, builder de sections (ordre + activation), onglet dédié balances/lootsplit avec simulateur de split raid.
- Backend dashboard: cache temporaire des permissions/roles membres Discord (moins d’appels API sur commandes répétées), plus robustesse publication raid (IDs normalisés), leaderboard balances + actions add/remove depuis le dashboard.
- Sécurité dashboard: toutes les routes backend mutantes (`POST`/`PUT`/`DELETE`) exigent un header `X-CSRF-Token` valide avant les contrôles métier.
- Permission dashboard: `POST /api/actions/bank/apply` exige la clé métier `bank_manage` (permission logique `bank_manager`).
- Tickets: correction de la sauvegarde/lecture de transcript pour conserver le vrai contenu message (fallback `system_content` + compatibilité ancien format de snapshots).

Commandes principales :
- `/comp_wizard`, `/comp_edit`, `/comp_delete`, `/comp_list`
- `/raid_open`, `/raid_edit`, `/raid_list`, `/raid_close`, `/raid_assistant`
- `/loot_scout_limits`, `/loot_split`

### 2) Banque
- Balance par membre.
- Ajout/retrait sur cibles multiples.
- Répartition d'un total (`*_split`).
- Undo de la dernière action manager.
- Paiement joueur à joueur (`/pay`).

Commandes principales :
- `/bal`, `/pay`, `/bank_assistant`
- `/bank_add`, `/bank_remove`, `/bank_add_split`, `/bank_remove_split`, `/bank_undo`

### 3) Tickets (multi-types + traçabilité)
- Panneau admin/manager pour publier un message d'ouverture de ticket.
- Types de tickets flexibles par serveur (recrutement, aide, customs...).
- Permissions support configurables par type (rôles différents selon le type).
- Fermeture simple pour l'auteur ou le support, avec confirmation obligatoire et **raison optionnelle**.
- Historique technique des messages (création/édition/suppression) pour les tickets connus.
- Logging des tickets configurable sur un salon dédié (embed + fichier transcript).

Commandes principales :
- `/ticket_panel_send`
- `/ticket_open`, `/ticket_close [reason]`
- `/ticket_type_set`, `/ticket_type_remove`
- `/ticket_config_mode`
- `/ticket_config_category`
- `/ticket_config_roles`
- `/ticket_config_open_style`
- `/ticket_config_logs`
- `/ticket_log_send`

### 4) Permissions bot
- Configuration par serveur des rôles autorisés par permission logique.
- Assistant modal admin.

Commandes principales :
- `/permissions_set`
- `/permissions_assistant`

---

## Installation locale

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
python -m albionbot
```

> Si le wizard DM ne lit pas les messages : active **Message Content Intent** dans le portail Discord puis décommente `intents.message_content = True` dans `src/albionbot/main.py`.

---

## Variables d'environnement

### 1) Bot Discord (`python -m albionbot`)

| Variable | Obligatoire | Valeur attendue | Exemple concret |
|---|---:|---|---|
| `DISCORD_TOKEN` | ✅ | Token du bot (Discord Developer Portal > Bot) | `<SECRET>` |
| `GUILD_IDS` | recommandé | IDs Discord (entiers) séparés par virgules | `123456789012345678,987654321098765432` |
| `DATA_PATH` | recommandé | Chemin du fichier JSON d'état | `/data/state.json` |
| `BANK_DATABASE_URL` | recommandé* | URL PostgreSQL pour la banque (prioritaire) | `postgresql://user:pass@host:5432/dbname` |
| `DATABASE_URL` | fallback | URL PostgreSQL fallback si `BANK_DATABASE_URL` absent | `postgresql://user:pass@host:5432/dbname` |
| `BANK_SQLITE_PATH` | optionnel | Chemin SQLite si tu n'utilises pas PostgreSQL | `/data/bank.sqlite3` |
| `RAID_REQUIRE_MANAGE_GUILD` | optionnel | `true`/`false` (contrôle permission Discord Manage Guild) | `true` |
| `RAID_MANAGER_ROLE_ID` | optionnel | ID rôle manager raids | `123456789012345678` |
| `BANK_REQUIRE_MANAGE_GUILD` | optionnel | `true`/`false` (contrôle permission Discord Manage Guild) | `true` |
| `BANK_MANAGER_ROLE_ID` | optionnel | ID rôle manager banque | `123456789012345678` |
| `SUPPORT_ROLE_ID` | optionnel | ID rôle support (compat legacy tickets) | `123456789012345678` |
| `TICKET_ADMIN_ROLE_ID` | optionnel | ID rôle admin tickets (compat legacy) | `123456789012345678` |
| `BANK_ALLOW_NEGATIVE` | optionnel | `true`/`false` autorise soldes négatifs | `true` |
| `SCHED_TICK_SECONDS` | optionnel | Fréquence scheduler (secondes) | `15` |
| `DEFAULT_PREP_MINUTES` | optionnel | Préparation raid par défaut (minutes) | `10` |
| `DEFAULT_CLEANUP_MINUTES` | optionnel | Nettoyage raid par défaut (minutes) | `30` |
| `VOICE_CHECK_AFTER_MINUTES` | optionnel | Délai check vocal auto (minutes) | `5` |

\* Si tu veux PostgreSQL, renseigne au moins une de ces deux variables (`BANK_DATABASE_URL` ou `DATABASE_URL`).

### 2) Backend dashboard (`web/backend`)

| Variable | Obligatoire | Valeur attendue | Exemple concret |
|---|---:|---|---|
| `DATA_PATH` | ✅ (si JSON partagé) | Même chemin que le bot (si volume partagé) | `/data/state.json` |
| `BANK_DATABASE_URL` | recommandé | URL PostgreSQL (prioritaire) | `postgresql://user:pass@host:5432/dbname` |
| `DATABASE_URL` | fallback | URL PostgreSQL fallback | `postgresql://user:pass@host:5432/dbname` |
| `BANK_SQLITE_PATH` | optionnel | Chemin SQLite | `/data/bank.sqlite3` |
| `DASHBOARD_CORS_ORIGINS` | ✅ | Liste d'origines frontend séparées par virgules | `https://frontend.up.railway.app` |
| `DISCORD_OAUTH_CLIENT_ID` | ✅ (OAuth) | Client ID de l'application Discord | `123456789012345678` |
| `DISCORD_OAUTH_CLIENT_SECRET` | ✅ (OAuth) | Client Secret Discord OAuth2 | `<SECRET>` |
| `DISCORD_OAUTH_REDIRECT_URI` | ✅ (OAuth) | Callback backend exacte | `https://backend.up.railway.app/auth/discord/callback` |
| `DISCORD_TOKEN` | ✅ | Token bot utilisé pour lire channels/membres/rôles Discord (autocomplétions dashboard) | `<SECRET>` |
| `DASHBOARD_COOKIE_SECURE` | recommandé | `true` en prod HTTPS, `false` en local HTTP | `true` |
| `DASHBOARD_POST_LOGIN_REDIRECT` | recommandé | URL frontend de retour après login | `https://frontend.up.railway.app/` |

### 3) Frontend dashboard (`web/dashboard`)

| Variable | Obligatoire | Valeur attendue | Exemple concret |
|---|---:|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | ✅ | URL publique du backend FastAPI | `https://backend.up.railway.app` |

---


## Dashboard web (FastAPI + Next.js)

Un service web séparé est disponible sous `web/`:
- Backend API: `web/backend` (transcripts tickets, comps/raids, actions managées).
- Synchronisation automatique bot ⇄ dashboard: le bot recharge l'état partagé toutes les 5 secondes et répercute les actions dashboard vers Discord (publication/mise à jour/suppression des messages raids, données banque/tickets rechargées côté bot).
- Publication des raids dashboard via outbox/queue persistante: chaque ouverture crée une commande `pending`, traitée ensuite par le bot avec retry/backoff et statut exposé à l'API (`publish_status`, `publish_error`).
- Le dashboard agit comme une interface de contrôle du bot: les actions de gestion sont réalisées via les flux du bot Discord (et non comme un back-office séparé de Discord).
- Frontend: `web/dashboard` (navigation type Discord).
- Contrat API: `web/API_CONTRACT.md`.
- Déploiement Railway multi-services: `web/README.md`.

## Déploiement Railway
1. Push sur GitHub.
2. Créer un projet Railway depuis le repo.
3. Build command:
   - `pip install -r requirements.txt && pip install .`
4. Start command:
   - `python -m albionbot`
5. Ajouter les variables d'environnement puis redéployer.

### Guide Railway complet (pas à pas)

Si tu veux une config propre et stable, fais cette version:

1) **Prépare ton bot Discord**
   - Va sur [Discord Developer Portal](https://discord.com/developers/applications).
   - Active les intents nécessaires dans **Bot > Privileged Gateway Intents** (au minimum ceux utilisés dans ton serveur; `MESSAGE CONTENT` si tu utilises les lectures de messages en DM/wizard).
   - Récupère le token et garde-le pour `DISCORD_TOKEN`.

2) **Crée le projet Railway**
   - `New Project` → `Deploy from GitHub repo` → sélectionne ce dépôt.
   - Railway crée un service, renomme-le en `albionbot` (optionnel, mais plus clair).

3) **Configure le service bot**
   - **Build Command**:
     - `pip install -r requirements.txt && pip install .`
   - **Start Command**:
     - `python -m albionbot`
   - **Variables minimales**:
     - `DISCORD_TOKEN=<token bot>`
   - **Variables recommandées**:
     - `GUILD_IDS=<id1,id2>`
     - `DATABASE_URL` ou `BANK_DATABASE_URL` (si PostgreSQL)
     - `DATA_PATH=/data/state.json`

4) **Ajoute un volume (fortement recommandé)**
   - Sans volume, les fichiers locaux sont éphémères après redéploiement/restart.
   - Dans Railway: `Service > Volumes` → monte un volume sur `/data`.
   - Utilise:
     - `DATA_PATH=/data/state.json`
     - `BANK_SQLITE_PATH=/data/bank.sqlite3` (si tu restes en SQLite)

5) **(Optionnel) Ajoute PostgreSQL Railway**
   - `New > Database > PostgreSQL`.
   - Dans le service bot, mappe la variable `DATABASE_URL` (ou `BANK_DATABASE_URL`) sur l'URL PostgreSQL fournie.
   - Avantage: persistance plus robuste et partage possible avec le backend web.

6) **Redéploie et vérifie les logs**
   - Clique `Deploy`.
   - Vérifie les logs du service:
     - Le bot doit se connecter sans erreur de token.
     - Pas d'erreur de permissions Discord côté salon/commande.

7) **Checklist de debug rapide**
   - `Invalid token` → mauvais `DISCORD_TOKEN`.
   - Commandes slash absentes → `GUILD_IDS` incorrect ou propagation Discord pas terminée.
   - Données qui disparaissent → volume absent ou mauvais chemin (`DATA_PATH`/`BANK_SQLITE_PATH`).
   - Erreur DB → `DATABASE_URL`/`BANK_DATABASE_URL` non défini ou inaccessible.

### Déployer aussi le dashboard web (optionnel)

Voir `web/README.md` pour le détail complet. En résumé:
- Service bot Discord.
- Service backend FastAPI.
- Service frontend Next.js.

Les 3 services doivent avoir des variables cohérentes (URL backend, CORS, OAuth Discord, stockage partagé DB/volume).

### Mini tuto OAuth Discord (dashboard)

> Objectif : permettre le login Discord sur le dashboard via `/auth/discord/login`.

1) **Créer (ou ouvrir) l'application Discord**
   - Ouvre <https://discord.com/developers/applications>.
   - Crée une application (ou réutilise celle du bot).
   - Dans **OAuth2 > General**, copie:
     - `CLIENT ID` → `DISCORD_OAUTH_CLIENT_ID`
     - `CLIENT SECRET` → `DISCORD_OAUTH_CLIENT_SECRET`

2) **Déclarer la Redirect URL exacte**
   - Toujours dans **OAuth2 > General > Redirects**, ajoute :
     - `https://<ton-backend>/auth/discord/callback`
   - Exemple Railway:
     - `https://backend-production-xxxx.up.railway.app/auth/discord/callback`
   - Cette valeur doit être **strictement la même** que `DISCORD_OAUTH_REDIRECT_URI` côté backend.

3) **Configurer les variables backend**
   - `DISCORD_OAUTH_CLIENT_ID=<CLIENT_ID>`
   - `DISCORD_OAUTH_CLIENT_SECRET=<CLIENT_SECRET>`
   - `DISCORD_OAUTH_REDIRECT_URI=https://<ton-backend>/auth/discord/callback`
   - `DASHBOARD_POST_LOGIN_REDIRECT=https://<ton-frontend>/`
   - `DASHBOARD_COOKIE_SECURE=true` (prod HTTPS)

4) **Configurer le frontend**
   - `NEXT_PUBLIC_API_BASE_URL=https://<ton-backend>`
   - Le bouton/login frontend doit pointer vers `https://<ton-backend>/auth/discord/login`.

5) **Tester le flux OAuth**
   - Va sur le frontend, clique “Login Discord”.
   - Tu dois être redirigé vers Discord, puis revenir sur le frontend avec `?logged_in=1`.
   - Vérifie aussi l'endpoint `GET /me` (doit retourner l'utilisateur connecté).

6) **Erreurs fréquentes**
   - `OAuth Discord non configuré` → une variable `DISCORD_OAUTH_*` manque côté backend.
   - `State OAuth invalide` → cookie/state perdu (souvent domaine/protocole/cookies secure incohérents).
   - Redirect mismatch Discord → URL de callback non identique entre Discord Developer Portal et `DISCORD_OAUTH_REDIRECT_URI`.

### Railway — quoi mettre dans chaque variable (copier/coller)

Voici une matrice pratique par service.

#### 1) Service `albionbot` (bot Discord)

| Variable | Obligatoire | Valeur à mettre | Exemple |
|---|---:|---|---|
| `DISCORD_TOKEN` | ✅ | Token du bot Discord (Developer Portal > Bot) | `<SECRET>` |
| `GUILD_IDS` | recommandé | IDs de serveurs séparés par virgules | `123456789012345678,987654321098765432` |
| `DATA_PATH` | recommandé | Chemin du fichier d'état dans le volume | `/data/state.json` |
| `BANK_DATABASE_URL` | recommandé* | URL PostgreSQL pour la banque (prioritaire sur `DATABASE_URL`) | `postgresql://user:pass@host:5432/db` |
| `DATABASE_URL` | recommandé* | URL PostgreSQL fallback si `BANK_DATABASE_URL` absent | `postgresql://user:pass@host:5432/db` |
| `BANK_SQLITE_PATH` | optionnel | Chemin SQLite si pas de PostgreSQL | `/data/bank.sqlite3` |

\* Utilise **au moins une** des deux (`BANK_DATABASE_URL` ou `DATABASE_URL`) si tu veux PostgreSQL.

#### 2) Service `backend` (FastAPI dashboard)

| Variable | Obligatoire | Valeur à mettre | Exemple |
|---|---:|---|---|
| `DATA_PATH` | ✅ (si lecture JSON) | Même chemin que le bot si partagé via volume | `/data/state.json` |
| `BANK_DATABASE_URL` | recommandé | URL PostgreSQL (ou `DATABASE_URL`) | `postgresql://user:pass@host:5432/db` |
| `DATABASE_URL` | fallback | Utilisé si `BANK_DATABASE_URL` absent | `postgresql://user:pass@host:5432/db` |
| `BANK_SQLITE_PATH` | optionnel | Si mode SQLite | `/data/bank.sqlite3` |
| `DASHBOARD_CORS_ORIGINS` | ✅ | URL(s) frontend autorisées, séparées par virgules | `https://frontend.up.railway.app` |
| `DISCORD_OAUTH_CLIENT_ID` | ✅ (si login Discord) | Client ID OAuth2 Discord | `123456789012345678` |
| `DISCORD_OAUTH_CLIENT_SECRET` | ✅ (si login Discord) | Secret OAuth2 Discord | `<SECRET>` |
| `DISCORD_OAUTH_REDIRECT_URI` | ✅ (si login Discord) | Callback backend `/auth/discord/callback` | `https://backend.up.railway.app/auth/discord/callback` |
| `DASHBOARD_COOKIE_SECURE` | ✅ en prod | `true` en HTTPS Railway | `true` |
| `DASHBOARD_POST_LOGIN_REDIRECT` | recommandé | URL frontend après login | `https://frontend.up.railway.app/` |

#### 3) Service `frontend` (Next.js dashboard)

| Variable | Obligatoire | Valeur à mettre | Exemple |
|---|---:|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | ✅ | URL publique du backend FastAPI | `https://backend.up.railway.app` |

#### 4) Mapping rapide “qui utilise quoi”

- **Bot seulement**: `DISCORD_TOKEN`, `GUILD_IDS`, `RAID_*`, `BANK_*` (runtime bot), `TICKET_*`.
- **Backend seulement**: `DASHBOARD_*`, `DISCORD_OAUTH_*`, `DASHBOARD_CORS_ORIGINS`.
- **Partagé bot + backend**: `DATA_PATH`, `BANK_DATABASE_URL` / `DATABASE_URL`, `BANK_SQLITE_PATH`.
- **Frontend seulement**: `NEXT_PUBLIC_API_BASE_URL`.

#### 5) Ordre recommandé sur Railway

1. Créer/brancher PostgreSQL (option recommandé) puis copier son URL dans `BANK_DATABASE_URL`.
2. Créer un volume `/data` pour le bot (et backend si partage fichiers).
3. Configurer les variables du bot, déployer, vérifier que le bot se connecte.
4. Configurer backend + OAuth Discord, vérifier `/health`.
5. Configurer frontend avec `NEXT_PUBLIC_API_BASE_URL` vers le backend.

---

## Licence
MIT (`LICENSE`)
