# Contrat API bot ↔ dashboard

Base URL backend dashboard: `/api`

## DTOs

- `GuildDTO`: `{ id, name, roles[] }`
- `RoleDTO`: `{ id, name }`
- `TicketTranscriptDTO`: métadonnées ticket + `messages[]`
- `TicketMessageDTO`: `{ message_id, author_id, content, created_at, event_type }`
- `RaidTemplateDTO`: template de compo + `roles[]`
- `RaidRoleDTO`: `{ key, label, slots, ip_required, required_role_ids[] }`
- `RaidDTO`: raid ouverte avec `status` (`OPEN|PINGED|CLOSED`)

## Endpoints lecture

- `GET /api/guilds`
- `GET /api/guilds/{guild_id}/tickets`
- `GET /api/guilds/{guild_id}/tickets/{ticket_id}`
- `GET /api/raid-templates`
- `GET /api/raids`

## Endpoints actions managées

- `POST /api/actions/raids/open`
  - body: `RaidOpenRequestDTO`
- `POST /api/actions/comp-wizard`
  - body: `CompTemplateCreateRequestDTO`

Les endpoints d'action sont pensés pour être protégés derrière une auth manager (JWT/proxy) côté infra.


## Auth Discord OAuth2

- `GET /auth/discord/login`: redirige vers Discord (`identify guilds`)
- `GET /auth/discord/callback`: callback OAuth2 sécurisé par `state`
- `POST /auth/logout`: logout (CSRF requis via header `X-CSRF-Token`)
- `GET /me`: profil Discord courant + guilds communes utilisateur/bot + guild sélectionnée
- `POST /me/select-guild/{guild_id}`: met à jour la guild active (CSRF requis)

Sécurité: session serveur-side, cookie HttpOnly (`albion_dash_session`), cookie CSRF (`albion_dash_csrf`), `SameSite=Lax`, refresh automatique du token, révocation au logout.
