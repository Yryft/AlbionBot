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
- Dashboard web: onglet Banque aligné commandes bot (`/bank_add`, `/bank_remove`, `/bank_add_split`, `/bank_remove_split`, `/bank_undo`, `/pay`, `/bal`) et gestion templates alignée sur le modèle bot (`content_type`, `raid_required_role_ids`, spec complète).
- Dashboard web: validation form-level côté UI avant appels API (`apiPost`/`apiPut`) avec contrôles montants/IP/date future/sélections requises, messages d'erreurs contextuels par champ et submit désactivé tant que les préconditions minimales ne sont pas remplies.
- Backend dashboard: cache temporaire des permissions/roles membres Discord (moins d’appels API sur commandes répétées), suivi robuste de publication raid via `publish_status`/`publish_error`, leaderboard balances + actions manager, transfert `/pay`, consultation ciblée `/bal`, historique d'actions et undo.
- Convention API dashboard: tous les IDs Discord (`guild_id`, `user_id`, `message_id`, `role_id`, `channel_id`) sont exposés en **string** côté HTTP/JSON, avec conversion explicite en interne backend.
- Sécurité dashboard: toutes les routes backend mutantes (`POST`/`PUT`/`DELETE`) exigent un header `X-CSRF-Token` valide avant les contrôles métier.
- Permission dashboard: `POST /api/actions/bank/apply` et `POST /api/actions/bank/undo` exigent la clé métier `bank_manage` (permission logique `bank_manager`), alors que `POST /api/actions/bank/pay` est disponible à tout membre de guilde.
- Cleanup admin dashboard: suppression directe des éléments persistés (raids, templates, logs tickets et entrées banque individuelles) pour corriger les données orphelines/mauvaises entrées sans manipuler la DB à la main.
- Règle de solde négatif dashboard alignée bot: validations manager banque basées sur `BANK_ALLOW_NEGATIVE` (équivalent de `cfg.bank_allow_negative`).
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
| `DASHBOARD_COOKIE_SECURE` | recommandé | `true` en prod HTTPS, `false` en local HTTP (ou auto via proto requête) | `true` |
| `DASHBOARD_POST_LOGIN_REDIRECT` | recommandé | URL frontend de retour après login | `https://frontend.up.railway.app/` |

### 3) Frontend dashboard (`web/dashboard`)

| Variable | Obligatoire | Valeur attendue | Exemple concret |
|---|---:|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | ✅ | URL publique du backend FastAPI | `https://backend.up.railway.app` |

---


## Dashboard web (FastAPI + Next.js)

