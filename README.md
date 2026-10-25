# Atlas Musical

[![CI](https://github.com/Tasour/atlas-musical/actions/workflows/ci.yml/badge.svg)](https://github.com/Tasour/atlas-musical/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](pyproject.toml)

> Carte affective locale pour explorer, filtrer et annoter une bibliothèque de musiques instrumentales.

**EN —** Atlas Musical is a local-first web app that maps instrumental tracks on a valence/arousal plane, with tension, confidence, tags, cue points and manual annotations. Audio and generated library data are intentionally not part of this repository.

## Aperçu

Atlas Musical transforme une collection de pistes en carte interactive pour choisir une ambiance, préparer un montage ou documenter un corpus :

- carte valence/arousal, couleur de tension et ellipse de confiance ;
- clusters de similarité nommés automatiquement et visualisés en bulles, avec filtre et tri dédiés ;
- filtres par famille, tags, BPM, durée, confiance et favoris ;
- presets d’usage cinéma (ouverture, transition, paysage, action, portrait, résolution) ;
- fiche détaillée : tonalité, arc temporel, hook, points de coupe, tags, usages, licence et pistes proches ;
- annotations manuelles stockées localement dans SQLite ;
- export SQLite, JSON ou ZIP depuis l’interface ;
- thème Omarchy optionnel, avec fallback neutre.

L’application ne « détecte » pas les émotions. Elle estime un **profil affectif perçu**, relatif au corpus, avec une confiance explicite. Les détails sont dans [`METHODOLOGY.md`](METHODOLOGY.md).

## Contenu du dépôt

Ce dépôt contient uniquement le code source et la documentation :

- `app/` : interface HTML/CSS/JS sans build ;
- `server.py` : API FastAPI et service des fichiers statiques ;
- `analysis/` : catalogue d’exemple, téléchargement, extraction de features, modèle et validation ;
- `launch.sh`, `install.sh` : lancement local et intégration Omarchy optionnelle ;
- `tests/`, `pyproject.toml`, CI GitHub Actions.

Ne sont **pas** versionnés :

- les MP3 et fichiers sources (`audio/`, `work/download/`) ;
- les WAV intermédiaires et le cache de features (`work/`) ;
- la base SQLite, les snapshots JSON et les exports (`data/`) ;
- `CREDITS.md`, généré localement par l’analyse.

Le catalogue public contient les métadonnées de 20 références d’exemple. `analysis/discover.py` permet d’en ajouter d’autres localement dans `data/catalog.local.json`, sans les publier. Les fichiers audio restent soumis aux licences de leurs auteurs ; consultez les pages source et `CREDITS.md` après génération.

## Démarrage rapide

Prérequis : Python 3.11+, `ffmpeg` et `yt-dlp` pour reconstruire un corpus audio.

```bash
git clone https://github.com/Tasour/atlas-musical.git
cd atlas-musical

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[analysis,download]"

python3 -m analysis.download
python3 -m analysis.analyze
python3 -m analysis.validate

python3 server.py
```

Ouvrir ensuite <http://127.0.0.1:8765/>.

`analysis.download` récupère les sources, normalise en WAV et encode les MP3 localement. `analysis.analyze` construit `data/library.sqlite`, `data/library.json`, `data/manifest.json`, `data/clusters.json` et `CREDITS.md`. `analysis.validate` produit `data/validation.json`.

### Étendre le catalogue localement

`analysis.discover` recherche sur YouTube des pistes instrumentales sous licence Creative Commons, filtre les doublons et écrit `data/catalog.local.json` (ignoré par Git). Le catalogue public n’est pas modifié.

```bash
python3 -m analysis.discover --target 50
python3 -m analysis.download
python3 -m analysis.analyze
python3 -m analysis.validate
```

Traiter par lots de 50 permet de valider la qualité avant de continuer. `analysis.download` et `analysis.analyze` sont incrémentaux : les pistes déjà traitées sont ignorées. Options utiles : `--family acoustique|cinematique|tropical|intense`, `--per-query`, `--workers`, `--min-duration`, `--max-duration`, `--min-views`, `--channels-only` (uniquement des chaînes d’auteurs CC de confiance), `--no-channels` (recherche seule). Par défaut, la découverte privilégie des chaînes d’auteurs CC puis complète par une recherche, en écartant les reprises, tutoriels et compilations.

### Clusters de similarité

L’analyse regroupe aussi les pistes par similarité et écrit `data/clusters.json`. Les groupes sont nommés à partir de leurs tags dominants (par exemple « Littoral », « Nuit/route », « Nostalgie & apaisement ») puis projetés en 2D pour être affichés comme des bulles. Dans l’interface, l’onglet **Clusters de similarité** permet de filtrer la bibliothèque en cliquant une bulle ; le cluster apparaît aussi dans la liste, la fiche détaillée et le tri.

```bash
python3 -m analysis.cluster              # recalcule les groupes seuls
python3 -m analysis.cluster --clusters 6 # impose un nombre de groupes
```

La méthode (Ward, silhouette, ACP, nommage) est décrite dans [`METHODOLOGY.md`](METHODOLOGY.md). Le fichier `data/clusters.json` est local et ignoré par Git.

### Lancer uniquement l’interface et l’API

```bash
python3 -m pip install -e .
python3 server.py
```

L’interface affiche une erreur explicite tant que `data/library.json` n’existe pas : c’est le comportement attendu sans corpus analysé.

### Omarchy

```bash
./install.sh   # installe le lanceur et l’icône
./launch.sh    # démarre le serveur si nécessaire et ouvre la webapp
```

`install.sh` est spécifique à Omarchy. `launch.sh` utilise `omarchy-launch-webapp` si disponible, sinon `xdg-open`. Le port peut être changé avec `ATLAS_PORT`.

## Structure

```text
.
├── app/                    interface statique
├── analysis/               catalogue, pipeline, modèle, validation
├── tests/                  tests unitaires et smoke tests
├── server.py               API FastAPI
├── launch.sh               démarrage local
├── install.sh              intégration Omarchy
├── METHODOLOGY.md          méthode, formules, limites, références
├── CONTRIBUTING.md
├── SECURITY.md
└── pyproject.toml
```

Les dossiers `audio/`, `data/` et `work/` sont créés à l’exécution et ignorés par Git.

## API locale

- `GET /api/health`
- `GET /api/library`
- `GET /api/track/{id}`
- `GET /api/audio/{id}` (Range supporté)
- `GET /api/download/{id}` (MP3 en pièce jointe)
- `GET /api/export?format=sqlite|json|zip`
- `POST /api/annotations`
- `DELETE /api/annotations/{id}`
- `GET /api/theme`
- `POST /api/scan`

Le serveur écoute uniquement sur `127.0.0.1` et ne possède pas d’authentification. Ne pas l’exposer sur un réseau public.

## Tests et qualité

```bash
python3 -m pip install -e ".[dev]"
pytest
ruff check .
node --check app/app.js
```

La CI GitHub Actions exécute les tests Python, `ruff` et la vérification syntaxique du JavaScript à chaque push et pull request.

## Données et limites

- Les scores sont relatifs au corpus analysé et ne constituent pas une mesure clinique.
- La valence est généralement moins stable que l’arousal ; les ellipses rendent cette incertitude visible.
- Les tags et les usages sont des propositions à valider à l’écoute.
- Les annotations manuelles remplacent les valeurs automatiques sur la carte.
- Une licence Creative Commons n’exclut pas une revendication Content ID : vérifier les droits avant publication monétisée.

## Licence

Le code de ce dépôt est distribué sous licence MIT (voir [`LICENSE`](LICENSE)). Les œuvres musicales et leurs métadonnées conservent leurs licences respectives. Aucun fichier audio n’est distribué ici.
