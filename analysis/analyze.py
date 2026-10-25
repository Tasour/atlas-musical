#!/usr/bin/env python3
"""Analyse la bibliothèque, calcule les scores et construit SQLite + JSON."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .catalog import TRACKS
    from .features import extract
    from .model import USAGE_NAMES, score_all
except ImportError:
    from catalog import TRACKS
    from features import extract
    from model import USAGE_NAMES, score_all

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
FEATURES = WORK / "features"
FEATURE_VERSION = "1.1"
DATA = ROOT / "data"
DB = DATA / "library.sqlite"
LIB_JSON = DATA / "library.json"
MANIFEST = DATA / "manifest.json"
DOWNLOAD_MANIFEST = WORK / "download_manifest.json"
EXPORTS = DATA / "exports"

for d in (FEATURES, DATA, EXPORTS):
    d.mkdir(parents=True, exist_ok=True)

TAG_META = {
    "Joie": ("émotion", "#e8b84b", "Lumière, ouverture, plaisir immédiat."),
    "Tristesse": ("émotion", "#6d8fb8", "Couleur grave, retenue, mélancolie."),
    "Nostalgie": ("émotion", "#b08a6a", "Mémoire, texture acoustique, passé."),
    "Ambiance": ("texture", "#7f8fa6", "Nappe, texture, peu d'événements rythmiques."),
    "Tension": ("émotion", "#c45a5a", "Rugosité, dissonance, attente."),
    "Aventure": ("émotion", "#d98b4a", "Élan, mouvement, horizon."),
    "Apaisement": ("émotion", "#6fa89a", "Basse énergie, stabilité, respiration."),
    "Émerveillement": ("émotion", "#9a8cc9", "Ampleur, largeur stéréo, suspension."),
    "Intimité": ("émotion", "#b07a8f", "Proximité, faible densité, acoustique."),
    "Romance": ("émotion", "#d18b9e", "Douceur, consonance, chaleur."),
    "Énergie": ("émotion", "#e0a33e", "Densité rythmique, attaque, brillance."),
    "Instrumental": ("texture", "#8a969c", "Aucune voix principale."),
    "Littoral": ("contexte", "#5fa8b8", "Côte, océan, lumière."),
    "Aride/outback": ("contexte", "#c97b4a", "Terre rouge, horizon sec, route."),
    "Brousse": ("contexte", "#8b9a5b", "Végétation, folk, intérieur."),
    "Nuit/route": ("contexte", "#6c7fa3", "Nuit, route, introspection."),
}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS tracks (
  id TEXT PRIMARY KEY,
  youtube_id TEXT UNIQUE NOT NULL,
  source_title TEXT,
  title TEXT NOT NULL,
  artist TEXT NOT NULL,
  credit TEXT,
  license TEXT,
  license_url TEXT,
  source_url TEXT,
  file_path TEXT NOT NULL,
  family TEXT,
  genre TEXT,
  note TEXT,
  duration REAL,
  bpm REAL,
  bpm_confidence REAL,
  key TEXT,
  mode TEXT,
  key_confidence REAL,
  valence REAL,
  arousal REAL,
  tension REAL,
  confidence REAL,
  valence01 REAL,
  arousal01 REAL,
  tension01 REAL,
  ellipse_rx REAL,
  ellipse_ry REAL,
  energy REAL,
  danceability REAL,
  acousticness REAL,
  loopability REAL,
  hook_start REAL,
  hook_duration REAL,
  intro_end REAL,
  peak_time REAL,
  outro_start REAL,
  arc_type TEXT,
  loudness_lufs REAL,
  dynamic_range REAL,
  crest REAL,
  features_json TEXT,
  tags_json TEXT,
  usage_json TEXT,
  tag_scores_json TEXT,
  usage_scores_json TEXT,
  arc_json TEXT,
  cut_points_json TEXT,
  sha256 TEXT,
  status TEXT DEFAULT 'ready',
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  category TEXT NOT NULL,
  color TEXT NOT NULL,
  description TEXT
);
CREATE TABLE IF NOT EXISTS track_tags (
  track_id TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  score REAL NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'auto',
  PRIMARY KEY (track_id, tag_id)
);
CREATE TABLE IF NOT EXISTS annotations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  track_id TEXT UNIQUE NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
  valence REAL,
  arousal REAL,
  tension REAL,
  tags_json TEXT,
  note TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  finished_at TEXT,
  version TEXT,
  params_json TEXT,
  stats_json TEXT,
  status TEXT,
  log TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_family ON tracks(family);
CREATE INDEX IF NOT EXISTS idx_tracks_scores ON tracks(valence, arousal, tension);
CREATE INDEX IF NOT EXISTS idx_track_tags_tag ON track_tags(tag_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def load_manifest() -> dict:
    if not DOWNLOAD_MANIFEST.exists():
        return {}
    return json.loads(DOWNLOAD_MANIFEST.read_text())


def feature_path(track_id: str) -> Path:
    return FEATURES / f"{track_id}.json"


def get_features(track: dict, download: dict) -> dict:
    fp = feature_path(track["id"])
    wav = ROOT / download["wav"]
    if fp.exists() and wav.exists() and fp.stat().st_mtime >= wav.stat().st_mtime:
        try:
            cached = json.loads(fp.read_text())
            if cached.get("analysis_version") == FEATURE_VERSION:
                return cached
        except Exception:
            pass
    print(f"[analyse] {track['id']} — {wav.name}", flush=True)
    feats = extract(wav)
    write_json(fp, feats)
    return feats


def build_credits(rows: list[dict]) -> str:
    lines = [
        "# Crédits musicaux — Atlas Musical",
        "",
        "Toutes les pistes sont instrumentales et destinées au montage vidéo.",
        "Les licences ont été vérifiées sur les pages source au moment du téléchargement.",
        "Conserver ce fichier avec les MP3 et vérifier la licence avant toute publication",
        "monétisée : une licence Creative Commons peut cohabiter avec un Content ID YouTube.",
        "",
        "## Pistes",
        "",
    ]
    for i, row in enumerate(rows, 1):
        meta = row["meta"]
        lines += [
            f"### {i}. {meta['title']} — {meta['artist']}",
            "",
            f"- **Source** : {meta['source_url']}",
            f"- **Licence** : {meta['license']} ({meta['license_url']})",
            f"- **Crédit à afficher** : {meta['credit']}",
            f"- **Fichier** : `{row['file_path']}`",
            f"- **Genre / famille** : {meta['genre']} / {meta['family']}",
        ]
        if row.get("source_title") and row["source_title"] != meta["title"]:
            lines.append(f"- **Titre source** : {row['source_title']}")
        if meta.get("note"):
            lines.append(f"- **Note éditoriale** : {meta['note']}")
        lines.append("")
    lines += [
        "## Attribution type",
        "",
        "> Musique : « {titre} » par {artiste}, sous licence {licence}. Source : {url}",
        "",
        "Pour les pistes indiquées « gratuit avec crédit », la mention du crédit",
        "ci-dessus est obligatoire même si la licence YouTube affichée est CC BY.",
        "",
        "## Content ID",
        "",
        "Une licence CC BY n'empêche pas un ayant droit de revendiquer une piste via",
        "Content ID. En cas de réclamation, conserver la capture de la page source,",
        "la date de téléchargement et ce fichier de crédits.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    started = now()
    download = load_manifest()
    ready: list[tuple[dict, dict]] = []
    for track in TRACKS:
        entry = download.get(track["id"])
        if not entry or entry.get("status") not in {"ok", "cached"}:
            print(f"[skip] {track['id']} : téléchargement absent/échoué", flush=True)
            continue
        if not (ROOT / entry["wav"]).exists():
            print(f"[skip] {track['id']} : WAV absent", flush=True)
            continue
        ready.append((track, entry))
    if not ready:
        print("Aucune piste prête. Lancer analysis/download.py d'abord.", file=sys.stderr)
        return 2

    features: list[dict] = []
    metas: list[dict] = []
    entries: list[dict] = []
    for track, entry in ready:
        feats = get_features(track, entry)
        features.append(feats)
        metas.append(track)
        entries.append(entry)

    scored, stats = score_all(features, metas)
    rows = []
    for item, entry in zip(scored, entries):
        meta = item["meta"]
        feats = item["features"]
        scores = item["scores"]
        rows.append(
            {
                "meta": meta,
                "features": feats,
                "scores": scores,
                "entry": entry,
                "file_path": entry["mp3"],
                "source_title": entry.get("source_title"),
            }
        )

    run_id = None
    conn = sqlite3.connect(DB)
    try:
        conn.executescript(SCHEMA)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO analysis_runs (started_at, version, params_json, stats_json, status, log) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                started,
                "1.1",
                json.dumps({"features": 18, "corpus": len(rows)}, ensure_ascii=False),
                json.dumps(stats, ensure_ascii=False),
                "running",
                "",
            ),
        )
        run_id = cur.lastrowid

        for name in sorted(TAG_META):
            category, color, desc = TAG_META[name]
            cur.execute(
                "INSERT INTO tags (name, category, color, description) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET category=excluded.category, "
                "color=excluded.color, description=excluded.description",
                (name, category, color, desc),
            )
        cur.execute("SELECT id, name FROM tags")
        tag_ids = dict(cur.fetchall())

        stamp = now()
        for row in rows:
            meta = row["meta"]
            feats = row["features"]
            scores = row["scores"]
            entry = row["entry"]
            cur.execute("DELETE FROM tracks WHERE id = ?", (meta["id"],))
            cur.execute(
                """
                INSERT INTO tracks (
                  id, youtube_id, source_title, title, artist, credit, license,
                  license_url, source_url, file_path, family, genre, note,
                  duration, bpm, bpm_confidence, key, mode, key_confidence,
                  valence, arousal, tension, confidence, valence01, arousal01,
                  tension01, ellipse_rx, ellipse_ry, energy, danceability,
                  acousticness, loopability, hook_start, hook_duration, intro_end,
                  peak_time, outro_start, arc_type, loudness_lufs, dynamic_range,
                  crest, features_json, tags_json, usage_json, tag_scores_json,
                  usage_scores_json, arc_json, cut_points_json, sha256, status,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    meta["id"],
                    meta["youtube_id"],
                    entry.get("source_title"),
                    meta["title"],
                    meta["artist"],
                    meta["credit"],
                    meta["license"],
                    meta["license_url"],
                    meta["source_url"],
                    row["file_path"],
                    meta["family"],
                    meta["genre"],
                    meta.get("note"),
                    feats.get("duration"),
                    feats.get("tempo"),
                    feats.get("tempo_confidence"),
                    feats.get("key"),
                    feats.get("mode"),
                    feats.get("key_confidence"),
                    scores["valence"],
                    scores["arousal"],
                    scores["tension"],
                    scores["confidence"],
                    scores["valence01"],
                    scores["arousal01"],
                    scores["tension01"],
                    scores["ellipse_rx"],
                    scores["ellipse_ry"],
                    feats.get("energy"),
                    feats.get("danceability"),
                    feats.get("acousticness"),
                    feats.get("loopability"),
                    feats.get("hook_start"),
                    feats.get("hook_duration"),
                    feats.get("intro_end"),
                    feats.get("peak_time"),
                    feats.get("outro_start"),
                    feats.get("arc_type"),
                    entry.get("loudness_input_lufs"),
                    feats.get("dynamic_range_db"),
                    feats.get("crest_db"),
                    json.dumps(feats, ensure_ascii=False),
                    json.dumps(scores["tags"], ensure_ascii=False),
                    json.dumps(scores["usages"], ensure_ascii=False),
                    json.dumps(scores["tag_scores"], ensure_ascii=False),
                    json.dumps(scores["usage_scores"], ensure_ascii=False),
                    json.dumps(feats.get("arc"), ensure_ascii=False),
                    json.dumps(feats.get("cut_points"), ensure_ascii=False),
                    entry.get("sha256"),
                    "ready",
                    stamp,
                    stamp,
                ),
            )
            for tag in scores["tags"]:
                tid = tag_ids.get(tag)
                if tid is None:
                    continue
                cur.execute(
                    "INSERT OR REPLACE INTO track_tags (track_id, tag_id, score, source) "
                    "VALUES (?, ?, ?, 'auto')",
                    (meta["id"], tid, scores["tag_scores"].get(tag, 0.0)),
                )
        cur.execute(
            "UPDATE analysis_runs SET finished_at=?, status=?, log=? WHERE id=?",
            (now(), "ok", f"{len(rows)} pistes analysées", run_id),
        )
        conn.commit()
    finally:
        conn.close()

    tracks_json = []
    for row in rows:
        meta, feats, scores, entry = (
            row["meta"],
            row["features"],
            row["scores"],
            row["entry"],
        )
        tracks_json.append(
            {
                "id": meta["id"],
                "youtube_id": meta["youtube_id"],
                "title": meta["title"],
                "artist": meta["artist"],
                "credit": meta["credit"],
                "license": meta["license"],
                "license_url": meta["license_url"],
                "source_url": meta["source_url"],
                "source_title": row.get("source_title"),
                "file_path": row["file_path"],
                "audio_url": f"/api/audio/{meta['id']}",
                "family": meta["family"],
                "genre": meta["genre"],
                "note": meta.get("note"),
                "duration": feats.get("duration"),
                "bpm": feats.get("tempo"),
                "bpm_confidence": feats.get("tempo_confidence"),
                "key": feats.get("key"),
                "mode": feats.get("mode"),
                "key_confidence": feats.get("key_confidence"),
                "valence": scores["valence"],
                "arousal": scores["arousal"],
                "tension": scores["tension"],
                "valence01": scores["valence01"],
                "arousal01": scores["arousal01"],
                "tension01": scores["tension01"],
                "confidence": scores["confidence"],
                "ellipse_rx": scores["ellipse_rx"],
                "ellipse_ry": scores["ellipse_ry"],
                "energy": feats.get("energy"),
                "danceability": feats.get("danceability"),
                "acousticness": feats.get("acousticness"),
                "loopability": feats.get("loopability"),
                "hook_start": feats.get("hook_start"),
                "hook_duration": feats.get("hook_duration"),
                "intro_end": feats.get("intro_end"),
                "peak_time": feats.get("peak_time"),
                "outro_start": feats.get("outro_start"),
                "arc": feats.get("arc"),
                "arc_type": feats.get("arc_type"),
                "cut_points": feats.get("cut_points"),
                "tags": scores["tags"],
                "tag_scores": scores["tag_scores"],
                "usages": scores["usages"],
                "usage_scores": scores["usage_scores"],
                "features": feats,
                "loudness_lufs": entry.get("loudness_input_lufs"),
                "sha256": entry.get("sha256"),
            }
        )

    tag_list = [
        {
            "name": name,
            "category": category,
            "color": color,
            "description": desc,
        }
        for name, (category, color, desc) in TAG_META.items()
    ]
    library = {
        "meta": {
            "app": "Atlas Musical",
            "version": "1.1",
            "generated_at": now(),
            "corpus_size": len(tracks_json),
            "model_version": "1.1",
            "analysis_version": FEATURE_VERSION,
            "audio_format": "MP3 320 kb/s, 48 kHz, stéréo, -16 LUFS",
            "coordinates": {
                "x": "calme → énergique (arousal)",
                "y": "mélancolique → solaire (valence)",
                "color": "tension",
                "size": "confiance",
            },
            "disclaimer": (
                "Les scores estiment un profil affectif perçu, pas un état émotionnel "
                "réel. Ils sont relatifs au corpus et doivent être validés à l'écoute."
            ),
            "methodology": "METHODOLOGY.md",
            "credits": "CREDITS.md",
        },
        "tags": tag_list,
        "usages": USAGE_NAMES,
        "tracks": tracks_json,
    }
    write_json(LIB_JSON, library)

    # Annotations existantes, fusionnées pour le client.
    try:
        conn = sqlite3.connect(DB)
        conn.row_factory = sqlite3.Row
        anns = {
            r["track_id"]: dict(r)
            for r in conn.execute("SELECT * FROM annotations").fetchall()
        }
        conn.close()
    except Exception:
        anns = {}
    for track in library["tracks"]:
        a = anns.get(track["id"])
        if a:
            track["annotation"] = {
                "valence": a.get("valence"),
                "arousal": a.get("arousal"),
                "tension": a.get("tension"),
                "tags": json.loads(a.get("tags_json") or "[]"),
                "note": a.get("note"),
                "updated_at": a.get("updated_at"),
            }
    write_json(LIB_JSON, library)

    manifest = {
        "app": "Atlas Musical",
        "version": "1.1",
        "generated_at": now(),
        "tracks": len(tracks_json),
        "database": "data/library.sqlite",
        "json": "data/library.json",
        "audio_dir": "audio",
        "exports_dir": "data/exports",
        "tags": len(tag_list),
        "model_version": "1.1",
        "analysis_version": FEATURE_VERSION,
    }
    write_json(MANIFEST, manifest)
    (ROOT / "CREDITS.md").write_text(build_credits(rows), encoding="utf-8")

    try:
        try:
            from .cluster import build_and_write as build_clusters
        except ImportError:
            from cluster import build_and_write as build_clusters
        clusters = build_clusters(library)
        print(
            f"CLUSTERS : {len(clusters['clusters'])} groupes "
            f"(silhouette {clusters['silhouette']:+.3f})"
        )
    except Exception as exc:
        print(f"[clusters] échec : {exc}", file=sys.stderr)

    print(f"OK : {len(tracks_json)} pistes, {len(tag_list)} tags")
    print(f"DB : {DB}")
    print(f"JSON : {LIB_JSON}")
    return 0 if len(tracks_json) == len(ready) else 1


if __name__ == "__main__":
    sys.exit(main())