Un service web séparé est disponible sous `web/`:
- Backend API: `web/backend` (transcripts tickets, comps/raids, actions managées).
- Synchronisation automatique bot ⇄ dashboard: le bot recharge l'état partagé toutes les 5 secondes et répercute les actions dashboard vers Discord (publication/mise à jour/fermeture des raids et rafraîchissement des messages, données banque/tickets rechargées côté bot). Le backend FastAPI recharge aussi cet état au début de chaque requête pour éviter les statuts de publication obsolètes et les écrasements inter-processus.
- Résilience PostgreSQL (Railway): reconnexion automatique sur erreur réseau/SSL transitoire (ex. `unexpected eof while reading`) pendant les lectures/écritures banque + état partagé, afin d'éviter les erreurs ASGI lors du refresh d'état.
- Publication des raids dashboard via outbox/queue persistante: chaque ouverture crée une commande `pending`, traitée ensuite par le bot avec retry/backoff et statut exposé à l'API (`publish_status`, `publish_error`).
- Pour les templates `ava_raid`, la publication (commande bot ou queue dashboard) pré-inscrit automatiquement le créateur en `raid_leader` (`main`) si ce rôle existe dans la composition.
- Le dashboard agit comme une interface de contrôle du bot: les actions de gestion sont réalisées via les flux du bot Discord (et non comme un back-office séparé de Discord).
- Périmètre raids dashboard aligné sur les commandes bot de référence: ouverture (`raid_open`), édition (`raid_edit`), fermeture explicite (`raid_close`) et gestion roster (inscription/retrait).
- Frontend: `web/dashboard` (navigation type Discord).
- Dashboard: prévisualisation du message raid dans le formulaire avant confirmation, alignée sur le rendu bot exact (embed + composants interactifs).
- Dashboard: écran non connecté simplifié avec présentation du bot et un bouton unique de connexion Discord.
- Dashboard: panneau admin serveur pour gérer les permissions bot (`raid_manager`, `bank_manager`, `ticket_manager`) par rôles et membres (IDs Discord), désormais isolé dans un onglet dédié **Administration**.
- Dashboard: nouvel onglet **Craft calculator** pour estimer les matériaux consommés (bonus ville/HO), ajuster les prix unitaires et projeter le profit net après taxe marché.
- Dashboard craft: ajout du mode prix `manuel/prérempli`, saisie du livre d'imbuer et endpoint backend de simulation rentabilité avec breakdown ligne par ligne (matériaux, focus, revenus, profit, marge).
- Dashboard: écran non connecté corrigé pour utiliser toute la largeur (suppression de l'effet de colonne latérale vide).
- Accessibilité UI du dashboard renforcée: styles `:focus-visible` explicites sur boutons/liens/champs/listes (`outline` + `offset`), contraste amélioré des états actifs/hover (`tabs`, `rows`, boutons secondaires), états `:disabled` plus lisibles, et boutons de sélection de guilde annotés pour lecteurs d’écran (`aria-label`, `aria-pressed`).
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
   - Erreur `psycopg.OperationalError: ... SSL error: unexpected eof while reading` → généralement connexion PostgreSQL idle coupée par le provider; la version actuelle retente automatiquement avec reconnexion, sinon vérifier la stabilité réseau DB.

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
   - `DASHBOARD_COOKIE_SECURE=true` (prod HTTPS, optionnel en auto)
   - En auto, le backend adapte Secure/SameSite selon le protocole de la requête (HTTP local => cookies compatibles).

4) **Configurer le frontend**
   - `NEXT_PUBLIC_API_BASE_URL=https://<ton-backend>`
   - Le bouton/login frontend doit pointer vers `https://<ton-backend>/auth/discord/login`.

5) **Tester le flux OAuth**
   - Va sur le frontend, clique “Login Discord”.
   - Tu dois être redirigé vers Discord, puis revenir sur le frontend avec `?logged_in=1`.
   - Vérifie aussi l'endpoint `GET /me` (doit retourner l'utilisateur connecté).
   - Si la session/cookies existent déjà sur la même machine (IP + user-agent), `/auth/discord/login` propose une reprise et évite un nouveau passage OAuth (`?resumed=1`).
   - Si tu veux forcer une vraie redirection OAuth (ex: reprise bloquée), utilise `https://<ton-backend>/auth/discord/login?force=1`.

Session dashboard:
- persistance disque des sessions (`DASHBOARD_SESSIONS_PATH`, défaut `data/dashboard_sessions.json`),
- expiration glissante (tant que l'utilisateur reste actif, la session est prolongée),
- session détruite à la déconnexion (`POST /auth/logout`) ou à expiration TTL.

6) **Erreurs fréquentes**
   - `OAuth Discord non configuré` → une variable `DISCORD_OAUTH_*` manque côté backend.
   - `State OAuth invalide` → cookie/state perdu (souvent domaine/protocole/cookies secure incohérents).
   - `Configuration cookies invalide` → `DASHBOARD_COOKIE_SAMESITE=none` impose `DASHBOARD_COOKIE_SECURE=true`.
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


### Spec template compatible parse_comp_spec

Format attendu: `Label;slots;options`.

Exemple:

```text
Tank;2;key=tank
Healer;2;ip=true
DPS Melee;4;req=123456789012345678
Support;2;roles=234567890123456789,345678901234567890
```

