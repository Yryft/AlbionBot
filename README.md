# AlbionBot

Bot Discord + dashboard web pour gérer raids, balances/lootsplit, tickets et administration.

## Fonctionnalités
- Gestion de raids (templates, ouverture, roster, signup/leave)
- Gestion de balance et actions banque
- Consultation des tickets
- Authentification Discord pour le dashboard
- Permissions par guilde (admin/roles/users)
- Crafting Assistant (focus, recettes multi-recipes, RRR par localisation)

## Lancer le projet
1. Installer les dépendances Python.
2. Configurer les variables d'environnement (`.env.example`).
3. Lancer le backend et le bot.
4. Lancer le frontend dashboard (`web/dashboard`).

## Tests
Exécuter `pytest` à la racine.

## Crafting Assistant
- Endpoint backend: `GET /crafting/item/{id}?tier=&enchant=` (+ paramètres de spécialisations et localisation).
- Profil de spécialisations persisté par utilisateur via `GET/PUT /api/crafting/profile`.
- Données offline versionnées dans `web/backend/data/crafting/` (catalogue, recettes, coefficients, modifiers).
