# AlbionBot

Bot Discord + dashboard web pour gérer raids, balances/lootsplit, tickets, crafting et killboard.

## Fonctionnalités
- Gestion de raids (templates, ouverture, roster, signup/leave)
- Gestion de balance et actions banque
- Consultation des tickets
- Authentification Discord pour le dashboard
- Permissions par guilde (admin/roles/users)
- Crafting Assistant (catalogue craftable, multi-recettes, focus, RRR, presets)
- Killboard (trackers guild/player, polling, événements persistés, rendu image)

## Lancer le projet
1. Installer les dépendances Python.
2. Configurer les variables d'environnement (`.env.example`).
3. Lancer le backend et le bot.
4. Lancer le frontend dashboard (`web/dashboard`).

## Tests
- `pytest -q`
- `npm test -- --run` dans `web/dashboard` (si dépendances frontend installées)
