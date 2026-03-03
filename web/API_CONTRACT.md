# Contrat API bot ↔ dashboard

Base URL backend dashboard: `/api`

## DTOs

## Convention d'identifiants (IDs)

Tous les IDs Discord exposés par l'API dashboard sont des **strings** (snowflakes Discord):

- `guild_id`: `string`
- `user_id`: `string`
- `message_id`: `string`
- `role_id`: `string`
- `channel_id`: `string`

Le backend conserve des entiers en interne si nécessaire, puis convertit explicitement à l'entrée/sortie des DTOs API.

- `GuildDTO`: `{ id, name, roles[] }`
- `RoleDTO`: `{ id, name }`
- `TicketTranscriptDTO`: métadonnées ticket + `messages[]`
- `TicketMessageDTO`: `{ message_id, author_id, author_name?, author_avatar_url?, content, embeds[], attachments[], created_at, event_type }`
- `RaidTemplateDTO`: template de compo + `roles[]`
- `RaidRoleDTO`: `{ key, label, slots, ip_required, required_role_ids[] }`
- `RaidDTO`: raid ouverte avec `status` (`OPEN|PINGED|CLOSED`) + état de publication Discord (`publish_status`, `publish_error`)
  - `publish_status`: `pending|delivered|failed` (source de vérité UI pour l'état de publication)
  - `publish_error`: dernier message d'erreur côté publication Discord (affiché dans l'UI si non vide)

## Matrice de référence raids (bot ↔ backend ↔ dashboard)

| Commande bot | Endpoint backend dashboard | Écran dashboard |
| --- | --- | --- |
| `/raid_open` | `POST /api/actions/raids/open` | `Dashboard` → bloc **Raid opener** |
| `/raid_edit` | `PUT /api/raids/{raid_id}` | `Dashboard` → bloc **Raid opener** (édition) + bouton **Éditer** dans `Tous les raids` |
| `/raid_close` | `POST /api/raids/{raid_id}/state` avec `{ "action": "close" }` | `Tous les raids` → bouton **Fermer raid** |
| `/raid_assistant` (close/edit) | `PUT /api/raids/{raid_id}` + `POST /api/raids/{raid_id}/state` | `Tous les raids` (actions **Éditer** / **Fermer raid**) |
| Boutons roster raid (`join/leave/absent`) | `GET /api/raids/{raid_id}/roster`, `POST /api/raids/{raid_id}/signup`, `POST /api/raids/{raid_id}/leave` | `Tous les raids` → panneau **Inscriptions en ligne** (**Gérer roster**) |
| `/loot_split`, `/loot_scout_limits` | _Non exposé dans le backend dashboard_ | _N/A_ |
| `/bal` | `GET /api/guilds/{guild_id}/balances/{user_id}` | `Banque` → bloc **Consultation ciblée** |
| `/pay` | `POST /api/actions/bank/pay` | `Banque` → bloc **Transfert** |
| `/bank_undo` | `POST /api/actions/bank/undo` | `Banque` → bouton **/bank_undo** |

## Endpoints lecture

- `GET /api/guilds`
- `GET /api/guilds/{guild_id}/tickets`
- `GET /api/guilds/{guild_id}/tickets/{ticket_id}`
- `GET /api/raid-templates`
- `GET /api/raids`
- `GET /api/my/raids`
- `GET /api/raids/{raid_id}/roster`
- `GET /api/guilds/{guild_id}/balances`
- `GET /api/guilds/{guild_id}/balances/{user_id}`
- `GET /api/guilds/{guild_id}/bank/actions?limit=25`
- `GET /api/public/overview`

## Endpoints actions managées

> Les écritures dashboard sont traitées comme des **commandes bot**: le dashboard enregistre l'action, puis le bot Discord applique/synchronise l'effet côté Discord (messages raid, état roster, banque, tickets).
>
> Pour l'ouverture de raid, une **outbox persistante** est utilisée: la commande est créée en `pending`, puis marquée `delivered` ou `failed` (avec retry/backoff automatique côté bot).

- `POST /api/actions/raids/open`
  - body: `RaidOpenRequestDTO` (`channel_id` requis, `voice_channel_id` optionnel, IDs au format `string`)
  - permission requise: `raid_open` / `raid_manager`
- `POST /api/actions/comp-wizard`
  - body: `CompTemplateCreateRequestDTO` (`raid_required_role_ids[]` en `string`)
  - permission requise: `comp_wizard` / `raid_manager`
- `POST /api/raids/{raid_id}/signup`
  - body: `RaidSignupRequestDTO`
- `POST /api/raids/{raid_id}/leave`
- `PUT /api/raid-templates/{template_name}`
  - body: `RaidTemplateUpdateRequestDTO`
- `PUT /api/raids/{raid_id}`
  - body: `RaidUpdateRequestDTO`
- `POST /api/raids/{raid_id}/state`
  - body: `RaidStateUpdateRequestDTO` (`action: close`)
- `POST /api/actions/bank/apply`
  - body: `BankActionRequestDTO` (`target_user_ids[]` en `string`)
  - permission requise: `bank_manage` / `bank_manager`
- `POST /api/actions/bank/undo`
  - body: `BankUndoRequestDTO`
  - permission requise: `bank_manage` / `bank_manager`
- `POST /api/actions/bank/pay`
  - body: `BankTransferRequestDTO`
  - permission requise: membre de la guilde (pas manager)

### Règles de permission banque

- `GET /api/guilds/{guild_id}/balances` et les actions manager (`/bank_add`, `/bank_remove`, `*_split`, `/bank_undo`) exigent `bank_manage` / `bank_manager`.
- `GET /api/guilds/{guild_id}/balances/{user_id}` autorise la consultation de sa propre balance pour tout membre; la consultation d'un tiers exige `bank_manage`.
- `POST /api/actions/bank/pay` est accessible à tout membre de la guilde et applique le transfert `from=current_user -> to_user`.
- Les validations de soldes manager (`apply`, `undo`) utilisent `BANK_ALLOW_NEGATIVE` côté backend dashboard, aligné avec `cfg.bank_allow_negative` du bot.

Les endpoints d'action sont pensés pour être protégés derrière une auth manager (JWT/proxy) côté infra.


## Auth Discord OAuth2

- `GET /auth/discord/login`: redirige vers Discord (`identify guilds`)
- `GET /auth/discord/callback`: callback OAuth2 sécurisé par `state`
- `POST /auth/logout`: logout (CSRF requis via header `X-CSRF-Token`)
- `GET /me`: profil Discord courant + guilds communes utilisateur/bot + guild sélectionnée
- `POST /me/select-guild/{guild_id}`: met à jour la guild active (CSRF requis)

Sécurité: session serveur-side, cookie HttpOnly (`albion_dash_session`), cookie CSRF (`albion_dash_csrf`), `SameSite=None` (ou `Lax` en local), refresh automatique du token, révocation au logout.


> Note: les endpoints de lecture restent accessibles sans OAuth quand celui-ci n'est pas configuré (mode local/dev).
