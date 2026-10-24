#!/usr/bin/env python3
"""Stabilité du modèle : bootstrap, leave-one-out et annotations manuelles."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    from .model import corpus_stats, score_track
except ImportError:
    from model import corpus_stats, score_track

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "library.sqlite"
OUT = ROOT / "data" / "validation.json"
KEYS = ("valence", "arousal", "tension")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rank(values: np.ndarray) -> np.ndarray:
    return np.argsort(np.argsort(values)).astype(float)


def load() -> tuple[list[dict], list[dict], list[dict], dict[str, dict]]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM tracks ORDER BY id").fetchall()
    ann_rows = conn.execute("SELECT * FROM annotations").fetchall()
    conn.close()
    feats = [json.loads(r["features_json"]) for r in rows]
    metas = [{"id": r["id"], "family": r["family"]} for r in rows]
    base = {
        r["id"]: {
            "valence": r["valence"],
            "arousal": r["arousal"],
            "tension": r["tension"],
            "confidence": r["confidence"],
        }
        for r in rows
    }
    anns = {r["track_id"]: dict(r) for r in ann_rows}
    return feats, metas, rows, {"base": base, "annotations": anns}


def main() -> int:
    if not DB.exists():
        print("Base absente : lancer analysis/analyze.py")
        return 2
    feats, metas, rows, extra = load()
    n = len(feats)
    base = extra["base"]
    rng = np.random.default_rng(42)

    boot = {
        r["id"]: {k: [] for k in KEYS}
        for r in rows
    }
    iterations = 240
    for _ in range(iterations):
        idx = rng.integers(0, n, n)
        stats = corpus_stats([feats[i] for i in idx])
        for i in range(n):
            sc = score_track(feats[i], stats, metas[i])
            for key in KEYS:
                boot[metas[i]["id"]][key].append(float(sc[key]))

    loo = {}
    for i in range(n):
        stats = corpus_stats([feats[j] for j in range(n) if j != i])
        sc = score_track(feats[i], stats, metas[i])
        loo[metas[i]["id"]] = {k: float(sc[k]) for k in KEYS}

    report = {
        "generated_at": now(),
        "n": n,
        "bootstrap_iterations": iterations,
        "scores": {},
        "summary": {},
        "manual_annotations": {},
    }
    for r in rows:
        tid = r["id"]
        bstd = {
            k: float(np.std(boot[tid][k], ddof=1)) if len(boot[tid][k]) > 1 else 0.0
            for k in KEYS
        }
        ldelta = {k: abs(loo[tid][k] - float(base[tid][k])) for k in KEYS}
        report["scores"][tid] = {
            "auto": {k: float(base[tid][k]) for k in KEYS},
            "bootstrap_std": {k: round(v, 4) for k, v in bstd.items()},
            "loo_abs_delta": {k: round(v, 4) for k, v in ldelta.items()},
            "confidence": float(base[tid]["confidence"]),
        }
    for key in KEYS:
        report["summary"][key] = {
            "mean_bootstrap_std": round(
                float(np.mean([v["bootstrap_std"][key] for v in report["scores"].values()])),
                4,
            ),
            "max_bootstrap_std": round(
                float(np.max([v["bootstrap_std"][key] for v in report["scores"].values()])),
                4,
            ),
            "mean_loo_abs_delta": round(
                float(np.mean([v["loo_abs_delta"][key] for v in report["scores"].values()])),
                4,
            ),
        }

    anns = extra["annotations"]
    pairs = {k: ([], []) for k in KEYS}
    for tid, ann in anns.items():
        if tid not in base:
            continue
        for key in KEYS:
            manual = ann.get(key)
            if manual is not None:
                pairs[key][0].append(float(base[tid][key]))
                pairs[key][1].append(float(manual))
    for key, (auto, manual) in pairs.items():
        if len(auto) >= 3:
            a = np.asarray(auto)
            m = np.asarray(manual)
            report["manual_annotations"][key] = {
                "n": len(a),
                "mae": round(float(np.mean(np.abs(a - m))), 4),
                "spearman": round(float(np.corrcoef(rank(a), rank(m))[0, 1]), 4),
            }
        else:
            report["manual_annotations"][key] = {"n": len(auto), "note": "échantillon insuffisant"}

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Rapport : {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