- Erreurs bloquantes (spec vide, slots invalides, ligne mal formée) retournées par le backend dashboard avec détail.
- Warnings non bloquants (options inconnues ignorées) retournés dans la réponse de création/édition (`spec_warnings`).
- Normalisation automatique dashboard pour `content_type=ava_raid` (création/édition): les variantes/doublons de `raid_leader` et `scout` sont supprimés puis remplacés par la structure canonique bot (`raid_leader` forcé: `slots=1`, `ip_required=false`, `required_role_ids=[]`; `scout` forcé: `slots=1`, `ip_required=false`, `required_role_ids` repris depuis la première entrée scout fournie).

### Variables cache/provider Albion (backend dashboard)

Le backend dashboard expose désormais des endpoints de lecture craft (`/api/craft/items`, `/api/craft/items/{item_id}`) alimentés par un provider Albion avec cache multi-niveaux.

| Variable | Obligatoire | Rôle |
|---|---:|---|
| `ALBION_PROVIDER_URL` | optionnel | Endpoint JSON du provider Albion (catalogue + recettes) |
| `ALBION_PROVIDER_TIMEOUT_SECONDS` | optionnel | Timeout HTTP provider (défaut: `8`) |
| `ALBION_ICON_BASE_URL` | optionnel | Base URL de rendu des icônes item (défaut: `https://render.albiononline.com/v1/item`) |
| `ALBION_CACHE_MEMORY_TTL_SECONDS` | optionnel | TTL cache mémoire pour requêtes fréquentes (défaut: `300`) |
| `ALBION_CACHE_SNAPSHOT_PATH` | optionnel | Fichier snapshot persistant pour warm start/fallback (défaut: `data/albion_provider_snapshot.json`) |
| `ALBION_SYNC_INTERVAL_SECONDS` | optionnel | Fréquence du job de synchronisation périodique (défaut: `86400`, soit 24h) |

Comportement:
- synchronisation journalière (24h) qui télécharge `items.txt`, calcule les diffs (`insert/update/deactivate`) et persiste l'index dans la table SQL dédiée `craft_items_index`,
- persistance de métadonnées de synchro (`source`, `checksum`, date de tentative/réussite, compteurs, erreur) dans `craft_sync_state`,
- `GET /api/craft/items` lit désormais en priorité depuis `craft_items_index` (fallback mémoire/snapshot si nécessaire),
- endpoint admin d'invalidation manuelle `POST /api/admin/craft/cache/invalidate?guild_id=<id>` (admin Discord + CSRF),
- source de vérité persistante du focus craft via table SQL `craft_focus_costs`, hydratée dans `metadata.base_focus_cost` lors de `GET /api/craft/items/{item_id}`,
- simulation craft durcie: `POST /api/craft/simulate` renvoie une erreur explicite `missing_focus_cost` si le coût focus n'est pas configuré (suppression du fallback implicite),
- convention d'ID enchanté unifiée en suffixe `@N` (ex: `T4_BAG@2`) et nouveau champ API `enchantment_level` (0..4), résolu en `item_id` final avant `get_item_detail` avec fallback automatique sur l'item de base si la variante n'a pas de détail,
- maintenance focus cost via endpoint admin `POST /api/admin/craft/focus-costs?guild_id=<id>` (bulk upsert) et script `python web/backend/scripts/upsert_focus_costs.py --input <csv|json>`,
- fallback automatique: en cas d'échec réseau, l'API continue à servir la dernière version DB/snapshot et conserve `last_success_at`,
- exposition du statut de synchro via `GET /api/craft/metadata` et `GET /api/admin/craft/sync-status?guild_id=<id>`,
- récupération paresseuse du détail d'un item via le template Tools4Albion intégré (`{item_id}`) si la recette n'est pas encore en cache.

Endpoints intégrés en dur:
- `items.txt` -> `https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt` (index massif pour autocomplete),
- détail item -> `https://www.tools4albion.com/api_info.php?item_id={item_id}` pour charger recette/metadata au besoin.


### Simulation craft (backend domain)

Le backend dashboard expose maintenant `POST /api/craft/simulate` avec un module métier pur `web/backend/domain/crafting/simulator.py` (sans dépendance I/O) pour les calculs.

