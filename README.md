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
- Fermeture simple pour l'auteur ou le support, avec confirmation obligatoire.
- Historique technique des messages (création/édition/suppression) pour les tickets connus.

Commandes principales :
- `/ticket_panel_send`
- `/ticket_open`, `/ticket_close`
- `/ticket_type_set`, `/ticket_type_remove`
- `/ticket_config_mode`
- `/ticket_config_category`
- `/ticket_config_roles`
- `/ticket_config_open_style`

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

## Déploiement Railway
1. Push sur GitHub.
2. Créer un projet Railway depuis le repo.
3. Build command:
   - `pip install -r requirements.txt && pip install .`
4. Start command:
   - `python -m albionbot`
5. Ajouter les variables d'environnement puis redéployer.

---

## Licence
MIT (`LICENSE`)
