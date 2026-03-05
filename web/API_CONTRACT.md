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
- `GuildPermissionBindingDTO`: `{ permission_key, role_ids[], user_ids[] }` pour configurer les permissions bot par rôle et membre.
- `CraftItemDTO`: `{ id, name, tier, enchant, icon, category, craftable }`
- `CraftLocationBonusDTO`: `{ location_key, location_name, is_hideout, return_rate_bonus, focus_bonus, craft_fee }`
- `CraftSimulationRequestDTO`: `{ item_id, quantity, category_mastery_level, item_specializations, location_key, available_focus, use_focus }`
- `CraftSimulationResultDTO`: `{ item_id, focus_efficiency, focus_per_item, total_focus, items_craftable_with_available_focus, base_materials[], intermediate_materials[], applied_yields }`
  - `base_materials[]`: `{ item_id, item_name, gross_quantity, net_quantity }` (matériaux bruts non craftables)
  - `intermediate_materials[]`: `{ item_id, item_name, gross_quantity, net_quantity }` (intermédiaires craftables)
  - `applied_yields`: `{ base_return_rate, location_return_rate_bonus, hideout_return_rate_bonus, focus_return_rate_bonus, additional_return_rate_bonus, total_return_rate }`
- `CraftProfitabilityRequestDTO`: `{ simulation, material_unit_prices, imbuer_journal_unit_price, item_sale_unit_price, crafted_quantity, market_tax_rate, focus_unit_price, include_focus_cost, pricing_mode }`
- `CraftProfitabilityResultDTO`: `{ simulation, pricing_mode, material_lines[], total_material_cost, focus_cost, imbuer_journal_cost, total_cost, gross_revenue, market_tax_amount, net_revenue, profit, margin_pct }`

## Matrice de référence raids (bot ↔ backend ↔ dashboard)

| Commande bot | Endpoint backend dashboard | Écran dashboard |
| --- | --- | --- |
| `/raid_open` | `POST /api/actions/raids/open` | `Dashboard` → bloc **Raid opener** |
| `/raid_edit` | `PUT /api/raids/{raid_id}` | `Dashboard` → bloc **Raid opener** (édition) + bouton **Éditer** dans `Tous les raids` |
| `/raid_close` | `POST /api/raids/{raid_id}/state` avec `{ "action": "close" }` | `Tous les raids` → bouton **Fermer raid** |
| _Cleanup admin_ | `DELETE /api/raids/{raid_id}` | `Tous les raids` → bouton **Supprimer raid** |
| `/raid_assistant` (close/edit) | `PUT /api/raids/{raid_id}` + `POST /api/raids/{raid_id}/state` | `Tous les raids` (actions **Éditer** / **Fermer raid**) |
| Boutons roster raid (`join/leave/absent`) | `GET /api/raids/{raid_id}/roster`, `POST /api/raids/{raid_id}/signup`, `POST /api/raids/{raid_id}/leave` | `Tous les raids` → panneau **Inscriptions en ligne** (**Gérer roster**) |
| `/loot_split`, `/loot_scout_limits` | _Non exposé dans le backend dashboard_ | _N/A_ |
| `/bal` | `GET /api/guilds/{guild_id}/balances/{user_id}` | `Banque` → bloc **Consultation ciblée** |
| `/pay` | `POST /api/actions/bank/pay` | `Banque` → bloc **Transfert** |
| `/bank_undo` | `POST /api/actions/bank/undo` | `Banque` → bouton **/bank_undo** |
| _Cleanup admin banque_ | `DELETE /api/guilds/{guild_id}/balances/{user_id}` | `Banque` → suppression d'une entrée utilisateur |


### Formules & hypothèses craft simulation

- Validation stricte:
  - `quantity > 0`, `0 <= category_mastery_level <= 100`, chaque niveau de `item_specializations` borné `0..100`, `available_focus >= 0`, `location_key` connu.
  - l'item cible doit être `craftable=true`.
- Efficacité focus cible: `focus_efficiency_target = min(0.5, category_mastery_level*0.002 + specialization_item_cible*0.003)`.
- Coût focus unitaire cible: `focus_per_item = ceil(base_focus_cost_target * (1 - focus_efficiency_target))` (min 1).
- Coût focus total agrégé: somme du focus cible + intermédiaires craftables ayant un focus cost connu.
  - pour chaque intermédiaire: `eff = min(0.5, category_mastery_appliquée*0.002 + specialization_intermediaire*0.003)`
  - `category_mastery_appliquée = category_mastery_level` uniquement si l'intermédiaire est dans la même catégorie que l'item cible, sinon `0`.
  - `focus_intermediaire = ceil(base_focus_cost_intermediaire * (1 - eff)) * quantite_intermediaire`.

- Rendement total: `total_return_rate = clamp(base + location + hideout + bonus + (focus_bonus si use_focus), 0, 0.95)`.
- Matériaux nets: `net_quantity = ceil(gross_quantity * (1 - total_return_rate))`.
- Multi-étapes:
  - `base_materials`: expansion récursive jusqu'aux ressources non craftables.
  - `intermediate_materials`: composants craftables intermédiaires cumulés.

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
- `DELETE /api/guilds/{guild_id}/balances/{user_id}`
- `GET /api/guilds/{guild_id}/bank/actions?limit=25`
- `GET /api/guilds/{guild_id}/permissions` (admin serveur)
- `GET /api/public/overview`
- `GET /api/craft/items?q=<texte>&limit=<n>`
- `GET /api/craft/items/{item_id}`
- `POST /api/admin/craft/cache/invalidate?guild_id=<discord_guild_id>` (admin serveur + CSRF)

