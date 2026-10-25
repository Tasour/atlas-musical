#!/usr/bin/env python3
"""Regroupe les pistes par similarité, nomme les groupes et les projette en 2D.

Le clustering utilise les scores de tags, les axes affectifs et quelques
descripteurs acoustiques. Une classification ascendante hiérarchique (Ward)
est coupée au nombre de groupes qui maximise la silhouette. Les groupes sont
ensuite nommés à partir de leurs tags dominants et de leur climat affectif,
puis positionnés dans un plan ACP pour être affichés comme des bulles.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist, squareform

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LIB_JSON = DATA / "library.json"
CLUSTERS_JSON = DATA / "clusters.json"

FAMILY_SHORT = {
    "acoustique": "Acoustique",
    "cinematique": "Cinématique",
    "tropical": "Tropical",
    "intense": "Intense",
}

PALETTE = [
    "hsl(205 55% 62%)",
    "hsl(158 45% 58%)",
    "hsl(38 70% 62%)",
    "hsl(12 60% 62%)",
    "hsl(275 45% 66%)",
    "hsl(190 55% 62%)",
    "hsl(95 40% 58%)",
    "hsl(330 45% 64%)",
    "hsl(240 45% 66%)",
]

# Poids relatifs des blocs de variables dans l'espace de similarité.
WEIGHTS = {
    "tags": 1.0,
    "affect": 0.85,
    "energy": 0.55,
    "bpm": 0.35,
    "acousticness": 0.35,
    "danceability": 0.35,
}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _zscore(matrix: np.ndarray) -> np.ndarray:
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std = np.where(std < 1e-9, 1.0, std)
    return (matrix - mean) / std


def _feature_matrix(tracks: list[dict], tag_names: list[str]) -> np.ndarray:
    rows: list[list[float]] = []
    for track in tracks:
        scores = track.get("tag_scores") or {}
        tags = [float(scores.get(name) or 0.0) for name in tag_names]
        affect = [
            float(track.get("valence") or 0.0),
            float(track.get("arousal") or 0.0),
            float(track.get("tension") or 0.0),
        ]
        extras = [
            float(track.get("energy") or 0.0),
            float(track.get("bpm") or 0.0),
            float(track.get("acousticness") or 0.0),
            float(track.get("danceability") or 0.0),
        ]
        rows.append(tags + affect + extras)
    matrix = np.asarray(rows, dtype=float)
    if len(matrix) > 2:
        matrix = _zscore(matrix)
    weights = np.asarray(
        [WEIGHTS["tags"]] * len(tag_names)
        + [WEIGHTS["affect"]] * 3
        + [
            WEIGHTS["energy"],
            WEIGHTS["bpm"],
            WEIGHTS["acousticness"],
            WEIGHTS["danceability"],
        ]
    )
    return matrix * weights


def _silhouette(distances: np.ndarray, labels: np.ndarray) -> float:
    unique = np.unique(labels)
    if len(unique) < 2 or len(unique) >= len(labels):
        return -1.0
    scores: list[float] = []
    for index in range(len(labels)):
        own = labels == labels[index]
        own[index] = False
        if not own.any():
            scores.append(0.0)
            continue
        a = float(distances[index, own].mean())
        b = min(
            float(distances[index, labels == label].mean())
            for label in unique
            if label != labels[index]
        )
        denominator = max(a, b)
        scores.append((b - a) / denominator if denominator > 1e-9 else 0.0)
    return float(np.mean(scores))


def _choose_labels(matrix: np.ndarray, requested: int | None) -> tuple[np.ndarray, int, float]:
    count = len(matrix)
    if count < 3:
        return np.ones(count, dtype=int), 1, 0.0
    distances = squareform(pdist(matrix, metric="euclidean"))
    if requested and 2 <= requested < count:
        labels = fcluster(linkage(matrix, method="ward"), requested, criterion="maxclust")
        return labels.astype(int), requested, _silhouette(distances, labels)

    tree = linkage(matrix, method="ward")
    k_max = min(9, count - 1)
    min_size = max(3, int(round(count * 0.015)))
    best: tuple[float, int, np.ndarray] | None = None
    for k in range(3, k_max + 1):
        labels = fcluster(tree, k, criterion="maxclust").astype(int)
        sizes = np.bincount(labels)[1:]
        if sizes.size < 2 or sizes.min() < min_size:
            continue
        score = _silhouette(distances, labels)
        if best is None or score > best[0]:
            best = (score, k, labels)
    if best is None:
        labels = fcluster(tree, 2, criterion="maxclust").astype(int)
        return labels, 2, _silhouette(distances, labels)
    return best[2], best[1], best[0]


def _pca_2d(matrix: np.ndarray) -> np.ndarray:
    centered = matrix - matrix.mean(axis=0)
    try:
        left, singular, _ = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return np.zeros((len(matrix), 2))
    coords = left[:, :2] * singular[:2]
    if coords.shape[1] == 1:
        coords = np.column_stack([coords[:, 0], np.zeros(len(coords))])
    low = coords.min(axis=0)
    span = float((coords.max(axis=0) - low).max()) or 1.0
    coords = (coords - low) / span
    coords = 0.12 + coords * 0.76
    return np.clip(coords, 0.02, 0.98)


def _relax(centroids: np.ndarray, radii: np.ndarray) -> np.ndarray:
    positions = centroids.copy()
    count = len(positions)
    for _ in range(260):
        push = np.zeros_like(positions)
        for i in range(count):
            for j in range(i + 1, count):
                delta = positions[j] - positions[i]
                distance = float(np.linalg.norm(delta))
                minimum = radii[i] + radii[j] + 0.015
                if distance < 1e-9:
                    delta = np.array([0.001, 0.001])
                    distance = float(np.linalg.norm(delta))
                if distance < minimum:
                    unit = delta / distance
                    amount = (minimum - distance) / 2
                    push[i] -= unit * amount
                    push[j] += unit * amount
        positions += push + 0.015 * (centroids - positions)
        for i in range(count):
            positions[i] = np.clip(positions[i], radii[i] + 0.02, 0.98 - radii[i])
    return positions


def _descriptor(valence: float, arousal: float, tension: float) -> str:
    if valence >= 0.05 and arousal >= 0.05:
        label = "solaire et énergique"
    elif valence >= 0.05:
        label = "lumineux et posé"
    elif arousal >= 0.05:
        label = "sombre et énergique"
    else:
        label = "mélancolique et calme"
    if tension >= 0.35:
        label += " · tendu"
    return label


def _cluster_names(
    tracks: list[dict],
    labels: np.ndarray,
    tag_names: list[str],
    clusters: list[dict],
) -> None:
    global_tags = {
        name: float(np.mean([float((t.get("tag_scores") or {}).get(name) or 0) for t in tracks]))
        for name in tag_names
    }
    used: set[str] = set()
    for cluster in clusters:
        members = [tracks[i] for i in np.where(labels == cluster["_label"])[0]]
        sizes = Counter(t.get("family") for t in members)
        family, count = sizes.most_common(1)[0]
        share = count / max(1, len(members))
        valence = float(np.mean([float(t.get("valence") or 0) for t in members]))
        arousal = float(np.mean([float(t.get("arousal") or 0) for t in members]))
        tension = float(np.mean([float(t.get("tension") or 0) for t in members]))
        tag_means = {
            name: float(np.mean([float((t.get("tag_scores") or {}).get(name) or 0) for t in members]))
            for name in tag_names
        }
        ranked = sorted(
            (name for name in tag_names if name != "Instrumental"),
            key=lambda name: (tag_means[name] - global_tags[name], tag_means[name]),
            reverse=True,
        )
        first = ranked[0]
        second = ranked[1] if len(ranked) > 1 else first
        lift = tag_means[first] - global_tags[first]
        base = first if lift >= 0.5 or tag_means[first] >= 0.85 else f"{first} & {second.lower()}"
        name = base
        if name in used:
            name = f"{base} · {_descriptor(valence, arousal, tension)}"
        suffix = 2
        while name in used:
            name = f"{base} ({suffix})"
            suffix += 1
        used.add(name)
        cluster["name"] = name
        mix = (
            f"majorité {FAMILY_SHORT.get(family, family)}"
            if share >= 0.4
            else "familles mixtes"
        )
        cluster["description"] = (
            f"{len(members)} pistes · {mix} · {', '.join(ranked[:3])} · "
            f"valence {valence:+.2f}, énergie {arousal:+.2f}, tension {tension:+.2f}"
        )
        cluster["affect"] = {
            "valence": round(valence, 4),
            "arousal": round(arousal, 4),
            "tension": round(tension, 4),
        }
        cluster["families"] = dict(sizes)
        cluster["top_tags"] = [
            {
                "name": tag_name,
                "score": round(tag_means[tag_name], 4),
                "lift": round(tag_means[tag_name] - global_tags[tag_name], 4),
            }
            for tag_name in ranked[:4]
        ]


def build_clusters(library: dict, k: int | None = None) -> dict:
    tracks = library.get("tracks") or []
    tag_names = [tag.get("name") for tag in library.get("tags") or [] if tag.get("name")]
    if not tracks or not tag_names:
        raise ValueError("Bibliothèque vide ou tags absents")
    matrix = _feature_matrix(tracks, tag_names)
    labels, chosen_k, silhouette = _choose_labels(matrix, k)
    coords = _pca_2d(matrix)

    raw_clusters: list[dict] = []
    for label in sorted(set(labels.tolist())):
        members = np.where(labels == label)[0]
        centroid = coords[members].mean(axis=0)
        spread = float(np.linalg.norm(coords[members] - centroid, axis=1).mean()) * 0.7
        raw_clusters.append(
            {
                "_label": int(label),
                "_members": members,
                "_centroid": centroid,
                "size": int(len(members)),
                "spread": round(float(np.clip(spread, 0.015, 0.15)), 4),
            }
        )

    largest = max(cluster["size"] for cluster in raw_clusters)
    for cluster in raw_clusters:
        cluster["r"] = round(0.045 + 0.075 * float(np.sqrt(cluster["size"] / largest)), 4)
    radii = np.array([cluster["r"] for cluster in raw_clusters])
    centroids = np.array([cluster["_centroid"] for cluster in raw_clusters])
    positions = _relax(centroids, radii) if len(raw_clusters) > 1 else centroids

    clusters: list[dict] = []
    for index, cluster in enumerate(raw_clusters):
        cluster["id"] = f"c{index + 1}"
        cluster["color"] = PALETTE[index % len(PALETTE)]
        cluster["x"] = round(float(positions[index][0]), 4)
        cluster["y"] = round(float(positions[index][1]), 4)
        cluster["track_ids"] = [tracks[i]["id"] for i in cluster["_members"]]
        clusters.append(cluster)

    _cluster_names(tracks, labels, tag_names, clusters)

    cleaned: list[dict] = []
    assignments: dict[str, str] = {}
    for cluster in clusters:
        for track_id in cluster["track_ids"]:
            assignments[track_id] = cluster["id"]
        cleaned.append(
            {
                key: value
                for key, value in cluster.items()
                if not key.startswith("_")
            }
        )

    return {
        "generated_at": now(),
        "method": "ward",
        "k": int(chosen_k),
        "silhouette": round(float(silhouette), 4),
        "corpus_size": len(tracks),
        "features": tag_names
        + ["valence", "arousal", "tension", "energy", "bpm", "acousticness", "danceability"],
        "clusters": cleaned,
        "assignments": assignments,
    }


def write_clusters(payload: dict) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CLUSTERS_JSON.with_name(f"{CLUSTERS_JSON.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CLUSTERS_JSON)
    return CLUSTERS_JSON


def build_and_write(library: dict, k: int | None = None) -> dict:
    payload = build_clusters(library, k=k)
    write_clusters(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clusters", type=int, default=None, help="nombre de groupes imposé")
    args = parser.parse_args()
    if not LIB_JSON.exists():
        print("Bibliothèque absente : lancer analysis/analyze.py.", file=sys.stderr)
        return 2
    library = json.loads(LIB_JSON.read_text(encoding="utf-8"))
    payload = build_and_write(library, k=args.clusters)
    print(
        f"OK : {payload['k']} groupes, silhouette {payload['silhouette']:+.3f}, "
        f"{payload['corpus_size']} pistes"
    )
    for cluster in payload["clusters"]:
        print(f"  {cluster['id']:>3} · {cluster['size']:>3} pistes · {cluster['name']}")
    print(f"JSON : {CLUSTERS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
