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
