import json
from urllib.parse import unquote

from fastapi.testclient import TestClient

import server


def test_health_without_library(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "LIB_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(server, "DB", tmp_path / "missing.sqlite")
    monkeypatch.setattr(server, "AUDIO", tmp_path / "audio")

    response = TestClient(server.app).get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "Atlas Musical"
    assert payload["ok"] is False
    assert payload["tracks"] == 0
    assert payload["audio_files"] == 0


def test_library_requires_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "LIB_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(server, "DB", tmp_path / "missing.sqlite")

    response = TestClient(server.app).get("/api/library")

    assert response.status_code == 503
    assert "analysée" in response.json()["detail"]


def test_download_returns_attachment(tmp_path, monkeypatch):
    track = {"id": "t1", "title": "Titre test", "artist": "Artiste test", "file_path": "audio/t1.mp3"}
    library = tmp_path / "library.json"
    library.write_text(json.dumps({"tracks": [track]}), encoding="utf-8")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "t1.mp3").write_bytes(b"ID3\x04test")

    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "LIB_JSON", library)
    monkeypatch.setattr(server, "DB", tmp_path / "missing.sqlite")

    response = TestClient(server.app).get("/api/download/t1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    disposition = unquote(response.headers["content-disposition"])
    assert "attachment" in disposition
    assert "Artiste test - Titre test.mp3" in disposition
    assert response.content == b"ID3\x04test"


def test_clusters_requires_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CLUSTERS_JSON", tmp_path / "missing.json")

    response = TestClient(server.app).get("/api/clusters")

    assert response.status_code == 503
    assert "analysis.cluster" in response.json()["detail"]


def test_clusters_returns_payload(tmp_path, monkeypatch):
    payload = {
        "k": 2,
        "clusters": [{"id": "c1", "name": "Test"}],
        "assignments": {"t1": "c1"},
    }
    path = tmp_path / "clusters.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(server, "CLUSTERS_JSON", path)

    response = TestClient(server.app).get("/api/clusters")

    assert response.status_code == 200
    assert response.json()["k"] == 2


def test_library_merges_cluster_assignments(tmp_path, monkeypatch):
    library = tmp_path / "library.json"
    library.write_text(
        json.dumps({"tracks": [{"id": "t1", "title": "Titre"}]}), encoding="utf-8"
    )
    clusters = tmp_path / "clusters.json"
    clusters.write_text(
        json.dumps(
            {
                "clusters": [{"id": "c1", "name": "Littoral", "color": "teal"}],
                "assignments": {"t1": "c1"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "LIB_JSON", library)
    monkeypatch.setattr(server, "CLUSTERS_JSON", clusters)
    monkeypatch.setattr(server, "DB", tmp_path / "missing.sqlite")

    payload = server.merged_library()

    track = payload["tracks"][0]
    assert track["cluster"] == "c1"
    assert track["cluster_name"] == "Littoral"
    assert track["cluster_color"] == "teal"
    assert payload["clusters"]["clusters"][0]["name"] == "Littoral"
