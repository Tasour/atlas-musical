import json

import analysis.cluster as cluster

TAGS = ["Joie", "Tristesse", "Tension", "Apaisement", "Littoral", "Brousse"]


def make_track(index, profile, family, valence, arousal, tension, energy):
    return {
        "id": f"t{index}",
        "family": family,
        "tag_scores": {name: profile.get(name, 0.1) for name in TAGS},
        "valence": valence,
        "arousal": arousal,
        "tension": tension,
        "energy": energy,
        "bpm": 90 + index % 5,
        "acousticness": 0.5,
        "danceability": 0.5,
    }


def make_library():
    tracks = []
    index = 0
    groups = [
        ({"Joie": 0.9, "Aventure": 0.8}, "tropical", 0.6, 0.6, 0.1, 0.8),
        ({"Tristesse": 0.9, "Tension": 0.85}, "cinematique", -0.6, -0.2, 0.6, 0.3),
        ({"Littoral": 0.9, "Apaisement": 0.8}, "acoustique", 0.2, -0.5, -0.2, 0.3),
    ]
    for profile, family, valence, arousal, tension, energy in groups:
        for _ in range(12):
            tracks.append(
                make_track(index, profile, family, valence, arousal, tension, energy)
            )
            index += 1
    return {
        "tracks": tracks,
        "tags": [{"name": name} for name in TAGS],
    }


def test_clusters_assign_every_track():
    payload = cluster.build_clusters(make_library(), k=3)

    assert payload["k"] == 3
    assert len(payload["clusters"]) == 3
    assert sum(item["size"] for item in payload["clusters"]) == 36
    assert set(payload["assignments"]) == {f"t{i}" for i in range(36)}
    assert set(payload["paths"]) == {f"t{i}" for i in range(36)}
    assert len({item["name"] for item in payload["clusters"]}) == 3
    assert all(item["name"] for item in payload["clusters"])
    assert len(payload["nodes"]) >= 3
    assert all(node["color"] for node in payload["nodes"])
    assert all(payload["paths"][track_id][-1] == cluster_id for track_id, cluster_id in payload["assignments"].items())


def test_hierarchy_children_are_subsets():
    payload = cluster.build_clusters(make_library(), k=3)
    nodes = {node["id"]: node for node in payload["nodes"]}
    for node in nodes.values():
        if not node["children"]:
            continue
        children = [nodes[child_id] for child_id in node["children"]]
        assert all(child["parent"] == node["id"] for child in children)
        union = {track_id for child in children for track_id in child["track_ids"]}
        assert union == set(node["track_ids"])


def test_clusters_choose_k_automatically():
    payload = cluster.build_clusters(make_library())

    assert 2 <= payload["k"] <= 9
    assert len(payload["clusters"]) == payload["k"]
    assert len(payload["assignments"]) == 36


def test_write_clusters(tmp_path, monkeypatch):
    target = tmp_path / "clusters.json"
    monkeypatch.setattr(cluster, "CLUSTERS_JSON", target)

    payload = cluster.build_clusters(make_library(), k=3)
    cluster.write_clusters(payload)

    stored = json.loads(target.read_text(encoding="utf-8"))
    assert stored["k"] == 3
    assert len(stored["assignments"]) == 36
