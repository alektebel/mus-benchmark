#!/usr/bin/env bash
# Build the static table page for diegoatencia.dev/mus/ from musbench.live.ui.
#
# The page is written for same-origin serving by src/musbench/live/server.py;
# the static build points its two endpoint constants at the AWS backend and at
# the card art already hosted under /mus/cards/ on the site. The leaderboard
# reads /mus/bench-v2-results.json from the site itself.
set -euo pipefail
cd "$(dirname "$0")/.."

BACKEND="${MUS_BACKEND:-https://34.253.36.5.sslip.io}"
OUT="${1:-${PAGES_DIR:-$HOME/Github/alektebel.github.io}/mus/index.html}"

PYTHONPATH=src python3 -c "from musbench.live.ui import INDEX_HTML; import sys; sys.stdout.write(INDEX_HTML)" \
  | sed "s|^const API = '';|const API = '${BACKEND}';|;
         s|^const CARDS = '/cards/';|const CARDS = '/mus/cards/';|" \
  > "$OUT"

grep -q "^const API = '${BACKEND}';" "$OUT" || { echo "API rewrite failed" >&2; exit 1; }
grep -q "^const CARDS = '/mus/cards/';" "$OUT" || { echo "CARDS rewrite failed" >&2; exit 1; }
echo "built $OUT (backend: ${BACKEND})"
