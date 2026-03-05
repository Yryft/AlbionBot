# AlbionBot Web

Structure proposée:

- `web/backend`: API FastAPI dédiée dashboard.
- `web/dashboard`: Frontend Next.js (navigation style Discord).

## Principe de contrôle

- Le dashboard sert de **console de pilotage** du bot.
## Convention IDs API

- Tous les IDs Discord échangés entre frontend et backend (`guild_id`, `user_id`, `message_id`, `role_id`, `channel_id`) sont sérialisés en **`string`**.
- Le backend convertit ces IDs en `int` uniquement pour son traitement interne.

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

> Le bot recharge l'état partagé périodiquement (5s) afin d'appliquer dans Discord les actions faites depuis le dashboard (raids publiés/édités/fermés, état banque et tickets rafraîchi).
> Le backend dashboard recharge aussi l'état partagé au début de chaque requête HTTP pour éviter les statuts de publication obsolètes (ex: raid affiché `pending` alors qu'il est déjà publié) et limiter les écrasements inter-processus.

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
- Actions raids alignées bot: ouverture, édition, fermeture explicite et gestion roster.
- Endpoint `GET /api/guilds/{guild_id}/discord-directory` pour alimenter les autocomplétions (channels text/voice + membres).
- Affichage des balances avec pseudo Discord quand disponible.
- Formulaire template aligné API bot: `content_type`, `raid_required_role_ids`, `spec` complète (`Label;slots;options`).
- Retour explicite des validations de spec (`spec_warnings`, erreurs détaillées) côté dashboard.
- Cycle de vie template complet côté API/dashboard: création, édition et suppression (permissions manager conservées).
- UI dashboard simplifiée: suppression des éléments de builder décoratifs non reliés au modèle bot.
- **Onglet Banque** aligné sur les commandes bot officielles (`/bank_add`, `/bank_remove`, `/bank_add_split`, `/bank_remove_split`, `/bank_undo`, `/pay`, `/bal`).
- Cache de permissions/roles membre côté backend dashboard pour éviter de re-fetch Discord à chaque commande.
- Suivi UI de publication raid basé sur `publish_status` (`pending|delivered|failed`) + affichage de `publish_error` en cas d'échec.
- Leaderboard balances aligné avec Discord + actions rapides `/bank_add` et `/bank_remove` depuis le dashboard.
- Consultation ciblée d'une balance (`GET /api/guilds/{guild_id}/balances/{user_id}`) avec règles de permissions alignées bot (self vs manager).
- Historique d'actions banque manager (`GET /api/guilds/{guild_id}/bank/actions`) dans l'onglet Banque.
- Correction transcript tickets: conservation du contenu réel des messages (y compris fallback `system_content`) et lecture des anciens snapshots legacy.
- Endpoint `POST /api/actions/raids/open` protégé par la permission logique **raid_manager** (et non **bank_manager**).
- Endpoint `POST /api/raids/{raid_id}/state` (`action=close`) pour refléter explicitement `/raid_close` côté bot.
- Endpoint `POST /api/actions/bank/apply` protégé par la permission logique **bank_manager** (clé métier `bank_manage`).
- Endpoints `POST /api/actions/bank/undo` (manager) et `POST /api/actions/bank/pay` (membre de guilde) pour couvrir les commandes `/bank_undo` et `/pay`.
- Validation des actions manager banque alignée sur `BANK_ALLOW_NEGATIVE` (équivalent dashboard de `cfg.bank_allow_negative`).
- Outbox persistante pour `POST /api/actions/raids/open`: création d'une commande `pending`, consommation côté bot Discord, retry/backoff et exposition du statut (`publish_status`) pour l'UI.
- Harmonisation visuelle des contrôles interactifs du dashboard via des tokens CSS partagés (`--control-height`, `--control-radius`, `--control-padding-x`) appliqués aux onglets, CTA et listes d'actions (Raids, Banque, Templates, Tickets).
- Raid opener: remplacement des saisies d'IDs de salons par des sélecteurs explicites (texte/vocal) alimentés par `discord-directory`, avec mode "ID manuel" repliable réservé au dépannage.
- Banque manager: remplacement de la saisie libre `User IDs` par un multi-select membres (`display_name + id`) + fallback "ID manuel" repliable.
- Validation UI pré-submit des IDs (salons/utilisateurs) contre le répertoire local Discord pour réduire les erreurs de mapping avant appel API.
- Validation form-level renforcée dans `web/dashboard/app/page.tsx`: contrôles explicites avant `apiPost`/`apiPut` (montants > 0, IP numérique, date raid future, sélections requises), erreurs contextuelles par champ et désactivation des submit tant que les préconditions minimales ne sont pas satisfaites.
- Cleanup admin étendu: boutons de suppression pour les raids et endpoint `DELETE /api/guilds/{guild_id}/balances/{user_id}` pour purger les mauvaises entrées banque (utilisateurs supprimés/orphelins).


