"""Modèle affectif « profil perçu ».

Ce n'est pas un détecteur d'émotions : les scores sont des estimations
interprétables, relatives au corpus, avec une confiance explicite. Les poids
sont fixés a priori à partir de la littérature MIR/psychologie de la musique,
puis les features sont robustement standardisées (médiane/MAD) sur la
bibliothèque.
"""

from __future__ import annotations

import math

import numpy as np

FAMILY_VALENCE = {
    "acoustique": 0.30,
    "tropical": 0.48,
    "cinematique": -0.22,
    "intense": 0.02,
}
FAMILY_AROUSAL = {
    "acoustique": -0.10,
    "tropical": 0.16,
    "cinematique": -0.18,
    "intense": 0.40,
}
FAMILY_TENSION = {
    "acoustique": -0.08,
    "tropical": -0.10,
    "cinematique": 0.18,
    "intense": 0.12,
}

FAMILY_TAG_BOOST = {
    "acoustique": {"Nostalgie": 0.06, "Intimité": 0.05, "Apaisement": 0.03},
    "tropical": {"Joie": 0.12, "Énergie": 0.08, "Romance": 0.05, "Apaisement": 0.03, "Tension": -0.10},
    "cinematique": {"Émerveillement": 0.10, "Ambiance": 0.08, "Tension": 0.04, "Nostalgie": 0.04, "Énergie": -0.04},
    "intense": {"Aventure": 0.14, "Énergie": 0.10, "Tension": 0.06, "Intimité": -0.10, "Apaisement": -0.08, "Romance": -0.06},
}

CONTEXT = {
    "oak-sydney": ["Littoral"],
    "oak-coastline": ["Littoral"],
    "ylia-australian-folk": ["Brousse"],
    "ylia-byron-bay": ["Littoral"],
    "odcctv-before-dawn": ["Nuit/route"],
    "wayne-australia": ["Brousse"],
    "scott-ephemera": ["Nuit/route"],
    "nextune-cinematic-ambient": ["Nuit/route"],
    "cml-remnants": ["Nuit/route"],
    "tyops-documentary-ambient": ["Nuit/route"],
    "clio-odd-waltz": ["Brousse"],
    "leonites-easy-to-love": ["Littoral"],
    "bergs-tropical-soul": ["Littoral"],
    "bergs-coral": ["Littoral"],
    "tokyo-sunset-drive": ["Nuit/route"],
    "inossi-wonder": ["Littoral"],
    "alex-legends": ["Brousse"],
    "cml-expedition": ["Aride/outback"],
    "mc-red-ground": ["Aride/outback"],
    "karma-outback-adventurer": ["Aride/outback"],
}

TAG_NAMES = [
    "Joie",
    "Tristesse",
    "Nostalgie",
    "Ambiance",
    "Tension",
    "Aventure",
    "Apaisement",
    "Émerveillement",
    "Intimité",
    "Romance",
    "Énergie",
]

USAGE_NAMES = [
    "Ouverture",
    "Transition",
    "Paysage/drone",
    "Portrait/intime",
    "Action/montage",
    "Résolution/générique",
]

FAMILY_EXCLUDE_TAGS = {
    "intense": {"Romance", "Apaisement"},
}


