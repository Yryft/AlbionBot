# Crafting Assistant & Killboard (architecture)

## Fondation commune
- Persistance SQL centralisée dans `BankDB`.
- Nouvelles tables: `craft_profiles`, `craft_presets`, `killboard_trackers`, `killboard_events`, `killboard_event_posts`.
- Contrainte anti-doublon killboard: clé primaire `(albion_server, event_id)`.

## Module Crafting
- Service: `web/backend/crafting.py`.
- Sources:
  1. index local (`web/backend/data/crafting/*`)
  2. GameInfo (fallback runtime)
- API:
  - `GET /api/craft/catalog`
  - `GET /api/craft/item/{type_key}`
  - `GET/PUT /api/craft/profile?guild_id=...`
  - `GET/POST /api/craft/presets?guild_id=...`

## Module Killboard
- Provider: `GameInfoKillboardProvider`.
- Service: `KillboardService`.
- Rendu: `KillboardRenderService` (PNG quand Pillow est disponible).
- API:
  - `GET/POST /api/killboard/trackers?guild_id=...`
  - `DELETE /api/killboard/trackers/{tracker_id}`
  - `POST /api/killboard/poll`
  - `GET /api/killboard/events?guild_id=...`
- Discord:
  - `/killboard_add_guild`
  - `/killboard_add_player`
  - `/killboard_remove`
  - `/killboard_list`
  - `/killboard_poll_now`

## Vérification rapide
1. Créer un tracker killboard (dashboard ou slash command).
2. Lancer un poll manuel (`/killboard_poll_now` ou endpoint poll).
3. Vérifier la présence d'un event dans l'onglet Killboard et en base.
4. Ouvrir l'onglet Crafting, choisir type/tier/enchant, vérifier focus et recettes.
