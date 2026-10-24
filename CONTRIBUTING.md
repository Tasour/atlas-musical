# Contribuer

Les contributions sont bienvenues, en particulier pour la robustesse du pipeline, la lisibilité de l’interface et la documentation des limites du modèle.

## Environnement

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
pytest
ruff check .
node --check app/app.js
```

Pour travailler sur l’analyse complète, installer aussi les extras `analysis` et `download` :

```bash
python3 -m pip install -e ".[analysis,download]"
```

## Règles

- Garder l’application locale : ne pas ajouter de télémétrie ni d’appel réseau implicite.
- Ne jamais committer `audio/`, `work/`, `data/`, `CREDITS.md`, de secrets ou de chemins personnels.
- Ajouter ou adapter les tests pour toute modification du modèle, de l’API ou des exports.
- Conserver les scores dans leurs bornes documentées et mettre à jour `METHODOLOGY.md` si une formule change.
- Utiliser des messages de commit explicites, par exemple `fix: corriger la confiance de tempo`.

## Pull requests

Une PR doit décrire le problème, la solution et les vérifications effectuées. Les changements d’interface doivent inclure une capture ou une description du comportement avant/après.