- Prévisualisation du message raid ajoutée dans le bloc **Raid opener** avant soumission.
- Preview Raid opener renforcée: rendu backend du message **exact** (embed + composants interactifs) via `POST /api/actions/raids/preview`, en réutilisant la logique bot côté API.
- Écran non-authentifié recentré sur une présentation AlbionBot + CTA unique de connexion Discord.
- Nouveaux endpoints admin dashboard: `GET /api/guilds/{guild_id}/permissions` et `PUT /api/guilds/{guild_id}/permissions/{permission_key}` pour gérer les permissions par rôles et membres.
- Navigation dashboard ajustée: le panneau administratif (permissions) est déplacé dans un onglet dédié **Administration** pour séparer les opérations admin du dashboard opérationnel quotidien.
- Écran d'accueil non connecté corrigé: la page occupe désormais toute la largeur utile (plus de colonne latérale vide héritée de la vue connectée).
- Client API dashboard enrichi pour le craft: nouveaux DTOs (`CraftItemDTO`, `CraftLocationBonusDTO`, `CraftSimulation*`, `CraftProfitability*`) et wrappers dédiés (`apiGetCraftItems`, `apiGetCraftLocationBonuses`, `apiPostCraftSimulation`, `apiPostCraftProfitability`) avec propagation uniforme des erreurs `ApiError`.
- Calculateur craft & rentabilité: endpoint `POST /api/craft/profitability` (simulation + prix saisis) avec breakdown transparent par matériau (quantité, prix unitaire, coût ligne), mode de prix `manual|prefilled`, et agrégats (`coût matériaux`, `coût focus`, `revenu brut/net`, `profit`, `marge`).
- Onglet craft durci côté frontend: si `GET /api/craft/items` renvoie une erreur (ex: `503`) ou un payload invalide, l'UI affiche désormais un message explicite au lieu de planter sur un `.map`.

## Spec template (parse_comp_spec)

Format: une ligne par rôle, `Label;slots;options`.

Exemples valides:

```text
Tank;2;key=tank
Healer;2;ip=true
DPS Melee;4;req=123456789012345678
Support;2;roles=234567890123456789,345678901234567890
```

Options reconnues: `key=`, `ip=true|false`, `req=` / `require=` / `roles=`.

Erreurs bloquantes (spec vide, slots invalides, lignes invalides) sont remontées en `detail.details.errors[]`.
Warnings non bloquants (option inconnue) remontent en `spec_warnings[]` sur les endpoints de création/édition template.

## Provider craft Albion (backend)

Nouveaux endpoints backend:
- `GET /api/craft/items?q=<texte>&limit=<n>`: recherche/autocomplete items craftables.
- `GET /api/craft/items/{item_id}`: détail craft (recette + icône + métadonnées provider).
- `POST /api/admin/craft/cache/invalidate?guild_id=<id>`: invalidation manuelle cache (admin serveur + CSRF).
- `GET /api/craft/metadata`: statut de synchronisation (source/checksum/erreur).
- `GET /api/admin/craft/sync-status?guild_id=<id>`: même statut pour administration serveur.

Variables d'environnement associées:
- `ALBION_PROVIDER_URL` (source catalogue/recettes, optionnelle),
- `ALBION_PROVIDER_TIMEOUT_SECONDS` (timeout HTTP),
- `ALBION_ICON_BASE_URL` (mapping icônes),
- `ALBION_CACHE_MEMORY_TTL_SECONDS` (TTL cache mémoire),
- `ALBION_CACHE_SNAPSHOT_PATH` (snapshot persistant warm start/fallback),
- `ALBION_SYNC_INTERVAL_SECONDS` (job de sync périodique, défaut 24h).

Source de vérité focus cost:
- table SQL `craft_focus_costs` (persistante) utilisée par `GET /api/craft/items/{item_id}` et `POST /api/craft/simulate`,
- en simulation, absence de `base_focus_cost` => erreur explicite `missing_focus_cost` (plus de fallback silencieux),
- maintenance via endpoint admin `POST /api/admin/craft/focus-costs?guild_id=<id>` (admin + CSRF) ou script `python web/backend/scripts/upsert_focus_costs.py --input <fichier.csv|json>`.


Endpoints provider intégrés en dur:
- index/autocomplete via dump `ao-bin-dumps` (`https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt`),
- détails/recettes à la demande via `https://www.tools4albion.com/api_info.php?item_id={item_id}`.

Stockage/sync:
- table SQL `craft_items_index` pour l'autocomplete (items actifs/inactifs + source/checksum + timestamps),
- table SQL `craft_sync_state` pour le statut de la dernière tentative (`ok|error`, compteurs de diff, `last_success_at`, erreur),
- fallback automatique sur la dernière version persistée en DB si la synchro distante échoue.

## Calculateur craft & rentabilité

Le dashboard propose désormais un flux complet de simulation de rentabilité:
- saisie des prix unitaires matériau par matériau + coût livre d'imbuer + prix de vente final,
- mode **Prix manuel** et mode **Prérempli** (activé si des prix marché sont exposés par l'API provider),
- récapitulatif des coûts/revenus: matériaux, focus implicite (si valorisé), brut/net, profit et marge.

API associée:
- `POST /api/craft/simulate`: calcule les quantités brutes/nettes et le focus,
- `POST /api/craft/profitability`: agrège les prix d'entrée et retourne un breakdown ligne par ligne + KPI de rentabilité.