- Validation stricte des inputs: `quantity > 0`, `mastery/specialization` bornés `0..100`, `available_focus >= 0`, `location_key` supporté, item `craftable`.
- Formules:
  - `focus_efficiency = min(0.5, mastery*0.002 + specialization*0.003)`
  - `focus_per_item = ceil(base_focus_cost * (1 - focus_efficiency))`
  - `total_focus = focus_per_item * quantity`
  - `total_return_rate = clamp(base + city/HO + bonus + focus(si activé), 0, 0.95)`
  - `net_quantity = ceil(gross_quantity * (1 - total_return_rate))`
- Multi-étapes: séparation explicite entre `base_materials` (bruts non craftables) et `intermediate_materials` (composants craftables).
- Résultat structuré: focus/item, focus total, items réalisables avec focus disponible, rendements appliqués, matériaux bruts vs nets.

Clés `location_key` supportées actuellement:
- `none`
- `city` (+ `city_key`)
- `hideout` (+ `hideout_biome_key`, `hideout_territory_level`, `hideout_zone_quality`)

Détail localisation craft:
- **City**: bonus de retour appliqué seulement si la catégorie de l'item cible correspond à la spécialisation de la ville (mapping backend centralisé),
- **Hideout**: bonus de retour calculé depuis biome + niveau de territoire (`1..9`) + qualité de zone (`1..6`) via lookup O(1),
- Focus bonus conserve `+25%` pour `city`/`hideout`.



### Calculateur craft & rentabilité
- Endpoint backend `POST /api/craft/profitability` pour simuler la rentabilité à partir du résultat craft (`/api/craft/simulate`) + prix d'entrée utilisateur.
- Retour détaillé pour l'UI: coûts par matériau, coût focus implicite, coût livre d'imbuer, **frais de station (%)**, revenu brut/net, profit et marge (%).
- Front dashboard mis à jour avec formulaire de prix unitaires, frais de station et récapitulatif financier complet.
- Sélection d'item améliorée: autocomplete intelligent (nom + ID) avec affichage des icônes, pour une sélection plus rapide et fiable.
- Parsing `items.txt` renforcé côté backend (lignes préfixées, format `ID : NAME`, CSV/TSV simples, fallback JSON ligne) pour mieux hydrater `name`, `tier`, `enchant` et `icon`, avec fallback automatique `name = item_id` si le nom est vide.
- Préférences utilisateur persistantes (item cible, spés, localisation, prix): `GET/PUT /api/user/preferences/craft` (lié au compte Discord connecté).

## Formule focus agrégée (catégorie + spécialisations)

Le calculateur craft utilise désormais:

1. **Efficacité focus item**
   - `eff(item) = min(0.5, category_mastery_appliquee(item)*0.002 + specialization(item)*0.003)`
2. **Focus unitaire item**
   - `focus_unit(item) = ceil(base_focus_cost(item) * (1 - eff(item)))`, minimum `1`.
3. **Focus total simulation**
   - `focus_total = focus_cible + somme(focus_intermediaires_craftables_avec_focus_cost)`.
   - Pour les intermédiaires d'une **autre catégorie** que l'item cible, `category_mastery_appliquee = 0`.

### Exemple 1 (item unique)
- `category_mastery_level = 50`, `specialization_cible = 80`, `base_focus_cost = 100`.
- `eff = min(0.5, 50*0.002 + 80*0.003) = min(0.5, 0.34) = 0.34`.
- `focus_unit = ceil(100 * 0.66) = 66`.

### Exemple 2 (intermédiaire sans spécialisation renseignée)
- Item cible holy staff, intermédiaire `T4_PLANK` sans entrée dans `item_specializations`.
- Spécialisation intermédiaire par défaut `0`.
- Si `T4_PLANK` n'est pas dans la même catégorie que l'item cible, maîtrise catégorie appliquée `0`.
- Donc `eff(T4_PLANK)=0`, focus intermédiaire plein (coût brut).
