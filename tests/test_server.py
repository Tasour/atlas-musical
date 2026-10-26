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


def test_library_merges_hierarchical_cluster_path(tmp_path, monkeypatch):
    library = tmp_path / "library.json"
    library.write_text(
        json.dumps({"tracks": [{"id": "t1", "title": "Titre"}]}), encoding="utf-8"
    )
    clusters = tmp_path / "clusters.json"
    clusters.write_text(
        json.dumps(
            {
                "clusters": [{"id": "c1", "name": "Racine", "color": "teal"}],
                "nodes": [
                    {"id": "c1", "name": "Racine", "color": "teal"},
                    {"id": "c1-1", "name": "Sous-groupe", "color": "teal"},
                ],
                "assignments": {"t1": "c1-1"},
                "paths": {"t1": ["c1", "c1-1"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "LIB_JSON", library)
    monkeypatch.setattr(server, "CLUSTERS_JSON", clusters)
    monkeypatch.setattr(server, "DB", tmp_path / "missing.sqlite")

    track = server.merged_library()["tracks"][0]

    assert track["cluster"] == "c1-1"
    assert track["cluster_name"] == "Sous-groupe"
    assert track["cluster_path"] == ["c1", "c1-1"]
    assert track["cluster_path_names"] == ["Racine", "Sous-groupe"]


def test_export_selection_zip(tmp_path, monkeypatch):
    import io
    import zipfile

    track = {
        "id": "t1",
        "youtube_id": "aaaaaaaaaaa",
        "title": "Titre test",
        "artist": "Artiste test",
        "file_path": "audio/t1.mp3",
        "license": "CC BY 4.0",
        "credit": "Artiste test",
        "source_url": "https://example.org",
        "duration": 120,
        "bpm": 90,
    }
    library = tmp_path / "library.json"
    library.write_text(json.dumps({"tracks": [track]}), encoding="utf-8")
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "t1.mp3").write_bytes(b"ID3\x04test")
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "LIB_JSON", library)
    monkeypatch.setattr(server, "CLUSTERS_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(server, "DB", tmp_path / "missing.sqlite")
    monkeypatch.setattr(server, "EXPORTS", exports)

    response = TestClient(server.app).post(
        "/api/export-selection",
        json={"items": [{"id": "t1", "status": "choisi", "note": "plan", "license_checked": True}], "brief": "Action"},
    )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "selection.json" in names
        assert "CREDITS.txt" in names
        assert "audio/Artiste test - Titre test.mp3" in names
        selection = json.loads(archive.read("selection.json"))
        assert selection["items"][0]["license_checked"] is True
        assert "artiste test" in archive.read("CREDITS.txt").decode().lower()