def _zstats(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    med = float(np.nanmedian(arr))
    mad = float(np.nanmedian(np.abs(arr - med)))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale < 1e-6:
        scale = float(np.nanstd(arr))
    if not np.isfinite(scale) or scale < 1e-6:
        scale = 1.0
    return med, scale


def corpus_stats(features: list[dict]) -> dict:
    keys = [
        "tempo",
        "onset_rate",
        "spectral_flux",
        "spectral_centroid",
        "percussive_ratio",
        "crest_db",
        "dynamic_range_db",
        "bass_ratio",
        "pulse_clarity",
        "roughness",
        "harmonic_entropy",
        "out_of_key",
        "harmonic_ratio",
        "spectral_flatness",
        "stereo_width",
        "energy",
        "acousticness",
        "loopability",
    ]
    stats = {}
    for key in keys:
        vals = [float(f.get(key, 0.0)) for f in features]
        stats[key] = _zstats(vals)
    return stats


def _z(features: dict, stats: dict, key: str) -> float:
    med, scale = stats[key]
    v = float(features.get(key, 0.0))
    return float(np.clip((v - med) / scale, -3.0, 3.0))


def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def score_track(features: dict, stats: dict, meta: dict) -> dict:
    family = meta.get("family", "cinematique")
    z_tempo = _z(features, stats, "tempo")
    z_onset = _z(features, stats, "onset_rate")
    z_flux = _z(features, stats, "spectral_flux")
    z_centroid = _z(features, stats, "spectral_centroid")
    z_perc = _z(features, stats, "percussive_ratio")
    z_crest = _z(features, stats, "crest_db")
    z_dyn = _z(features, stats, "dynamic_range_db")
    z_bass = _z(features, stats, "bass_ratio")
    z_pulse = _z(features, stats, "pulse_clarity")
    z_rough = _z(features, stats, "roughness")
    z_harm_entropy = _z(features, stats, "harmonic_entropy")
    z_out_key = _z(features, stats, "out_of_key")
    z_harmonic = _z(features, stats, "harmonic_ratio")
    z_flat = _z(features, stats, "spectral_flatness")

    key_conf = _clip01(features.get("key_confidence", 0.3))
    mode_sign = 1.0 if features.get("mode") == "major" else -1.0
    tempo_conf = _clip01(features.get("tempo_confidence", 0.2))
    pulse = _clip01(features.get("pulse_clarity", 0.0))
    acoustic = _clip01(features.get("acousticness", 0.5))

    a_raw = (
        0.24 * z_tempo
        + 0.16 * z_onset
        + 0.13 * z_flux
        + 0.12 * z_centroid
        + 0.10 * z_perc
        + 0.08 * z_crest
        + 0.06 * z_dyn
        + 0.05 * z_bass
        + 0.04 * z_pulse
        + 0.30 * FAMILY_AROUSAL.get(family, 0.0)
    )
    arousal = math.tanh(0.95 * a_raw)

    v_raw = (
        0.28 * mode_sign * key_conf
        + 0.14 * z_harmonic
        - 0.14 * z_rough
        + 0.10 * z_pulse
        + 0.08 * (1.0 - min(abs(z_dyn) / 3.0, 1.0))
        - 0.06 * z_flat
        + 0.24 * FAMILY_VALENCE.get(family, 0.0)
    )
    valence = math.tanh(0.90 * v_raw)

    t_raw = (
        0.30 * z_rough
        + 0.20 * z_harm_entropy
        + 0.18 * z_out_key
        + 0.12 * z_flux
        - 0.10 * z_pulse
        + 0.10 * abs(z_flat)
        + 0.04 * z_centroid
        + 0.20 * FAMILY_TENSION.get(family, 0.0)
    )
    tension = math.tanh(0.85 * t_raw)

    confidence = _clip01(
        0.18 + 0.30 * tempo_conf + 0.34 * key_conf + 0.10 * (1.0 - abs(z_rough) / 3.0)
    )
    if features.get("duration", 0) < 30:
        confidence *= 0.8
    confidence = _clip01(confidence)
    rx = round(0.045 + 0.11 * (1.0 - confidence), 4)
    ry = round(0.045 + 0.13 * (1.0 - confidence), 4)

    a01 = _clip01((arousal + 1.0) / 2.0)
    v01 = _clip01((valence + 1.0) / 2.0)
    t01 = _clip01((tension + 1.0) / 2.0)
    brightness = _clip01(float(features.get("spectral_centroid", 0.0)) / 5000.0)
    harmonic = _clip01(float(features.get("harmonic_ratio", 0.0)))
    width = _clip01(float(features.get("stereo_width", 0.0)))
    onset_norm = _clip01(float(features.get("onset_rate", 0.0)) / 3.5)

    perc_norm = _clip01(float(features.get("percussive_ratio", 0.0)))
    rough_norm = _clip01(float(features.get("roughness", 0.0)) * 5.0)
    tag_scores = {
        "Énergie": _clip01(
            0.55 * _clip01(float(features.get("energy", 0.0)))
            + 0.25 * a01
            + 0.10 * perc_norm
            + 0.10 * onset_norm
        ),
        "Apaisement": _clip01(
            0.45 * (1.0 - a01)
            + 0.25 * (1.0 - t01)
            + 0.15 * acoustic
            + 0.15 * (1.0 - _clip01(float(features.get("energy", 0.0))))
        ),
        "Joie": _clip01(
            0.45 * v01
            + 0.25 * a01
            + 0.20 * pulse
            + 0.10 * _clip01(float(features.get("energy", 0.0)))
        ),
        "Tristesse": _clip01(
            0.50 * (1.0 - v01)
            + 0.25 * (1.0 - a01)
            + 0.15 * (1.0 - brightness)
            + 0.10 * (1.0 - _clip01(float(features.get("energy", 0.0))))
        ),
        "Nostalgie": _clip01(
            0.30 * (1.0 - v01)
            + 0.20 * (1.0 - a01)
            + 0.20 * acoustic
            + 0.15 * (1.0 - brightness)
            + 0.15 * (1.0 - _clip01(float(features.get("energy", 0.0))))
        ),
        "Tension": _clip01(0.75 * t01 + 0.15 * rough_norm + 0.10 * (1.0 - pulse)),
        "Aventure": _clip01(
            0.45 * a01
            + 0.20 * pulse
            + 0.15 * _clip01(float(features.get("energy", 0.0)))
            + 0.20 * (1.0 if family == "intense" else 0.0)
        ),
        "Émerveillement": _clip01(
            0.35 * harmonic
            + 0.25 * width
            + 0.20 * (1.0 - onset_norm)
            + 0.20 * (1.0 - t01)
        ),
        "Intimité": _clip01(
            0.30 * acoustic
            + 0.25 * (1.0 - _clip01(float(features.get("energy", 0.0))))
            + 0.20 * (1.0 - width)
            + 0.15 * (1.0 - a01)
            + 0.10 * (1.0 - onset_norm)
        ),
        "Romance": _clip01(
            0.40 * v01
            + 0.25 * (1.0 - a01)
            + 0.20 * harmonic
            + 0.15 * (1.0 - t01)
        ),
        "Ambiance": _clip01(
            0.30 * harmonic
            + 0.25 * (1.0 - pulse)
            + 0.20 * (1.0 - onset_norm)
            + 0.15 * (1.0 - t01)
            + 0.10 * (1.0 - _clip01(float(features.get("energy", 0.0))))
        ),
    }
    for name, boost in FAMILY_TAG_BOOST.get(family, {}).items():
        tag_scores[name] = _clip01(tag_scores[name] + boost)
    context_tags = CONTEXT.get(meta.get("id", ""), [])
    for tag in context_tags:
        tag_scores[tag] = 0.90
    tag_scores["Instrumental"] = 1.0

    return {
        "valence": round(float(np.clip(valence, -1, 1)), 4),
        "arousal": round(float(np.clip(arousal, -1, 1)), 4),
        "tension": round(float(np.clip(tension, -1, 1)), 4),
        "valence01": round(v01, 4),
        "arousal01": round(a01, 4),
        "tension01": round(t01, 4),
        "confidence": round(confidence, 4),
        "ellipse_rx": rx,
        "ellipse_ry": ry,
        "tags": [],
        "tag_scores": {k: round(float(v), 4) for k, v in tag_scores.items()},
        "usages": [],
        "usage_scores": {},
        "score_version": "1.0",
    }


def _calibrate(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [0.15 + 0.80 * (v - lo) / (hi - lo) for v in values]


def _assign_tags(out: list[dict]) -> None:
    raw = {
        tag: [float(item["scores"]["tag_scores"].get(tag, 0.0)) for item in out]
        for tag in TAG_NAMES
    }
    calibrated = {tag: _calibrate(values) for tag, values in raw.items()}
    for i, item in enumerate(out):
        scores = item["scores"]
        family = item["meta"].get("family", "cinematique")
        for tag in TAG_NAMES:
            scores["tag_scores"][tag] = round(float(calibrated[tag][i]), 4)
        context_tags = CONTEXT.get(item["meta"].get("id", ""), [])
        for tag in context_tags:
            scores["tag_scores"][tag] = 0.90
        scores["tag_scores"]["Instrumental"] = 1.0
        excluded = FAMILY_EXCLUDE_TAGS.get(family, set())
        ranked = sorted(
            (
                (name, scores["tag_scores"][name])
                for name in TAG_NAMES
                if name not in excluded
            ),
            key=lambda kv: kv[1],
            reverse=True,
        )
        selected = [name for name, score in ranked if score >= 0.62][:4]
        if not selected:
            selected = [name for name, _ in ranked[:2]]
        scores["tags"] = selected + context_tags + ["Instrumental"]


def _assign_usages(out: list[dict]) -> None:
    raw = {name: [] for name in USAGE_NAMES}
    for item in out:
        scores = item["scores"]
        features = item["features"]
        tag = scores["tag_scores"]
        a01 = scores["arousal01"]
        v01 = scores["valence01"]
        t01 = scores["tension01"]
        calm = _clip01(1.0 - a01)
        loop = _clip01(float(features.get("loopability", 0.5)))
        pulse = _clip01(float(features.get("pulse_clarity", 0.0)))
        wonder = tag["Émerveillement"]
        ambience = tag["Ambiance"]
        adventure = tag["Aventure"]
        intimacy = tag["Intimité"]
        nostalgia = tag["Nostalgie"]
        raw["Ouverture"].append(
            _clip01(0.35 * wonder + 0.25 * adventure + 0.20 * v01 + 0.20 * (1.0 - t01))
        )
        raw["Transition"].append(
            _clip01(0.35 * ambience + 0.25 * loop + 0.20 * (1.0 - t01) + 0.20 * calm)
        )
        raw["Paysage/drone"].append(
            _clip01(0.50 * ambience + 0.30 * wonder + 0.20 * (1.0 - a01))
        )
        raw["Portrait/intime"].append(
            _clip01(0.50 * intimacy + 0.30 * nostalgia + 0.20 * calm)
        )
        raw["Action/montage"].append(
            _clip01(0.50 * a01 + 0.30 * adventure + 0.20 * pulse)
        )
        raw["Résolution/générique"].append(
            _clip01(0.35 * v01 + 0.25 * calm + 0.20 * wonder + 0.20 * loop)
        )
    calibrated = {name: _calibrate(values) for name, values in raw.items()}
    for i, item in enumerate(out):
        scores = item["scores"]
        usage = {name: round(float(calibrated[name][i]), 4) for name in USAGE_NAMES}
        scores["usage_scores"] = usage
        ranked = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)
        selected = [name for name, score in ranked if score >= 0.65][:3]
        if not selected:
            selected = [ranked[0][0]]
        scores["usages"] = selected


def score_all(features: list[dict], metas: list[dict]) -> tuple[list[dict], dict]:
    stats = corpus_stats(features)
    out = []
    for feat, meta in zip(features, metas):
        scores = score_track(feat, stats, meta)
        out.append({"meta": meta, "features": feat, "scores": scores})
    _assign_tags(out)
    _assign_usages(out)
    return out, stats
