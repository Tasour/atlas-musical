# Méthodologie — Atlas Musical

## Objet

Cette bibliothèque sert à choisir rapidement une musique instrumentale pour un plan vidéo. L’application ne « détecte » pas des émotions : elle estime un **profil affectif perçu** et le rend explicite, avec une confiance et des limites. Les scores sont relatifs aux 20 pistes du corpus.

## Corpus et formats

- 20 pistes instrumentales, quatre familles éditoriales : acoustique/folk, cinématique/ambient, tropical/chill, intense/aventure.
- Source : YouTube, téléchargement via `yt-dlp`.
- Analyse sur un WAV 48 kHz stéréo, normalisé à −16 LUFS (TP −1,5 dBTP) avec `loudnorm` en deux passes.
- Sortie locale : MP3 320 kb/s, 48 kHz, stéréo, tags ID3, crédits et licence inclus.
- Le dépôt public ne contient ni les MP3 ni la base ; ils sont générés localement par le pipeline.
- La normalisation limite les biais de mastering et de codec, mais ne les supprime pas.

## Coordonnées

- Axe horizontal : **arousal** (calme → énergique).
- Axe vertical : **valence** (mélancolique → solaire).
- Couleur : **tension** (résolution → attente).
- Taille et ellipse : **confiance** (plus la confiance est basse, plus l’ellipse est large).

La carte est une lecture opérationnelle du circumplex de Russell (1980), enrichie d’une dimension de tension (Huron, 2006 ; Eerola & Vuoskoski, 2011). Elle ne prétend pas mesurer une émotion ressentie.

## Pipeline

1. Décodage et normalisation du fichier source.
2. Extraction de descripteurs par frames (STFT 2048, hop 512, 22 050 Hz pour l’analyse).
3. Agrégation robuste (moyennes, écarts-types, percentiles) et features temporelles.
4. Standardisation médiane/MAD sur le corpus, puis calcul des scores.
5. Attribution de tags multi-étiquettes et de scores d’usage cinéma.
6. Écriture de `data/library.sqlite` (canonique), `data/library.json` (snapshot) et `data/validation.json` (stabilité).

## Clusters de similarité

Les groupes sont calculés sur un espace **audio + affect** : 24 descripteurs acoustiques et valence/arousal/tension, standardisés robustement (médiane/MAD, winsorisation), équilibrés par bloc, puis réduits par ACP (six composantes). Les tags ne servent **pas** au clustering : ils servent au nommage et à la lecture.

Une classification ascendante hiérarchique de Ward construit un seul dendrogramme, coupé en 4 à 6 groupes racines (silhouette, taille minimale), puis découpé récursivement en sous-groupes jusqu’à trois niveaux. Les enfants sont toujours des sous-ensembles exacts du parent : le zoom ne recalcule pas une partition concurrente.

La stabilité est estimée par bootstrap : 100 rééchantillonnages à 80 % pour les racines, 60 locaux pour les sous-groupes, avec Jaccard par nœud et ARI global. `data/clusters.json` expose `roots`, `nodes`, `paths`, `assignments`, `stability`, `silhouette` et la variance expliquée de l’ACP.

Chaque nœud est nommé par ses tags les plus surreprésentés, avec une prévalence minimale et un lift positif. Les noms restent descriptifs : ils résument des proximités dans l’espace de features, pas des genres musicaux validés. Ils doivent être vérifiés à l’écoute.

## Parcours et score de compatibilité

Le brief est un filtre de préférence, pas une vérité : le score de compatibilité combine l’usage cinéma estimé (35 %), la proximité de valence (25 %) et d’arousal (20 %) avec le ton demandé, la durée du plan (10 %) et la boucle (10 % si le plan boucle). Ces poids sont fixes et affichés ; ils ne sont pas appris sur les annotations.

Les groupes sont présentés du plus compatible au moins compatible, mais leur surface reste proportionnelle au nombre de pistes. Le score sert à ordonner, jamais à masquer l’incertitude.

## Descripteurs

- **Rythme** : tempo, clarté de pulse (concentration du tempogramme 40–200 BPM, `(pic − moyenne)/pic`), confiance de tempo (`1,2 × clarté`, bornée), nombre de temps, taux d’onsets.
- **Dynamique** : RMS, plage dynamique (P95−P10), crest factor.
- **Timbre** : centroïde, bande passante, rolloff 85 %, flatness, contraste spectral, ZCR, flux spectral, ratios basse/médium/aigu.
- **Harmonie** : chroma CQT, tonalité par corrélation avec les profils majeurs/mineurs de Krumhansl (1982), marge entre les deux meilleures corrélations, entropie chromatique, tonnetz.
- **Texture** : ratio harmonique/percussif (HPSS), rugosité de Plomp-Levelt/Sethares sur les pics spectraux, largeur stéréo mid/side.
- **Forme** : arc RMS en 12 segments, intro/pic/sortie, hook de 12 s, points de coupe sur les temps, loopabilité (similarité chroma début/fin + clarté de pulse + stabilité RMS).
- **Corpus** : famille éditoriale comme prior faible, jamais comme vérité.

## Scores

Les features sont standardisées par `z = clip((x − médiane) / (1,4826 × MAD), −3, 3)`. Les poids sont fixés a priori ; aucun modèle supervisé n’est entraîné sur 20 exemples.

