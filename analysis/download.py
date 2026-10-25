#!/usr/bin/env python3
"""Télécharge, normalise et encode les titres du catalogue.

Sorties :
  work/download/<youtube_id>.<ext>   source yt-dlp
  work/wav/<id>.wav                  WAV 48 kHz stéréo normalisé -16 LUFS
  audio/<id>__<slug>.mp3             MP3 320 kb/s taggé
  work/download_manifest.json        traçabilité (durée, loudness, hash)
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from .catalog import TRACKS
except ImportError:
    from catalog import TRACKS

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD = ROOT / "work" / "download"
WAV = ROOT / "work" / "wav"
AUDIO = ROOT / "audio"
DATA = ROOT / "data"
MANIFEST = ROOT / "work" / "download_manifest.json"

for d in (DOWNLOAD, WAV, AUDIO, DATA):
    d.mkdir(parents=True, exist_ok=True)

LOCK = threading.Lock()
RESULTS: dict[str, dict] = {}
if MANIFEST.exists():
    try:
        RESULTS = json.loads(MANIFEST.read_text())
    except Exception:
        RESULTS = {}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def save_manifest() -> None:
    with LOCK:
        tmp = MANIFEST.with_suffix(".tmp")
        tmp.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2))
        tmp.replace(MANIFEST)


def ffprobe(path: Path) -> dict:
    p = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe: {p.stderr.strip()}")
    data = json.loads(p.stdout)
    stream = (data.get("streams") or [{}])[0]
    return {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
    }


def find_source(yt_id: str) -> Path | None:
    candidates = [
        p
        for p in DOWNLOAD.glob(f"{yt_id}.*")
        if p.suffix not in {".part", ".ytdl", ".json", ".tmp"}
        and p.is_file()
        and p.stat().st_size > 50_000
    ]
    return max(candidates, key=lambda p: p.stat().st_size) if candidates else None


def parse_printed(stdout: str) -> dict:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        for key in ("TITLE", "UPLOADER", "DURATION"):
            prefix = f"__YT_{key}__"
            if line.startswith(prefix):
                out[key.lower()] = line[len(prefix) :].strip()
    return out


def download_source(track: dict) -> tuple[Path, dict]:
    existing = find_source(track["youtube_id"])
    if existing:
        return existing, {}
    yt_id = track["youtube_id"]
    url = track["source_url"]
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        "--no-progress",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--concurrent-fragments",
        "4",
        "-f",
        "bestaudio/best",
        "-o",
        str(DOWNLOAD / "%(id)s.%(ext)s"),
        "--print",
        "after_move:__YT_TITLE__%(title)s",
        "--print",
        "after_move:__YT_UPLOADER__%(uploader)s",
        "--print",
        "after_move:__YT_DURATION__%(duration)s",
        url,
    ]
    log(f"yt-dlp {yt_id} — {track['artist']} / {track['title']}")
    p = run(cmd, timeout=1200)
    if p.returncode != 0:
        raise RuntimeError(f"yt-dlp {yt_id}: {p.stderr.strip()[-900:]}")
    source = find_source(yt_id)
    if not source:
        raise RuntimeError(f"yt-dlp {yt_id}: fichier introuvable")
    return source, parse_printed(p.stdout)


def first_pass_loudnorm(source: Path) -> dict:
    p = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(source),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        timeout=900,
    )
    if p.returncode != 0:
        return {}
    matches = re.findall(r"\{[^{}]+\}", p.stderr, flags=re.S)
    for raw in reversed(matches):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "input_i" in data:
            return data
    return {}


def normalize(source: Path, track: dict, loud: dict) -> Path:
    dest = WAV / f"{track['id']}.wav"
    if dest.exists() and dest.stat().st_size > 500_000:
        return dest
    filt = "loudnorm=I=-16:TP=-1.5:LRA=11"
    if loud:
        filt = (
            "loudnorm=I=-16:TP=-1.5:LRA=11"
            f":measured_I={loud.get('input_i', '-16')}"
            f":measured_TP={loud.get('input_tp', '-1.5')}"
            f":measured_LRA={loud.get('input_lra', '11')}"
            f":measured_thresh={loud.get('input_thresh', '-26')}"
            f":offset={loud.get('target_offset', '0')}"
            ":linear=true"
        )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-ar",
        "48000",
        "-ac",
        "2",
        "-af",
        filt,
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    p = run(cmd, timeout=1200)
    if p.returncode != 0:
        if loud:
            log(f"loudnorm linéaire impossible pour {track['id']}, fallback simple passe")
            return normalize(source, track, {})
        raise RuntimeError(f"ffmpeg normalisation {track['id']}: {p.stderr[-900:]}")
    return dest


def encode_mp3(wav: Path, track: dict, source_info: dict, loud: dict) -> Path:
    dest = AUDIO / f"{track['id']}__{track['youtube_id']}.mp3"
    comment = (
        f"Source : {track['source_url']} | Licence : {track['license']} | "
        f"Crédit : {track['credit']} | Analyse : Atlas Musical"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostats",
        "-i",
        str(wav),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        "-id3v2_version",
        "3",
        "-write_id3v1",
        "1",
        "-metadata",
        f"title={track['title']}",
        "-metadata",
        f"artist={track['artist']}",
        "-metadata",
        "album=Atlas Musical",
        "-metadata",
        f"album_artist={track['artist']}",
        "-metadata",
        f"genre={track['genre']}",
        "-metadata",
        "date=2026",
        "-metadata",
        f"comment={comment}",
        "-metadata",
        f"copyright={track['license']} — {track['credit']}",
        "-metadata",
        f"source={track['source_url']}",
        str(dest),
    ]
    p = run(cmd, timeout=900)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg MP3 {track['id']}: {p.stderr[-900:]}")
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def process(track: dict) -> tuple[str, dict]:
    final = AUDIO / f"{track['id']}__{track['youtube_id']}.mp3"
    if final.exists() and final.stat().st_size > 200_000:
        try:
            probe = ffprobe(final)
        except Exception:
            probe = {}
        log(f"déjà présent : {final.name}")
        return track["id"], {
            **track,
            "status": "cached",
            "mp3": str(final.relative_to(ROOT)),
            "wav": str((WAV / f"{track['id']}.wav").relative_to(ROOT)),
            "duration": probe.get("duration"),
            "sha256": sha256(final),
        }

    source, printed = download_source(track)
    info = ffprobe(source)
    log(f"  source {source.name} ({info['duration']:.1f}s) — normalisation")
    loud = first_pass_loudnorm(source)
    wav = normalize(source, track, loud)
    log(f"  WAV {wav.name} — encodage MP3")
    mp3 = encode_mp3(wav, track, info, loud)
    probe = ffprobe(mp3)
    result = {
        **track,
        "status": "ok",
        "source_title": printed.get("title"),
        "source_uploader": printed.get("uploader"),
        "mp3": str(mp3.relative_to(ROOT)),
        "wav": str(wav.relative_to(ROOT)),
        "duration": round(probe["duration"], 3),
        "source_duration": round(info["duration"], 3),
        "source_codec": info["codec"],
        "sample_rate": probe["sample_rate"],
        "channels": probe["channels"],
        "loudness_input_lufs": loud.get("input_i"),
        "loudness_input_tp": loud.get("input_tp"),
        "loudness_input_lra": loud.get("input_lra"),
        "bytes": mp3.stat().st_size,
        "sha256": sha256(mp3),
    }
    log(f"  OK {mp3.name} ({mp3.stat().st_size / 1e6:.1f} Mo)")
    return track["id"], result


def main() -> int:
    pending = [t for t in TRACKS if not (
        (AUDIO / f"{t['id']}__{t['youtube_id']}.mp3").exists()
        and (AUDIO / f"{t['id']}__{t['youtube_id']}.mp3").stat().st_size > 200_000
    )]
    log(f"{len(TRACKS)} titres, {len(pending)} à traiter")
    failed: list[tuple[str, str]] = []

    def worker(track: dict):
        try:
            tid, res = process(track)
            with LOCK:
                RESULTS[tid] = res
            save_manifest()
            return res
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            log(f"ECHEC {track['id']}: {msg}")
            with LOCK:
                RESULTS[track["id"]] = {
                    **track,
                    "status": "error",
                    "error": msg,
                }
            save_manifest()
            failed.append((track["id"], msg))
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(worker, pending))

    ok = sum(1 for r in RESULTS.values() if r.get("status") in {"ok", "cached"})
    log(f"Terminé : {ok}/{len(TRACKS)} titres disponibles")
    if failed:
        for tid, msg in failed:
            log(f"  échec {tid}: {msg}")
        return 1
    return 0 if ok == len(TRACKS) else 1


if __name__ == "__main__":
    sys.exit(main())
