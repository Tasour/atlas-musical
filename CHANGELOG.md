# Changelog

Toutes les dates sont au format AAAA-MM-JJ.

## [Unreleased]

### Ajouté

- Bouton de téléchargement MP3 sur chaque piste de la liste.
- Endpoint `GET /api/download/{id}` avec nom de fichier lisible `Artiste - Titre.mp3`.

## [1.1.0] - 2026-10-24

### Ajouté

- Carte affective valence/arousal avec tension, confiance et ellipses.
- Filtres, presets d’usage, fiches détaillées et pistes proches.
- Annotations manuelles persistées dans SQLite.
- Exports SQLite, JSON et ZIP.
- Pipeline de téléchargement, features, scoring et validation.
- Intégration Omarchy optionnelle et thème adaptatif.
- Tests Python, lint Ruff et vérification JavaScript en CI.

### Modifié

- Identité publique de l’application : **Atlas Musical**.
- Documentation et packaging public sans médias ni données générées.
