#!/usr/bin/env python3
"""Serveur local de la webapp Atlas Musical.

Lancement : python3 server.py
Interface : http://127.0.0.1:8765/
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.middleware.gzip import GZipMiddleware

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"
DATA = ROOT / "data"
DB = DATA / "library.sqlite"
LIB_JSON = DATA / "library.json"
CLUSTERS_JSON = DATA / "clusters.json"
AUDIO = ROOT / "audio"
EXPORTS = DATA / "exports"
EXPORTS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Atlas Musical", version="1.0")
app.add_middleware(GZipMiddleware, minimum_size=800)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_library() -> dict:
    if not LIB_JSON.exists():
        raise HTTPException(503, "Bibliothèque non analysée : lancer analysis/analyze.py")
    return json.loads(LIB_JSON.read_text())


def annotations() -> dict[str, dict]:
    if not DB.exists():
        return {}
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM annotations").fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    out = {}
    for r in rows:
        out[r["track_id"]] = {
            "valence": r["valence"],
            "arousal": r["arousal"],
            "tension": r["tension"],
            "tags": json.loads(r["tags_json"] or "[]"),
            "note": r["note"],
            "updated_at": r["updated_at"],
        }
    return out


def read_clusters() -> dict:
    if not CLUSTERS_JSON.exists():
        return {}
    try:
        return json.loads(CLUSTERS_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def merged_library() -> dict:
    lib = read_library()
    anns = annotations()
    clusters = read_clusters()
    assignments = clusters.get("assignments", {})
    nodes = clusters.get("nodes") or clusters.get("clusters", [])
    by_id = {node["id"]: node for node in nodes}
    paths = clusters.get("paths", {})
    for track in lib.get("tracks", []):
        if track["id"] in anns:
            track["annotation"] = anns[track["id"]]
        cluster_id = assignments.get(track["id"])
        if cluster_id:
            cluster = by_id.get(cluster_id, {})
            track["cluster"] = cluster_id
            track["cluster_name"] = cluster.get("name")
            track["cluster_color"] = cluster.get("color")
            path = paths.get(track["id"], [])
            track["cluster_path"] = path
            track["cluster_path_names"] = [
                by_id.get(node_id, {}).get("name") for node_id in path
            ]
    if clusters:
        lib["clusters"] = clusters
    return lib


def cleanup_exports(max_files: int = 24) -> None:
    files = sorted(
        EXPORTS.glob("atlas-musical-*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[max_files:]:
        try:
            old.unlink()
        except OSError:
            pass


def unique_export(suffix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return EXPORTS / f"atlas-musical-{stamp}{suffix}"


def sqlite_export() -> Path:
    dest = unique_export(".sqlite")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
        out.execute("PRAGMA journal_mode=DELETE")
    finally:
        out.close()
        src.close()
    return dest


def json_export() -> Path:
    dest = unique_export(".json")
    dest.write_text(json.dumps(merged_library(), ensure_ascii=False, indent=2))
    return dest


def zip_export() -> Path:
    dest = unique_export(".zip")
    lib_path = json_export()
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.write(lib_path, "library.json")
            if DB.exists():
                z.write(DB, "library.sqlite")
            for name in ("CREDITS.md", "METHODOLOGY.md", "README.md"):
                p = ROOT / name
                if p.exists():
                    z.write(p, name)
            for mp3 in sorted(AUDIO.glob("*.mp3")):
                z.write(mp3, f"audio/{mp3.name}")
    finally:
        try:
            lib_path.unlink()
        except OSError:
            pass
    return dest


def audio_path(track_id: str) -> tuple[Path, dict]:
    lib = merged_library()
    track = next((t for t in lib["tracks"] if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "Piste inconnue")
    path = ROOT / track["file_path"]
    if not path.exists():
        raise HTTPException(404, "Fichier audio manquant")
    return path, track


def download_name(track: dict) -> str:
    base = f"{track.get('artist', '')} - {track.get('title', '')}".strip(" -")
    base = re.sub(r'[\\/:*?"<>|]+', "-", base)
    base = re.sub(r"\s+", " ", base).strip(" .")
    return f"{base or track.get('id', 'piste')}.mp3"


class SelectionItem(BaseModel):
    id: str
    status: str = "a-ecouter"
    note: str = ""
    license_checked: bool = False


class SelectionExport(BaseModel):
    items: list[SelectionItem] = Field(min_length=1, max_length=20)
    brief: str = ""


@app.get("/api/health")
def health() -> dict:
    lib = {}
    try:
        lib = read_library()
    except HTTPException:
        pass
    mp3s = list(AUDIO.glob("*.mp3"))
    return {
        "app": "Atlas Musical",
        "ok": bool(lib),
        "tracks": len(lib.get("tracks", [])),
        "audio_files": len(mp3s),
        "db": DB.exists(),
        "json": LIB_JSON.exists(),
        "generated_at": lib.get("meta", {}).get("generated_at"),
        "now": now(),
    }


@app.get("/api/library")
def library() -> dict:
    return merged_library()


@app.get("/api/library/summary")
def library_summary() -> dict:
    lib = merged_library()
    lib["tracks"] = [
        {
            key: value
            for key, value in track.items()
            if key not in {"features", "arc", "tag_scores", "sha256", "source_title"}
        }
        for track in lib.get("tracks", [])
    ]
    lib.setdefault("meta", {})["summary"] = True
    return lib


@app.get("/api/clusters")
def clusters() -> dict:
    payload = read_clusters()
    if not payload:
        raise HTTPException(
            503, "Clusters indisponibles : lancer python -m analysis.cluster"
        )
    return payload


@app.get("/api/track/{track_id}")
def track(track_id: str) -> dict:
    lib = merged_library()
    item = next((t for t in lib["tracks"] if t["id"] == track_id), None)
    if not item:
        raise HTTPException(404, "Piste inconnue")
    return item


@app.get("/api/audio/{track_id}")
def audio(track_id: str):
    path, track = audio_path(track_id)
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/download/{track_id}")
def download(track_id: str):
    path, track = audio_path(track_id)
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=download_name(track),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/export-selection")
def export_selection(payload: SelectionExport):
    cleanup_exports()
    lib = merged_library()
    by_id = {track["id"]: track for track in lib.get("tracks", [])}
    selected = [
        (item, by_id[item.id])
        for item in payload.items
        if item.id in by_id
    ]
    if not selected:
        raise HTTPException(404, "Aucune piste valide dans la sélection")
    dest = unique_export(".zip")
    used_names: set[str] = set()
    rows = []
    credit_lines = [
        "Atlas Musical — sélection",
        f"Généré le {now()}",
        f"Brief : {payload.brief or '—'}",
        "",
    ]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item, track in selected:
            row = {
                "id": track["id"],
                "title": track.get("title"),
                "artist": track.get("artist"),
                "status": item.status,
                "note": item.note,
                "license_checked": item.license_checked,
                "license": track.get("license"),
                "credit": track.get("credit"),
                "source_url": track.get("source_url"),
                "duration": track.get("duration"),
                "bpm": track.get("bpm"),
                "cluster_path": track.get("cluster_path_names") or [],
            }
            rows.append(row)
            credit_lines.append(
                f"- {row['title']} — {row['artist']} · {row['license']} · "
                f"{row['credit']} · {row['source_url']}"
            )
            audio = ROOT / track["file_path"]
            if not audio.exists():
                continue
            name = download_name(track)
            while name in used_names:
                base = name[:-4] if name.lower().endswith(".mp3") else name
                name = f"{base} ({track['id']}).mp3"
            used_names.add(name)
            archive.write(audio, f"audio/{name}")
        archive.writestr(
            "selection.json",
            json.dumps(
                {
                    "app": "Atlas Musical",
                    "generated_at": now(),
                    "brief": payload.brief,
                    "items": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        archive.writestr("CREDITS.txt", "\n".join(credit_lines) + "\n")
    return FileResponse(
        dest,
        media_type="application/zip",
        filename="atlas-selection.zip",
        background=BackgroundTask(lambda: dest.unlink(missing_ok=True)),
    )


@app.get("/api/export")
def export(format: str = "sqlite"):
    cleanup_exports()
    fmt = format.lower().strip()
    if fmt in {"sqlite", "db"}:
        path = sqlite_export()
        media = "application/vnd.sqlite3"
        name = "atlas-musical.sqlite"
    elif fmt == "json":
        path = json_export()
        media = "application/json"
        name = "atlas-musical.json"
    elif fmt == "zip":
        path = zip_export()
        media = "application/zip"
        name = "atlas-musical.zip"
    else:
        raise HTTPException(400, "Format attendu : sqlite, json ou zip")
    return FileResponse(
        path,
        media_type=media,
        filename=name,
        background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
    )


class Annotation(BaseModel):
    track_id: str
    valence: float | None = Field(default=None, ge=-1, le=1)
    arousal: float | None = Field(default=None, ge=-1, le=1)
    tension: float | None = Field(default=None, ge=-1, le=1)
    tags: list[str] = Field(default_factory=list)
    note: str = ""


@app.post("/api/annotations")
def save_annotation(payload: Annotation) -> dict:
    if not DB.exists():
        raise HTTPException(503, "Base absente")
    lib = read_library()
    if not any(t["id"] == payload.track_id for t in lib["tracks"]):
        raise HTTPException(404, "Piste inconnue")
    stamp = now()
    conn = sqlite3.connect(DB)
    try:
        conn.execute(
            """
            INSERT INTO annotations
              (track_id, valence, arousal, tension, tags_json, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_id) DO UPDATE SET
              valence=excluded.valence,
              arousal=excluded.arousal,
              tension=excluded.tension,
              tags_json=excluded.tags_json,
              note=excluded.note,
              updated_at=excluded.updated_at
            """,
            (
                payload.track_id,
                payload.valence,
                payload.arousal,
                payload.tension,
                json.dumps(payload.tags, ensure_ascii=False),
                payload.note,
                stamp,
                stamp,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "updated_at": stamp}


@app.delete("/api/annotations/{track_id}")
def delete_annotation(track_id: str) -> dict:
    conn = sqlite3.connect(DB)
    try:
        conn.execute("DELETE FROM annotations WHERE track_id=?", (track_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def theme_colors() -> dict[str, Any]:
    fallback = {
        "mode": "dark",
        "background": "#000000",
        "dark_background": "#090909",
        "darker_background": "#070707",
        "lighter_background": "#1a1a1a",
        "foreground": "#cacccc",
        "muted": "#7a7f82",
        "accent": "#798186",
        "selection": "#343d41",
        "red": "#de6145",
        "yellow": "#c9c2b4",
        "green": "#9fa5a9",
        "cyan": "#707070",
        "blue": "#798186",
        "magenta": "#9a9a9a",
    }
    try:
        name = subprocess.run(
            ["omarchy", "theme", "current"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
    except Exception:
        name = ""
    candidates = [
        Path.home() / ".config" / "omarchy" / "current" / "colors.toml",
        Path.home() / ".config" / "omarchy" / "themes" / name / "colors.toml",
    ]
    for path in candidates:
        try:
            if path.exists():
                data = tomllib.loads(path.read_text())
                for key, value in fallback.items():
                    if key in data and isinstance(data[key], str):
                        fallback[key] = data[key]
                fallback["theme"] = name
                return fallback
        except Exception:
            continue
    fallback["theme"] = name or "fallback"
    return fallback


@app.get("/api/theme")
def theme() -> dict:
    return theme_colors()


@app.post("/api/scan")
def scan() -> dict:
    lib = read_library()
    known = {t["file_path"] for t in lib["tracks"]}
    found = []
    for mp3 in sorted(AUDIO.glob("*.mp3")):
        rel = str(mp3.relative_to(ROOT))
        if rel not in known:
            found.append({"file": rel, "bytes": mp3.stat().st_size})
    return {
        "new_files": found,
        "message": "Relancer analysis/analyze.py pour analyser les nouveaux fichiers.",
    }


@app.exception_handler(404)
def not_found(_request, exc):
    return JSONResponse({"error": "not_found", "detail": str(exc.detail)}, status_code=404)


app.mount("/", StaticFiles(directory=str(APP_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("ATLAS_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
