#!/usr/bin/env bash
# Build the static play page for alektebel.github.io from live_ui.INDEX_HTML.
# The page is written for same-origin serving by live_server.py; the static
# build rewrites API/SSE calls to the AWS backend and card art to the copy
# already hosted at /mus/cards/ on the site.
set -euo pipefail
cd "$(dirname "$0")/.."

BACKEND="${MUS_BACKEND:-https://52.31.169.175.sslip.io}"
OUT="${1:-${PAGES_DIR:-/home/diego/Documents/Development/alektebel.github.io}/mus/play/index.html}"

python3 -c "from live_ui import INDEX_HTML; import sys; sys.stdout.write(INDEX_HTML)" \
  | sed "s|fetch('/api/|fetch('${BACKEND}/api/|g;
         s|new EventSource('/events|new EventSource('${BACKEND}/events|g;
         s|fetch('/snapshot|fetch('${BACKEND}/snapshot|g;
         s|'/cards/card_|'/mus/cards/card_|g;
         s|src=\"/cards/card_back.svg\"|src=\"/mus/cards/card_back.svg\"|g" \
  > "$OUT"

echo "built $OUT (backend: ${BACKEND})"
