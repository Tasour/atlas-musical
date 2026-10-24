from analysis.model import TAG_NAMES, USAGE_NAMES, score_all

BASE_FEATURES = {
    "tempo": 100.0,
    "onset_rate": 1.0,
    "spectral_flux": 0.5,
    "spectral_centroid": 2200.0,
    "percussive_ratio": 0.4,
    "crest_db": 12.0,
    "dynamic_range_db": 14.0,
    "bass_ratio": 0.3,
    "pulse_clarity": 0.5,
    "roughness": 0.1,
    "harmonic_entropy": 0.7,
    "out_of_key": 0.1,
    "harmonic_ratio": 0.7,
    "spectral_flatness": 0.2,
    "stereo_width": 0.3,
    "energy": 0.5,
    "acousticness": 0.5,
    "loopability": 0.5,
    "key_confidence": 0.7,
    "tempo_confidence": 0.7,
    "mode": "major",
    "duration": 120.0,
}


def features(**overrides):
    return {**BASE_FEATURES, **overrides}


def test_scores_are_bounded_and_assignments_are_present():
    rows, stats = score_all(
        [
            features(),
            features(
                tempo=140.0,
                onset_rate=2.5,
                energy=0.9,
                mode="minor",
                pulse_clarity=0.8,
                roughness=0.6,
                harmonic_entropy=0.95,
                out_of_key=0.8,
            ),
        ],
        [
            {"id": "calm-track", "family": "acoustique"},
            {"id": "intense-track", "family": "intense"},
        ],
    )

    assert len(rows) == 2
    assert {"tempo", "roughness", "spectral_centroid", "pulse_clarity"} <= set(stats)

    for row in rows:
        scores = row["scores"]
        assert -1.0 <= scores["valence"] <= 1.0
        assert -1.0 <= scores["arousal"] <= 1.0
        assert -1.0 <= scores["tension"] <= 1.0
        assert 0.0 <= scores["confidence"] <= 1.0
        assert 0.0 <= scores["ellipse_rx"] <= 0.2
        assert scores["tags"]
        assert scores["tags"][-1] == "Instrumental"
        assert set(scores["tags"]) <= set(TAG_NAMES) | {
            "Instrumental",
            "Littoral",
            "Aride/outback",
            "Brousse",
            "Nuit/route",
        }
        assert scores["usages"]
        assert set(scores["usages"]) <= set(USAGE_NAMES)
        assert set(scores["tag_scores"]) >= set(TAG_NAMES) | {"Instrumental"}
        assert set(scores["usage_scores"]) == set(USAGE_NAMES)

    assert rows[1]["scores"]["arousal"] > rows[0]["scores"]["arousal"]
