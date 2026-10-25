#!/usr/bin/env python3
"""Découvre automatiquement des pistes instrumentales CC BY sur YouTube.

Les candidats sont filtrés (licence Creative Commons, durée, vues, caractère
instrumental) puis ajoutés à `data/catalog.local.json`, non versionné. Le
catalogue public de `analysis/catalog.py` n'est jamais modifié.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import deque
from urllib.parse import quote_plus

try:
    from .catalog import LOCAL_CATALOG, PUBLIC_TRACKS
except ImportError:
    from catalog import LOCAL_CATALOG, PUBLIC_TRACKS

QUERIES = {
    "acoustique": [
        "acoustic guitar instrumental",
        "fingerstyle guitar instrumental",
        "piano instrumental solo",
        "folk instrumental",
        "ukulele instrumental",
        "classical guitar instrumental",
        "cello instrumental",
    ],
    "cinematique": [
        "cinematic instrumental",
        "ambient instrumental",
        "orchestral instrumental",
        "piano ambient instrumental",
        "documentary instrumental",
        "emotional piano instrumental",
        "epic orchestral music",
    ],
    "tropical": [
        "tropical instrumental",
        "chill instrumental",
        "reggae instrumental",
        "latin instrumental",
        "beach instrumental",
        "summer instrumental",
        "lo-fi instrumental",
    ],
    "intense": [
        "epic instrumental",
        "rock instrumental",
        "percussion instrumental",
        "action instrumental",
        "trailer music",
        "guitar riff instrumental",
        "drum instrumental",
    ],
}

CHANNELS = {
    "acoustique": [
        "https://www.youtube.com/@audionautix/videos",
        "https://www.youtube.com/@podingtonbear/videos",
        "https://www.youtube.com/@Cullah/videos",
        "https://www.youtube.com/@Scandinavianz/videos",
        "https://www.youtube.com/@Lesfm/videos",
    ],
    "cinematique": [
        "https://www.youtube.com/@ScottBuckley/videos",
        "https://www.youtube.com/@GhostrifterOfficial/videos",
        "https://www.youtube.com/@DarrenCurtisMusic/videos",
        "https://www.youtube.com/@ChrisZabriskie/videos",
        "https://www.youtube.com/@JonnyEaston/videos",
        "https://www.youtube.com/@Sappheiros/videos",
        "https://www.youtube.com/@alexandernakarada/videos",
        "https://www.youtube.com/@Myuu/videos",
        "https://www.youtube.com/@AShamaluevMusic/videos",
        "https://www.youtube.com/@RafaelKrux/videos",
    ],
    "tropical": [
        "https://www.youtube.com/@tubebackr/videos",
        "https://www.youtube.com/@FASSounds/videos",
        "https://www.youtube.com/@BrokeForFree/videos",
        "https://www.youtube.com/@VlogNoCopyrightMusic/videos",
        "https://www.youtube.com/@eklipsemusic/videos",
        "https://www.youtube.com/@Musicfox/videos",
    ],
    "intense": [
        "https://www.youtube.com/@RossBugden/videos",
        "https://www.youtube.com/@MokkaMusic/videos",
        "https://www.youtube.com/@Soundridemusic/videos",
        "https://www.youtube.com/@AnnoDominiNation/videos",
    ],
}

GENRES = {
    "acoustique": "Acoustic / folk",
    "cinematique": "Cinematic / ambient",
    "tropical": "Tropical / chill",
    "intense": "Intense / aventure",
}

KNOWN_CHANNELS = {
    "oak studios",
    "kevin macleod",
    "incompetech",
    "scott buckley",
    "kai engel",
    "luke bergs",
    "sebastian lindsjö",
    "migfus",
    "derek clegg",
    "jonas schmidt",
    "alexander nakarada",
    "myuu",
    "purple planet music",
    "whitesand",
    "sappheiros",
    "ghostrifter",
    "twin musicom",
    "audionautix",
    "chris zabriskie",
    "josh woodward",
    "podington bear",
    "doctor turtle",
    "broke for free",
    "rafael krux",
    "cullah",
}

NOISE = re.compile(
    r"[\[(]\s*(?:no copyright(?: music)?|royalty[- ]free(?: music)?|creative commons|"
    r"free music|background music|music for videos?)\s*[\])]",
    re.I,
)
TRAILING = re.compile(
    r"\s*[|·]\s*(?:background music|royalty[- ]free|no copyright|creative commons).*$",
    re.I,
)
CC_TAG = re.compile(r"\s*\[[^\]]*CC[- ]?BY[^\]]*\]", re.I)
MIX = re.compile(r"\b(?:mix|hours?|compilation|playlist)\b", re.I)
BAD_TITLE = re.compile(
    r"\b(?:cover(?:ed|s)?|karaoke|backing|type beat|inst|tab|arrangement|version|worship|"
    r"hillsong|elevation|hymn|gospel|christian|praise|christmas|carol|birthday|tutorial|"
    r"lesson|synthesia|sheet|remix|tribute|medley|tabs)\b",
    re.I,
)
BAD_CHANNEL = re.compile(r"\b(?:worship|hillsong|karaoke|tutorial|sheet)\b", re.I)
COVER_CHANNELS = re.compile(
    r"angelo magnaye|pip r\.? lagenta|elliot ward|i\.?o\.?o\.?p|shane hennessy|"
    r"karla garc|keizo ishibashi|raizenron|dave caruso|lance austria|"
    r"jon michael ogletree|josiah simon|drasticshotter|jack isidore|soundsforsoul|"
    r"captamazo|david beckingham|benote",
    re.I,
)
COVER_HINTS = re.compile(
    r"\b(?:moon river|funicul|totoro|la paloma|frankie and johnny|song of the islands|"
    r"lazy moon|irreplaceable|norah jones|ed sheeran|where do i begin|am i blue|"
    r"san francisco|somewhere out there|jerusalem|the water is wide|wayfaring stranger|"
    r"dakilang|musikatha|kalakip|antukin|rico blanco|arne de pano|michael w smith|"
    r"hark the herald|blessed assurance|it is well|genesis piano|august rush|"
    r"beautiful south|rotterdam|i love you|can'?t stop loving|left my heart)\b",
    re.I,
)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def clean_title(value: str, channel: str = "") -> str:
    title = CC_TAG.sub(" ", value)
    title = NOISE.sub(" ", title)
    title = TRAILING.sub("", title)
    title = re.sub(r"\s+", " ", title).strip(" -–—|·")
    if channel:
        suffix = re.compile(rf"\s[-–—]\s*{re.escape(channel)}\s*$", re.I)
        title = suffix.sub("", title).strip()
    return title or value.strip()


def search_url(query: str) -> str:
    return (
        "https://www.youtube.com/results?search_query="
        f"{quote_plus(query)}&sp=EgIwAQ%253D%253D"
    )


def fetch(url: str, per_query: int) -> list[dict]:
    command = [
        "yt-dlp",
        "--dump-json",
        "--skip-download",
        "--no-warnings",
        "--ignore-errors",
        "--socket-timeout",
        "20",
        "--extractor-retries",
        "2",
        "--playlist-end",
        str(per_query),
        url,
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
    results: list[dict] = []
    for line in process.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return results


def normalize(
    raw: dict,
    family: str,
    used_ids: set[str],
    used_yt: set[str],
    min_duration: int,
    max_duration: int,
    min_views: int,
    trusted: bool = False,
) -> dict | None:
    youtube_id = str(raw.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", youtube_id) or youtube_id in used_yt:
        return None

    license_raw = str(raw.get("license") or "")
    if "creative commons" not in license_raw.lower():
        return None

    duration = float(raw.get("duration") or 0)
    if duration < min_duration or duration > max_duration:
        return None

    views = int(raw.get("view_count") or 0)
    if views < min_views:
        return None

    if raw.get("is_live") or raw.get("age_limit"):
        return None
    if raw.get("availability") not in (None, "public"):
        return None

    raw_title = str(raw.get("title") or "")
    title = str(raw.get("track") or raw_title or youtube_id)
    if any(
        MIX.search(value) or BAD_TITLE.search(value) or COVER_HINTS.search(value)
        for value in {raw_title, title}
    ):
        return None

    channel = str(raw.get("channel") or raw.get("uploader") or "YouTube").strip()
    channel = re.sub(r"\s*-\s*Topic$", "", channel) or "YouTube"
    if BAD_CHANNEL.search(channel) or COVER_CHANNELS.search(channel):
        return None

    tags = raw.get("tags") or []
    haystack = " ".join(
        [title, raw_title, str(raw.get("description") or ""), channel, " ".join(map(str, tags))]
    ).lower()
    if (
        not trusted
        and "instrumental" not in haystack
        and channel.lower() not in KNOWN_CHANNELS
    ):
        return None

    clean = clean_title(title, channel)
    base = "-".join(part for part in (slugify(channel)[:24], slugify(clean)[:32]) if part)
    track_id = base or f"cc-{youtube_id.lower()}"
    if track_id in used_ids:
        track_id = f"{track_id}-{youtube_id[:5].lower()}"
    if track_id in used_ids:
        return None

    used_ids.add(track_id)
    used_yt.add(youtube_id)
    source_url = raw.get("webpage_url") or f"https://www.youtube.com/watch?v={youtube_id}"
    return {
        "id": track_id,
        "youtube_id": youtube_id,
        "title": clean,
        "artist": channel,
        "family": family,
        "genre": GENRES[family],
        "credit": channel,
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_url": source_url,
        "note": f"Découverte automatique · {views:,} vues · licence source : {license_raw}",
    }


def is_cover(track: dict) -> bool:
    haystack = f"{track.get('artist', '')} {track.get('title', '')}"
    return bool(
        BAD_TITLE.search(haystack)
        or BAD_CHANNEL.search(haystack)
        or COVER_CHANNELS.search(haystack)
        or COVER_HINTS.search(haystack)
    )


def load_existing() -> list[dict]:
    if not LOCAL_CATALOG.exists():
        return []
    try:
        payload = json.loads(LOCAL_CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("tracks", [])
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def write_local(tracks: list[dict]) -> None:
    LOCAL_CATALOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL_CATALOG.with_name(f"{LOCAL_CATALOG.name}.tmp")
    tmp.write_text(json.dumps(tracks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LOCAL_CATALOG)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=50, help="nombre de nouvelles pistes")
    parser.add_argument("--per-query", type=int, default=25, help="résultats par requête")
    parser.add_argument("--workers", type=int, default=3, help="recherches en parallèle")
    parser.add_argument("--family", action="append", choices=sorted(QUERIES), help="famille à explorer")
    parser.add_argument("--channels-only", action="store_true", help="n'utiliser que les chaînes de confiance")
    parser.add_argument("--no-channels", action="store_true", help="ignorer les chaînes de confiance")
    parser.add_argument("--min-duration", type=int, default=60)
    parser.add_argument("--max-duration", type=int, default=900)
    parser.add_argument("--min-views", type=int, default=500)
    args = parser.parse_args()

    if not shutil.which("yt-dlp"):
        print("yt-dlp est requis.", file=sys.stderr)
        return 2

    existing = load_existing()
    used_ids = {track["id"] for track in PUBLIC_TRACKS} | {track["id"] for track in existing}
    used_yt = {track["youtube_id"] for track in PUBLIC_TRACKS} | {
        track["youtube_id"] for track in existing
    }

    families = args.family or ["cinematique", "intense", "tropical", "acoustique"]
    tasks: deque[tuple[str, str, str, bool]] = deque()
    if not args.no_channels:
        for family in families:
            for url in CHANNELS.get(family, []):
                handle = url.rstrip("/").rsplit("/", 2)[-2]
                tasks.append((f"« {handle} »", family, url, True))
    if not args.channels_only:
        for family in families:
            for query in QUERIES[family]:
                tasks.append((f"« {query} »", family, search_url(query), False))

    discovered: list[dict] = []
    log(f"{len(existing)} pistes locales existantes · objectif {args.target} · {len(tasks)} sources")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers))
    try:
        while tasks and len(discovered) < args.target:
            batch = [tasks.popleft() for _ in range(min(args.workers, len(tasks)))]
            futures = {
                executor.submit(fetch, url, args.per_query): (label, family, trusted)
                for label, family, url, trusted in batch
            }
            for future in concurrent.futures.as_completed(futures):
                label, family, trusted = futures[future]
                try:
                    results = future.result()
                except Exception as exc:
                    log(f"source échouée {label} : {exc}")
                    continue
                added = 0
                for raw in results:
                    if len(discovered) >= args.target:
                        break
                    track = normalize(
                        raw,
                        family,
                        used_ids,
                        used_yt,
                        args.min_duration,
                        args.max_duration,
                        args.min_views,
                        trusted=trusted,
                    )
                    if track:
                        discovered.append(track)
                        added += 1
                if added:
                    write_local([*existing, *discovered])
                log(f"{family} · +{added} · {len(discovered)}/{args.target} · {label}")
                if len(discovered) >= args.target:
                    for pending in futures:
                        pending.cancel()
                    break
    finally:
        executor.shutdown(wait=True)

    if not discovered:
        print("Aucune piste retenue. Réessayer plus tard ou élargir les critères.", file=sys.stderr)
        return 1

    merged = [*existing, *discovered]
    write_local(merged)
    print(f"Ajouté : {len(discovered)} pistes ({len(merged)} locales au total)")
    print(f"Catalogue local : {LOCAL_CATALOG}")
    if len(discovered) < args.target:
        print(f"Attention : objectif {args.target} non atteint, relancer la commande.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
