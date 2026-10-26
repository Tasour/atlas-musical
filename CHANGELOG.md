# Changelog

Toutes les dates sont au format AAAA-MM-JJ.

## [Unreleased]

### Ajouté

- Clusters de similarité hiérarchiques : espace audio + affect, ACP, Ward multi-niveaux, stabilité bootstrap et nommage par tags dominants.
- Nouveau parcours linéaire en 5 étapes : brief, treemap de groupes, drill-down, short-list, décision.
- Short-list avec statuts, notes, comparaison 2-3 pistes et export JSON/CSV/Markdown avec crédits.
- Séparation inspecter/écouter, preview borné à 12 s, A/B séquentiel et lecteur simplifié.
- Export ZIP de la short-list avec MP3, sélection JSON et crédits ; suivi « licence vérifiée ».
- Comparateur A/B synchronisé (deux lecteurs, bascule instantanée) et état de recherche/filtres dans l’URL.
- Filtre, tri et fiche détaillée par cluster ; endpoint `GET /api/clusters`.
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
