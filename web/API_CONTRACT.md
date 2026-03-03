# Contrat API bot ↔ dashboard

Base URL backend dashboard: `/api`

## DTOs

- `GuildDTO`: `{ id, name, roles[] }`
- `RoleDTO`: `{ id, name }`
- `TicketTranscriptDTO`: métadonnées ticket + `messages[]`
- `TicketMessageDTO`: `{ message_id, author_id, author_name?, author_avatar_url?, content, embeds[], attachments[], created_at, event_type }`
- `RaidTemplateDTO`: template de compo + `roles[]`
- `RaidRoleDTO`: `{ key, label, slots, ip_required, required_role_ids[] }`
- `RaidDTO`: raid ouverte avec `status` (`OPEN|PINGED|CLOSED`) + `channel_id/message_id` pour suivi publication Discord
- `RaidDTO.publish_status`: état de la commande de publication (`pending|delivered|failed`)
- `RaidDTO.publish_error`: dernier message d'erreur côté publication Discord (vide si succès)

## Endpoints lecture

- `GET /api/guilds`
- `GET /api/guilds/{guild_id}/tickets`
- `GET /api/guilds/{guild_id}/tickets/{ticket_id}`
- `GET /api/raid-templates`
- `GET /api/raids`
- `GET /api/my/raids`
- `GET /api/raids/{raid_id}/roster`
- `GET /api/guilds/{guild_id}/balances`
- `GET /api/public/overview`

## Endpoints actions managées

> Les écritures dashboard sont traitées comme des **commandes bot**: le dashboard enregistre l'action, puis le bot Discord applique/synchronise l'effet côté Discord (messages raid, état roster, banque, tickets).
>
> Pour l'ouverture de raid, une **outbox persistante** est utilisée: la commande est créée en `pending`, puis marquée `delivered` ou `failed` (avec retry/backoff automatique côté bot).

- `POST /api/actions/raids/open`
  - body: `RaidOpenRequestDTO` (`channel_id` requis, `voice_channel_id` optionnel)
  - permission requise: `raid_open` / `raid_manager`
- `POST /api/actions/comp-wizard`
  - body: `CompTemplateCreateRequestDTO`
  - permission requise: `comp_wizard` / `raid_manager`
- `POST /api/raids/{raid_id}/signup`
  - body: `RaidSignupRequestDTO`
- `POST /api/raids/{raid_id}/leave`
- `PUT /api/raid-templates/{template_name}`
  - body: `RaidTemplateUpdateRequestDTO`
- `PUT /api/raids/{raid_id}`
  - body: `RaidUpdateRequestDTO`
- `POST /api/actions/bank/apply`
  - body: `BankActionRequestDTO`
  - permission requise: `bank_manage` / `bank_manager`

Les endpoints d'action sont pensés pour être protégés derrière une auth manager (JWT/proxy) côté infra.


## Auth Discord OAuth2

- `GET /auth/discord/login`: redirige vers Discord (`identify guilds`)
- `GET /auth/discord/callback`: callback OAuth2 sécurisé par `state`
- `POST /auth/logout`: logout (CSRF requis via header `X-CSRF-Token`)
- `GET /me`: profil Discord courant + guilds communes utilisateur/bot + guild sélectionnée
- `POST /me/select-guild/{guild_id}`: met à jour la guild active (CSRF requis)

Sécurité: session serveur-side, cookie HttpOnly (`albion_dash_session`), cookie CSRF (`albion_dash_csrf`), `SameSite=None` (ou `Lax` en local), refresh automatique du token, révocation au logout.


> Note: les endpoints de lecture restent accessibles sans OAuth quand celui-ci n'est pas configuré (mode local/dev).
