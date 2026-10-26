#!/usr/bin/env python3
"""Construit une hiérarchie de groupes de pistes par similarité.

Le clustering utilise des descripteurs audio et les trois axes affectifs, jamais
les tags (qui servent uniquement au nommage). Une classification ascendante
hiérarchique de Ward est coupée en plusieurs niveaux imbriqués : groupes,
sous-groupes, sous-sous-groupes. La stabilité de chaque nœud est estimée par
bootstrap (Jaccard), puis les groupes sont nommés à partir des tags dominants.
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
from scipy.special import comb

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

AUDIO_FEATURES = [
    "tempo",
    "pulse_clarity",
    "onset_rate",
    "rms_db",
    "dynamic_range_db",
    "crest_db",
    "spectral_centroid",
    "spectral_bandwidth",
    "spectral_rolloff",
    "spectral_flatness",
    "spectral_flux",
    "zcr",
    "roughness",
    "harmonic_entropy",
    "harmonic_ratio",
    "percussive_ratio",
    "bass_ratio",
    "mid_ratio",
    "high_ratio",
    "stereo_width",
    "acousticness",
    "danceability",
    "energy",
    "loopability",
]
LOG_FEATURES = {
    "tempo",
    "spectral_centroid",
    "spectral_bandwidth",
    "spectral_rolloff",
}
AUDIO_WEIGHT = 1.0
AFFECT_WEIGHT = 0.9
BOOTSTRAP_ITERATIONS = 100
LOCAL_BOOTSTRAP_ITERATIONS = 60
MAX_DEPTH = 3


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _robust_z(matrix: np.ndarray) -> np.ndarray:
    median = np.median(matrix, axis=0)
    mad = np.median(np.abs(matrix - median), axis=0) * 1.4826
    std = matrix.std(axis=0)
    scale = np.where(mad < 1e-9, np.where(std < 1e-9, 1.0, std), mad)
    return np.clip((matrix - median) / scale, -3.0, 3.0)


def _feature_matrix(tracks: list[dict]) -> tuple[np.ndarray, list[str]]:
    rows: list[list[float]] = []
    for track in tracks:
        features = track.get("features") or {}
        audio = []
        for name in AUDIO_FEATURES:
            value = float(features.get(name) or 0.0)
            if name in LOG_FEATURES:
                value = float(np.log1p(max(0.0, value)))
            audio.append(value)
        affect = [
            float(track.get("valence") or 0.0),
            float(track.get("arousal") or 0.0),
            float(track.get("tension") or 0.0),
        ]
        rows.append(audio + affect)
    matrix = _robust_z(np.asarray(rows, dtype=float))
    audio_block = matrix[:, : len(AUDIO_FEATURES)] / np.sqrt(len(AUDIO_FEATURES))
    affect_block = matrix[:, len(AUDIO_FEATURES) :] / np.sqrt(3)
    combined = np.hstack([audio_block * AUDIO_WEIGHT, affect_block * AFFECT_WEIGHT])
    return combined, AUDIO_FEATURES + ["valence", "arousal", "tension"]


def _pca(matrix: np.ndarray, components: int = 6) -> tuple[np.ndarray, list[float]]:
    centered = matrix - matrix.mean(axis=0)
    try:
        left, singular, _ = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return centered[:, :2], []
    dimensions = min(components, len(singular))
    variance = singular**2
    total = float(variance.sum()) or 1.0
    scores = left[:, :dimensions] * singular[:dimensions]
    return scores, [round(float(value / total), 4) for value in variance[:dimensions]]


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


def _ari(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2:
        return 1.0
    _, left_ids = np.unique(left, return_inverse=True)
    _, right_ids = np.unique(right, return_inverse=True)
    contingency = np.zeros((left_ids.max() + 1, right_ids.max() + 1), dtype=float)
    for row, col in zip(left_ids, right_ids, strict=True):
        contingency[row, col] += 1
    sum_cells = float(comb(contingency, 2).sum())
    rows = float(comb(contingency.sum(axis=1), 2).sum())
    cols = float(comb(contingency.sum(axis=0), 2).sum())
    total = float(comb(len(left), 2))
    expected = rows * cols / total if total else 0.0
    maximum = (rows + cols) / 2
    if maximum - expected < 1e-12:
        return 1.0
    return float((sum_cells - expected) / (maximum - expected))


def _choose_k(matrix: np.ndarray, requested: int | None = None) -> tuple[np.ndarray, int, float]:
    count = len(matrix)
    if count < 4:
        return np.ones(count, dtype=int), 1, 0.0
    distances = squareform(pdist(matrix, metric="euclidean"))
    tree = linkage(matrix, method="ward")
    if requested and 2 <= requested < count:
        labels = fcluster(tree, requested, criterion="maxclust").astype(int)
        return labels, requested, _silhouette(distances, labels)

    k_min = 2 if count < 20 else 4
    k_max = min(6, count - 1)
    min_size = max(3, int(round(count * 0.06)))
    best: tuple[float, int, np.ndarray] | None = None
    for k in range(k_min, k_max + 1):
        labels = fcluster(tree, k, criterion="maxclust").astype(int)
        sizes = np.bincount(labels)[1:]
        if sizes.size < 2 or sizes.min() < min_size:
            continue
        score = _silhouette(distances, labels)
        if best is None or score > best[0]:
            best = (score, k, labels)
    if best is not None:
        return best[2], best[1], best[0]

    for k in range(2, k_max + 1):
        labels = fcluster(tree, k, criterion="maxclust").astype(int)
        sizes = np.bincount(labels)[1:]
        if sizes.size < 2 or sizes.min() < 3:
            continue
        score = _silhouette(distances, labels)
        if best is None or score > best[0]:
            best = (score, k, labels)
    if best is None:
        labels = fcluster(tree, 2, criterion="maxclust").astype(int)
        return labels, 2, _silhouette(distances, labels)
    return best[2], best[1], best[0]


def _local_stability(
    matrix: np.ndarray,
    indices: np.ndarray,
    labels: np.ndarray,
    iterations: int = LOCAL_BOOTSTRAP_ITERATIONS,
    seed: int = 42,
) -> dict[int, float]:
    if len(indices) < 6 or len(set(labels.tolist())) < 2:
        return {}
    rng = np.random.default_rng(seed)
    unique = sorted(set(labels.tolist()))
    scores: dict[int, list[float]] = {label: [] for label in unique}
    sample_size = max(4, int(round(len(indices) * 0.8)))
    for _ in range(iterations):
        sample = rng.choice(len(indices), size=sample_size, replace=False)
        sub = matrix[indices[sample]]
        try:
            k = len(unique)
            sub_labels = fcluster(linkage(sub, method="ward"), k, criterion="maxclust").astype(int)
        except ValueError:
            continue
        for label in unique:
            reference = set(np.where(labels == label)[0].tolist())
            best = 0.0
            for candidate in set(sub_labels.tolist()):
                candidate_set = set(np.where(sub_labels == candidate)[0].tolist())
                union = reference | candidate_set
                if union:
                    best = max(best, len(reference & candidate_set) / len(union))
            scores[label].append(best)
    return {
        label: round(float(np.mean(values)), 4) if values else 0.0
        for label, values in scores.items()
    }


def _global_stability(
    matrix: np.ndarray,
    labels: np.ndarray,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = 42,
) -> tuple[dict[int, float], float]:
    unique = sorted(set(labels.tolist()))
    if len(unique) < 2:
        return {}, 1.0
    rng = np.random.default_rng(seed)
    scores: dict[int, list[float]] = {label: [] for label in unique}
    aris: list[float] = []
    sample_size = max(6, int(round(len(matrix) * 0.8)))
    for _ in range(iterations):
        sample = rng.choice(len(matrix), size=sample_size, replace=False)
        sub = matrix[sample]
        try:
            sub_labels = fcluster(
                linkage(sub, method="ward"), len(unique), criterion="maxclust"
            ).astype(int)
        except ValueError:
            continue
        aris.append(_ari(labels[sample], sub_labels))
        for label in unique:
            reference = set(np.where(labels == label)[0].tolist())
            best = 0.0
            for candidate in set(sub_labels.tolist()):
                candidate_set = set(np.where(sub_labels == candidate)[0].tolist())
                union = reference | candidate_set
                if union:
                    best = max(best, len(reference & candidate_set) / len(union))
            scores[label].append(best)
    per_cluster = {
        label: round(float(np.mean(values)), 4) if values else 0.0
        for label, values in scores.items()
    }
    return per_cluster, round(float(np.mean(aris)), 4) if aris else 0.0


def _descriptor(valence: float, arousal: float, tension: float) -> str:
    if tension >= 0.3:
        return "tendu"
    if arousal >= 0.3:
        return "énergique"
    if valence >= 0.25:
        return "lumineux"
    if valence <= -0.25:
        return "sombre"
    return "apaisé"


def _node_stats(tracks: list[dict], members: np.ndarray, tag_names: list[str]) -> dict:
    rows = [tracks[index] for index in members]
    families = Counter(track.get("family") for track in rows)
    valence = float(np.mean([float(track.get("valence") or 0) for track in rows]))
    arousal = float(np.mean([float(track.get("arousal") or 0) for track in rows]))
    tension = float(np.mean([float(track.get("tension") or 0) for track in rows]))
    tag_means = {
        name: float(
            np.mean([float((track.get("tag_scores") or {}).get(name) or 0) for track in rows])
        )
        for name in tag_names
    }
    prevalence = {
        name: sum(1 for track in rows if name in (track.get("tags") or [])) / max(1, len(rows))
        for name in tag_names
    }
    return {
        "families": dict(families),
        "valence": valence,
        "arousal": arousal,
        "tension": tension,
        "tag_means": tag_means,
        "prevalence": prevalence,
        "top_tags": sorted(
            (name for name in tag_names if name != "Instrumental"),
            key=lambda name: (tag_means[name], prevalence[name]),
            reverse=True,
        ),
    }


def _name_node(stats: dict, global_tags: dict[str, float], used: set[str]) -> str:
    candidates = [
        name
        for name in stats["top_tags"]
        if name != "Instrumental"
        and stats["prevalence"][name] >= 0.2
        and (stats["tag_means"][name] - global_tags.get(name, 0)) >= 0.0
    ]
    if not candidates:
        candidates = [name for name in stats["top_tags"] if name != "Instrumental"][:1]
    first = candidates[0] if candidates else "Groupe"
    second = candidates[1] if len(candidates) > 1 else None
    descriptor = _descriptor(stats["valence"], stats["arousal"], stats["tension"])
    if second and stats["prevalence"][second] >= 0.25:
        base = f"{first} & {second.lower()}"
    else:
        base = f"{first} · {descriptor}"
    name = base
    if name in used:
        for alternative in candidates[2:]:
            candidate = f"{first} & {alternative.lower()}"
            if candidate not in used:
                name = candidate
                break
    if name in used:
        name = f"{first} · {descriptor}"
    if name in used and second:
        name = f"{first} & {second.lower()} · {descriptor}"
    suffix = 2
    while name in used:
        name = f"{base} ({suffix})"
        suffix += 1
    used.add(name)
    return name


def _build_nodes(
    tracks: list[dict],
    matrix: np.ndarray,
    indices: np.ndarray,
    tag_names: list[str],
    global_tags: dict[str, float],
    used_names: set[str],
    level: int,
    parent: str | None,
    prefix: str,
) -> tuple[list[dict], dict[str, str], dict[str, list[str]]]:
    labels, k, score = _choose_k(matrix[indices])
    clusters: list[dict] = []
    assignments: dict[str, str] = {}
    paths: dict[str, list[str]] = {}

    for local_label in sorted(set(labels.tolist())):
        local_members = np.where(labels == local_label)[0]
        members = indices[local_members]
        node_id = f"{prefix}{local_label}"
        stats = _node_stats(tracks, members, tag_names)
        node = {
            "id": node_id,
            "parent": parent,
            "level": level,
            "name": _name_node(stats, global_tags, used_names),
            "size": int(len(members)),
            "stability": None,
            "silhouette": None,
            "children": [],
            "track_ids": [tracks[index]["id"] for index in members],
            "affect": {
                "valence": round(stats["valence"], 4),
                "arousal": round(stats["arousal"], 4),
                "tension": round(stats["tension"], 4),
            },
            "families": stats["families"],
            "top_tags": [
                {
                    "name": name,
                    "score": round(stats["tag_means"][name], 4),
                    "prevalence": round(stats["prevalence"][name], 4),
                    "lift": round(stats["tag_means"][name] - global_tags.get(name, 0), 4),
                }
                for name in stats["top_tags"][:5]
            ],
        }
        node["description"] = (
            f"{node['size']} pistes · "
            f"{', '.join(item['name'] for item in node['top_tags'][:3])} · "
            f"valence {stats['valence']:+.2f}, énergie {stats['arousal']:+.2f}, "
            f"tension {stats['tension']:+.2f}"
        )

        if level == 1:
            node["stability"] = None
            node["silhouette"] = round(score, 4)

        can_split = level < MAX_DEPTH and len(members) >= 14
        if can_split:
            child_nodes, child_assignments, child_paths = _build_nodes(
                tracks,
                matrix,
                members,
                tag_names,
                global_tags,
                used_names,
                level + 1,
                node_id,
                f"{node_id}-",
            )
            direct_children = [child for child in child_nodes if child["parent"] == node_id]
            if len(direct_children) > 1:
                node["children"] = [child["id"] for child in direct_children]
                stability = _local_stability(matrix, members, labels[local_members])
                for child in direct_children:
                    suffix = int(child["id"].rsplit("-", 1)[-1])
                    child["stability"] = stability.get(suffix)
                clusters.extend(child_nodes)
                assignments.update(child_assignments)
                for track_id, path in child_paths.items():
                    paths[track_id] = [node_id, *path]

        if not node["children"]:
            for index in members:
                track_id = tracks[index]["id"]
                assignments[track_id] = node_id
                paths[track_id] = [node_id]
        clusters.append(node)

    return clusters, assignments, paths


def build_clusters(library: dict, k: int | None = None) -> dict:
    tracks = library.get("tracks") or []
    tag_names = [tag.get("name") for tag in library.get("tags") or [] if tag.get("name")]
    if not tracks:
        raise ValueError("Bibliothèque vide")
    matrix, source_features = _feature_matrix(tracks)
    matrix, explained_variance = _pca(matrix, 6)
    indices = np.arange(len(tracks))
    global_tags = {
        name: float(
            np.mean([float((track.get("tag_scores") or {}).get(name) or 0) for track in tracks])
        )
        for name in tag_names
    }

    used_names: set[str] = set()
    if k:
        chosen_k = int(k)
        labels = fcluster(linkage(matrix, method="ward"), k, criterion="maxclust").astype(int)
        roots = sorted(set(labels.tolist()))
        top_level: list[dict] = []
        all_nodes: list[dict] = []
        assignments: dict[str, str] = {}
        paths: dict[str, list[str]] = {}
        for root_label in roots:
            members = np.where(labels == root_label)[0]
            node_id = f"c{root_label}"
            stats = _node_stats(tracks, members, tag_names)
            node = {
                "id": node_id,
                "parent": None,
                "level": 1,
                "name": _name_node(stats, global_tags, used_names),
                "size": int(len(members)),
                "stability": None,
                "silhouette": None,
                "children": [],
                "track_ids": [tracks[index]["id"] for index in members],
                "affect": {
                    "valence": round(stats["valence"], 4),
                    "arousal": round(stats["arousal"], 4),
                    "tension": round(stats["tension"], 4),
                },
                "families": stats["families"],
                "top_tags": [
                    {
                        "name": name,
                        "score": round(stats["tag_means"][name], 4),
                        "prevalence": round(stats["prevalence"][name], 4),
                        "lift": round(stats["tag_means"][name] - global_tags.get(name, 0), 4),
                    }
                    for name in stats["top_tags"][:5]
                ],
            }
            node["description"] = (
                f"{node['size']} pistes · "
                f"{', '.join(item['name'] for item in node['top_tags'][:3])} · "
                f"valence {stats['valence']:+.2f}, énergie {stats['arousal']:+.2f}, "
                f"tension {stats['tension']:+.2f}"
            )
            child_nodes, child_assignments, child_paths = _build_nodes(
                tracks,
                matrix,
                members,
                tag_names,
                global_tags,
                used_names,
                2,
                node_id,
                f"{node_id}-",
            )
            direct_children = [child for child in child_nodes if child["parent"] == node_id]
            node["children"] = [child["id"] for child in direct_children]
            stability = _local_stability(matrix, members, labels[members])
            for child in direct_children:
                suffix = int(child["id"].rsplit("-", 1)[-1])
                child["stability"] = stability.get(suffix)
            all_nodes.append(node)
            all_nodes.extend(child_nodes)
            assignments.update(child_assignments)
            for track_id, path in child_paths.items():
                paths[track_id] = [node_id, *path]
            top_level.append(node)
        roots_payload = top_level
        global_silhouette = _silhouette(squareform(pdist(matrix)), labels)
        ari = 1.0
        root_stability = {}
    else:
        labels, chosen_k, global_silhouette = _choose_k(matrix)
        root_stability, ari = _global_stability(matrix, labels)
        all_nodes, assignments, paths = _build_nodes(
            tracks,
            matrix,
            indices,
            tag_names,
            global_tags,
            used_names,
            1,
            None,
            "c",
        )
        roots_payload = [node for node in all_nodes if node["level"] == 1]
        for index, node in enumerate(sorted(roots_payload, key=lambda item: item["id"])):
            node["stability"] = root_stability.get(index + 1)
        chosen_k = len(roots_payload)

    for node in all_nodes:
        if node["stability"] is None and node["level"] == 1:
            node["stability"] = 0.0

    clusters = [
        {
            **node,
            "x": None,
            "y": None,
            "r": None,
            "spread": None,
            "color": PALETTE[index % len(PALETTE)],
        }
        for index, node in enumerate(sorted(roots_payload, key=lambda item: -item["size"]))
    ]
    node_by_id = {node["id"]: node for node in all_nodes}
    for cluster in clusters:
        node_by_id[cluster["id"]]["color"] = cluster["color"]

    def propagate(node_id: str, color: str, root_id: str) -> None:
        node = node_by_id.get(node_id)
        if not node:
            return
        node["color"] = color
        node["root_id"] = root_id
        for child_id in node["children"]:
            propagate(child_id, color, root_id)

    for cluster in clusters:
        propagate(cluster["id"], cluster["color"], cluster["id"])

    return {
        "generated_at": now(),
        "method": "ward-hierarchical",
        "k": int(chosen_k),
        "silhouette": round(float(global_silhouette), 4),
        "stability": round(float(ari), 4),
        "corpus_size": len(tracks),
        "features": source_features,
        "pca": {
            "components": len(explained_variance),
            "explained_variance": explained_variance,
        },
        "levels": [
            {"level": 1, "label": "Groupes"},
            {"level": 2, "label": "Sous-groupes"},
            {"level": 3, "label": "Familles fines"},
        ],
        "roots": [cluster["id"] for cluster in clusters],
        "clusters": clusters,
        "nodes": sorted(all_nodes, key=lambda node: (node["level"], node["id"])),
        "assignments": assignments,
        "paths": paths,
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
    parser.add_argument("--clusters", type=int, default=None, help="nombre de groupes racine")
    args = parser.parse_args()
    if not LIB_JSON.exists():
        print("Bibliothèque absente : lancer analysis/analyze.py.", file=sys.stderr)
        return 2
    library = json.loads(LIB_JSON.read_text(encoding="utf-8"))
    payload = build_and_write(library, k=args.clusters)
    print(
        f"OK : {payload['k']} groupes racine, {len(payload['nodes'])} nœuds, "
        f"silhouette {payload['silhouette']:+.3f}, stabilité {payload['stability']:+.3f}"
    )
    for cluster in payload["clusters"]:
        print(f"  {cluster['id']:>4} · {cluster['size']:>3} pistes · {cluster['name']}")
    print(f"JSON : {CLUSTERS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
