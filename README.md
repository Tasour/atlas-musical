# Atlas Musical

[![CI](https://github.com/Tasour/atlas-musical/actions/workflows/ci.yml/badge.svg)](https://github.com/Tasour/atlas-musical/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](pyproject.toml)

> Assistant local de décision musicale : de nombreuses pistes à une musique choisie, créditée et exportable.

**EN —** Atlas Musical is a local-first decision assistant that narrows an instrumental library through hierarchical clusters, a five-step flow, a shortlist, A/B comparison and a license-aware export. Audio and generated library data are intentionally not part of this repository.

## Aperçu

Atlas Musical organise la recherche musicale en un parcours linéaire, avec une seule question par écran :

1. **Brief** (optionnel) : type de plan, durée, ton, boucle, dialogue.
2. **Explorer** : 4 à 6 grands groupes de similarité, en treemap, classés par compatibilité avec le brief.
3. **Affiner** : descente dans les sous-groupes puis les familles fines, avec carte affective du cohorte et facettes contextuelles.
4. **Short-list** : 5 à 15 candidates, statuts (à écouter / retenu / écarté / choisi), notes, comparaison de 2 à 3 pistes et A/B synchronisé.
5. **Décider** : analyse détaillée, hook de 12 s, points de coupe, licence et crédit, export de la sélection.

Les filtres et la recherche sont encodés dans l’URL (`#/group/c1?tag=Tension&tracks=1`), ce qui rend une exploration partageable et rejouable.

Autres fonctions :

- clusters hiérarchiques nommés automatiquement, avec stabilité bootstrap, silhouette et variance ACP ;
- carte valence/arousal, tension, confiance, arc temporel, chroma, tags et usages ;
- annotations manuelles stockées localement dans SQLite ;
- export de la short-list en JSON, CSV, fiche de décision Markdown ou pack ZIP (MP3 + crédits) ;
- suivi de vérification des licences dans la short-list ;
- export de la base complète en SQLite, JSON ou ZIP ;
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

L’analyse construit une hiérarchie de groupes : l’espace combine 24 descripteurs audio et les axes affectifs, sans utiliser les tags (ils servent au nommage). Une ACP réduit l’espace, Ward construit les niveaux, et la stabilité de chaque nœud est estimée par bootstrap. Le fichier `data/clusters.json` expose `roots`, `nodes`, `paths`, `assignments` et les métriques de stabilité.

```bash
python3 -m analysis.cluster              # recalcule la hiérarchie seule
python3 -m analysis.cluster --clusters 5 # impose un nombre de groupes racines
```

Dans l’interface, le treemap des groupes permet de zoomer de niveau en niveau jusqu’aux pistes. La méthode (ACP, Ward, silhouette, Jaccard bootstrap, nommage) est décrite dans [`METHODOLOGY.md`](METHODOLOGY.md). Le fichier `data/clusters.json` est local et ignoré par Git.

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
- `GET /api/library/summary` (métadonnées légères, features chargées à la demande)
- `GET /api/clusters`
- `GET /api/track/{id}`
- `GET /api/audio/{id}` (Range supporté)
- `GET /api/download/{id}` (MP3 en pièce jointe)
- `GET /api/export?format=sqlite|json|zip`
- `POST /api/export-selection` (ZIP de la short-list avec MP3 et crédits)
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