## Endpoints actions managées

> Les écritures dashboard sont traitées comme des **commandes bot**: le dashboard enregistre l'action, puis le bot Discord applique/synchronise l'effet côté Discord (messages raid, état roster, banque, tickets).
>
> Pour l'ouverture de raid, une **outbox persistante** est utilisée: la commande est créée en `pending`, puis marquée `delivered` ou `failed` (avec retry/backoff automatique côté bot).

- `POST /api/actions/raids/preview`
  - body: `RaidOpenPreviewRequestDTO`
  - réponse: `RaidOpenPreviewDTO` (embed Discord + composants, alignés sur le rendu bot)
  - permission requise: `raid_open` / `raid_manager`
- `POST /api/actions/raids/open`
  - body: `RaidOpenRequestDTO` (`channel_id` requis, `voice_channel_id` optionnel, IDs au format `string`)
  - permission requise: `raid_open` / `raid_manager`
- `POST /api/actions/comp-wizard`
  - body: `CompTemplateCreateRequestDTO` (`raid_required_role_ids[]` en `string`)
  - réponse: `TemplateMutationResultDTO` (`template`, `spec_warnings[]`, `spec_errors[]`)
  - permission requise: `comp_wizard` / `raid_manager`
- `POST /api/raids/{raid_id}/signup`
  - body: `RaidSignupRequestDTO`
- `POST /api/raids/{raid_id}/leave`
- `PUT /api/raid-templates/{template_name}`
  - body: `RaidTemplateUpdateRequestDTO`
  - réponse: `TemplateMutationResultDTO` (`template`, `spec_warnings[]`, `spec_errors[]`)
- `DELETE /api/raid-templates/{template_name}`
  - permission requise: `comp_wizard` / `raid_manager`
- `PUT /api/raids/{raid_id}`
  - body: `RaidUpdateRequestDTO`
- `POST /api/raids/{raid_id}/state`
  - body: `RaidStateUpdateRequestDTO` (`action: close`)
- `DELETE /api/raids/{raid_id}`
  - permission requise: `raid_open` / `raid_manager`
- `POST /api/actions/bank/apply`
  - body: `BankActionRequestDTO` (`target_user_ids[]` en `string`)
  - permission requise: `bank_manage` / `bank_manager`
- `POST /api/actions/bank/undo`
  - body: `BankUndoRequestDTO`
  - permission requise: `bank_manage` / `bank_manager`
- `POST /api/actions/bank/pay`
  - body: `BankTransferRequestDTO`
  - permission requise: membre de la guilde (pas manager)
- `DELETE /api/guilds/{guild_id}/balances/{user_id}`
  - permission requise: `bank_manage` / `bank_manager`
- `PUT /api/guilds/{guild_id}/permissions/{permission_key}`
  - body: `GuildPermissionUpdateRequestDTO` (`role_ids[]`, `user_ids[]`)
  - permission requise: administrateur du serveur
- `POST /api/craft/simulate`
  - body: `CraftSimulationRequestDTO`
  - réponse: `CraftSimulationResultDTO`
  - erreurs de validation métier: `ApiError` avec payload `detail` (`code`, `message`, `details`)
- `POST /api/craft/profitability`
  - body: `CraftProfitabilityRequestDTO`
  - réponse: `CraftProfitabilityResultDTO` avec breakdown ligne par ligne (`material_lines[]`) pour affichage transparent
  - erreurs de validation métier: `ApiError` avec payload `detail` (`code`, `message`, `details`)

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

## Spec template compatible `parse_comp_spec`

Format attendu par ligne: `Label;slots;options...`

Options supportées:
- `key=<slug>`
- `ip=true|false` (alias: `ip`, `ip=1`, `ip_required=true`, `ip=0`, `noip`)
- `req=<roleId1,roleId2>` (alias: `require=`, `roles=`)
- liste brute d'IDs de rôles Discord (`123,456`)

Exemple valide:

```text
Tank;2;key=tank
Healer;2;ip=true
DPS Melee;4;req=123456789012345678
Support;2;roles=234567890123456789,345678901234567890
```

Comportement validation:
- erreurs bloquantes (ex: `slots` invalide, ligne mal formée, spec vide) => HTTP 400 avec `detail.details.errors[]`.
- warnings non bloquants (ex: option inconnue ignorée) => succès HTTP 200 avec `spec_warnings[]` dans la réponse.
- normalisation automatique dashboard quand `content_type=ava_raid` (création/édition): suppression des variantes/doublons de `raid_leader`/`scout`, puis injection canonique de `raid_leader` (`slots=1`, `ip_required=false`, `required_role_ids=[]`) et `scout` (`slots=1`, `ip_required=false`, `required_role_ids` repris de la première entrée scout fournie dans la spec).
