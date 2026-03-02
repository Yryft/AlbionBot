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

### Obligatoire
- `DISCORD_TOKEN`

### Recommandées
- `GUILD_IDS` (IDs serveur séparés par virgules)
- `BANK_DATABASE_URL` (PostgreSQL)
- `DATABASE_URL` (fallback Railway)

### Optionnelles
- `DATA_PATH` (défaut: `data/state.json`)
- `BANK_SQLITE_PATH` (défaut: `data/bank.sqlite3`)
- `RAID_REQUIRE_MANAGE_GUILD` (défaut: `true`)
- `RAID_MANAGER_ROLE_ID`
- `BANK_REQUIRE_MANAGE_GUILD` (défaut: `true`)
- `BANK_MANAGER_ROLE_ID`
- `SUPPORT_ROLE_ID` *(compat legacy ticket manager)*
- `TICKET_ADMIN_ROLE_ID` *(compat legacy ticket manager)*
- `BANK_ALLOW_NEGATIVE` (défaut: `true`)
- `SCHED_TICK_SECONDS` (défaut: `15`)
- `DEFAULT_PREP_MINUTES` (défaut: `10`)
- `DEFAULT_CLEANUP_MINUTES` (défaut: `30`)
- `VOICE_CHECK_AFTER_MINUTES` (défaut: `5`)

---


## Dashboard web (FastAPI + Next.js)

Un service web séparé est disponible sous `web/`:
- Backend API: `web/backend` (transcripts tickets, comps/raids, actions managées).
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
