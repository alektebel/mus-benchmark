#!/usr/bin/env bash
# Build the leaderboard site into the personal site repo at mus/benchmark/.
# Builds only: review, then commit and push the site repo yourself.
#
#   publish/deploy_benchmark_page.sh [SITE_REPO]      # default ~/Github/alektebel.github.io
set -euo pipefail
cd "$(dirname "$0")/.."
SITE="${1:-$HOME/Github/alektebel.github.io}"
DEST="$SITE/mus/benchmark"
[ -d "$SITE/.git" ] || { echo "not a git repo: $SITE" >&2; exit 1; }
PYTHONPATH=src python3 publish/build_replay_viewer.py --out "$DEST" --standalone
# the old redirect page would shadow the new folder at /mus/benchmark
if [ -f "$SITE/mus/benchmark.html" ]; then
  git -C "$SITE" rm -q "mus/benchmark.html" 2>/dev/null || rm -f "$SITE/mus/benchmark.html"
  echo "removed the old mus/benchmark.html redirect"
fi
echo
echo "built $DEST -> https://diegoatencia.dev/mus/benchmark/"
echo "review:  (cd $DEST && python3 -m http.server 8899)"
echo "publish: git -C $SITE add mus/benchmark && git -C $SITE commit -m 'mus: benchmark leaderboard' && git -C $SITE push"
