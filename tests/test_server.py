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
