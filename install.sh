#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SVG="$ROOT/app/assets/icon.svg"
PNG="$ROOT/app/assets/icon-256.png"

chmod +x "$ROOT/launch.sh"

if ! command -v omarchy-webapp-install >/dev/null 2>&1; then
  echo "omarchy-webapp-install est requis (intégration Omarchy uniquement)." >&2
  exit 1
fi

if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 256 -h 256 "$SVG" -o "$PNG"
elif command -v magick >/dev/null 2>&1; then
  magick -background none "$SVG" -resize 256x256 "$PNG"
elif command -v convert >/dev/null 2>&1; then
  convert -background none "$SVG" -resize 256x256 "$PNG"
else
  echo "rsvg-convert ou ImageMagick requis pour créer l'icône." >&2
  exit 1
fi

omarchy-webapp-install \
  "Atlas Musical" \
  "http://127.0.0.1:8765/" \
  "$PNG" \
  "$ROOT/launch.sh"

printf 'Lanceur installé. Chercher « Atlas Musical » dans le lanceur Omarchy (Super + Space).\n'