```text
A = tanh(0,95 × (
      0,24·z_tempo + 0,16·z_onsets + 0,13·z_flux + 0,12·z_centroïde
    + 0,10·z_percussif + 0,08·z_crest + 0,06·z_dynamique
    + 0,05·z_basses + 0,04·z_pulse + 0,30·prior_famille
))

V = tanh(0,90 × (
      0,28·mode×confiance_tonale + 0,14·z_harmonie − 0,14·z_rugosité
    + 0,10·z_pulse + 0,08·stabilité_dynamique − 0,06·z_flatness
    + 0,24·prior_famille
))

T = tanh(0,85 × (
      0,30·z_rugosité + 0,20·z_entropie_harmonique + 0,18·z_hors_tonalité
    + 0,12·z_flux − 0,10·z_pulse + 0,10·|z_flatness|
    + 0,04·z_centroïde + 0,20·prior_famille
))
```

Les scores sont dans `[−1, 1]`. Les valeurs `valence01`, `arousal01`, `tension01` sont les remises à l’échelle `[0, 1]` utilisées par la carte.

### Confiance

```text
confiance = clip(0,18 + 0,30·confiance_tempo + 0,34·confiance_tonale
                 + 0,10·(1 − |z_rugosité|/3), 0, 1)
```

La confiance baisse pour les pistes courtes (< 30 s). L’ellipse a un rayon de base de 0,045, augmenté quand la confiance baisse. Une ellipse large signifie « vérifier à l’écoute », pas « score faux ».

## Tags

Tags d’émotion : Joie, Tristesse, Nostalgie, Tension, Aventure, Apaisement, Émerveillement, Intimité, Romance, Énergie.
Tags de texture : Ambiance, Instrumental.
Tags de contexte : Littoral, Aride/outback, Brousse, Nuit/route.

Les scores bruts de tags combinent arousal, valence, tension, harmonicité, largeur stéréo, acousticness, pulse et taux d’onsets, avec un prior de famille (par exemple `Aventure`/`Énergie` pour la famille intense, `Joie` pour la famille tropicale). Pour éviter qu’un tag domine tout le corpus, chaque tag est ensuite calibré par min-max sur les 20 pistes vers `[0,15 ; 0,95]`. Les tags retenus sont les scores calibrés ≥ 0,62 (max. 4), puis le contexte et `Instrumental`. Pour la famille « intense », `Romance` et `Apaisement` sont exclus des tags automatiques afin d’éviter des étiquettes contre-intuitives ; l’annotation manuelle reste possible. Les scores complets restent disponibles dans la base et le JSON ; ils sont relatifs au corpus.

## Usages cinéma

Six fonctions : Ouverture, Transition, Paysage/drone, Portrait/intime, Action/montage, Résolution/générique. Chaque fonction est une combinaison de wonder, ambience, adventure, intimacy, nostalgia, calm, loopability et tension, calibrée par min-max sur le corpus. Les usages retenus sont les scores ≥ 0,65 (max. 3). Ce sont des **aides au choix**, pas des prescriptions de montage.

## Validation et incertitude

- `analysis/validate.py` réalise 240 bootstraps du corpus et un leave-one-out.
- `data/validation.json` contient l’écart-type bootstrap, le delta leave-one-out et, si disponibles, les corrélations avec les annotations manuelles (MAE, Spearman).
- Les annotations manuelles sont stockées dans `annotations` et remplacent les valeurs auto sur la carte. Elles ne réécrivent pas les features.
- Avec 20 pistes, la stabilité des rangs est plus informative que la valeur absolue d’un score.
- Résultats du corpus actuel (240 bootstraps) : écart-type moyen valence `0,090`, arousal `0,162`, tension `0,147` ; delta LOO moyen valence `0,037`, arousal `0,046`, tension `0,045`.

## Limites assumées

- Valence moins fiable que arousal, surtout sur les drones, le didgeridoo, les textures non tempérées et les pièces modales.
- Les profils de tonalité sont issus de la musique tonale occidentale ; leur application à d’autres traditions est une approximation signalée par la confiance.
- La perception est individuelle et culturelle ; le corpus est petit et non représentatif.
- Les tags ne sont pas des diagnostics et ne doivent pas être utilisés pour des décisions cliniques.
- Content ID peut revendiquer une piste même sous licence Creative Commons : conserver les crédits, la source et la date de téléchargement.

## Reproductibilité

```bash
python3 analysis/download.py
python3 analysis/analyze.py
python3 analysis/validate.py
```

Versions : Python 3.14, librosa 1.0.0, scipy 1.18.1, scikit-learn 1.9.1, soundfile 0.14.0, mutagen 1.48.1, uvicorn 0.54.0, ffmpeg 9.0.2, yt-dlp 2026.08.19. Version du pipeline de features : 1.1.

## Références

- Russell, J. A. (1980). A circumplex model of affect. *Journal of Personality and Social Psychology*.
- Krumhansl, C. L. (1982). Key-finding profiles. *Psychological Review*.
- Plomp, R., & Levelt, W. J. M. (1965). Tonal consonance and critical bandwidth. *Journal of the Acoustical Society of America*.
- Sethares, W. A. (1993). Local consonance and the relationship between timbre and scale. *Journal of the Acoustical Society of America*.
- Eerola, T., & Vuoskoski, J. K. (2011). A comparison of the discrete and dimensional models of emotion in music. *Psychology of Music*.
- Zentner, M., Grandjean, D., & Scherer, K. R. (2008). Emotions evoked by the sound of music: Characterization, classification, and measurement. *Emotion*.
- Huron, D. (2006). *Sweet Anticipation: Music and the Psychology of Expectation*. MIT Press.
- McFee, B., et al. (2015). librosa: Audio and music signal analysis in Python.
