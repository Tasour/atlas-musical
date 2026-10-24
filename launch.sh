#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://127.0.0.1:8765/"
LOG="$ROOT/work/server.log"

mkdir -p "$ROOT/work"

server_ready() {
  curl -fsS --max-time 2 "${URL}api/health" 2>/dev/null | grep -q "Atlas Musical"
}

if ! server_ready; then
  cd "$ROOT"
  nohup python3 server.py >>"$LOG" 2>&1 &
  echo $! >"$ROOT/work/server.pid"
  ready=0
  for _ in $(seq 1 60); do
    if server_ready; then
      ready=1
      break
    fi
    sleep 0.5
  done
  if [[ $ready -ne 1 ]]; then
    message="Le serveur Atlas Musical n'a pas démarré. Voir $LOG"
    if command -v notify-send >/dev/null 2>&1; then
      notify-send "Atlas Musical" "$message"
    else
      printf '%s\n' "$message" >&2
    fi
    exit 1
  fi
fi

if command -v omarchy-launch-webapp >/dev/null 2>&1; then
  exec omarchy-launch-webapp "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  exec xdg-open "$URL"
else
  printf 'Ouvrir %s dans un navigateur.\n' "$URL"
fi
