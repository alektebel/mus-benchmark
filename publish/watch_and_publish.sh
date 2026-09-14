#!/usr/bin/env bash
# Wait for the running tournament to finish, regenerate the benchmark page,
# push it to alektebel.github.io, and send a Telegram notification.
#
# Chat ids are read from (first found wins):
#   $HOME/.config/mus-bench/telegram_chat_ids   (one numeric id per line)
#   $TELEGRAM_CHAT_ID
# The bot token comes from $TELEGRAM_KEY. If no chat id is configured the page
# is still published and the notification is skipped.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
PAGES_DIR="${PAGES_DIR:-/tmp/opencode/pages_publish}"
RESULTS_DIRS=(results/tournament_replication results/tournament_mirror)

echo "[watch] $(date -u +%FT%TZ) waiting for run_tournament.py to finish"
while pgrep -f "run_tournament.py" >/dev/null; do sleep 30; done
echo "[watch] tournament finished at $(date -u +%FT%TZ)"

# --- refresh pages clone ---
rm -rf "$PAGES_DIR"
git clone --depth 1 https://github.com/alektebel/alektebel.github.io "$PAGES_DIR" >/dev/null 2>&1
cd "$PAGES_DIR"
git config user.name "alektebel"
git config user.email "alektebel@users.noreply.github.com"

# --- render ---
python3 "$REPO/publish/render_results.py" \
  $(for d in "${RESULTS_DIRS[@]}"; do echo -n " --results-dir $REPO/$d"; done) \
  --out "$PAGES_DIR/mus/benchmark.html"

# --- commit + push ---
if git status --porcelain | grep -q .; then
  git add mus/benchmark.html
  git commit -m "mus: update LLM benchmark results ($(date -u +%F))" >/dev/null
  git push origin main >/dev/null 2>&1 && echo "[watch] pushed benchmark.html" || echo "[watch] PUSH FAILED"
else
  echo "[watch] no page changes to push"
fi

# --- summarize for the notification ---
SUMMARY=$(python3 - "$REPO" <<'PY'
import json, sys
from pathlib import Path
repo = Path(sys.argv[1])
rows = []
for d in ("results/tournament_replication", "results/tournament_mirror"):
    sp = repo / d / "summary.json"
    if sp.exists():
        rows += json.loads(sp.read_text()).get("entries", [])
done = [e for e in rows if e.get("status") in ("done", "finished")]
def line(e):
    m = e.get("metrics") or {}
    return (f"{e.get('team_a')} vs {e.get('team_b')} (seed {e.get('seed')}): "
            f"vacas {m.get('vacas_a')}-{m.get('vacas_b')}, hands {m.get('hand_wins')}, "
            f"señas {m.get('senas_published')}/{m.get('senas_caught')}, "
            f"fb {m.get('fallbacks')}, calls {m.get('llm_calls')}")
print(f"mus_bench finished: {len(done)}/{len(rows)} matches publishable")
for e in done:
    print("  " + line(e))
print("https://alektebel.github.io/mus/benchmark.html")
PY
)
echo "$SUMMARY"

# --- telegram ---
CHAT_IDS=()
if [ -f "$HOME/.config/mus-bench/telegram_chat_ids" ]; then
  while read -r id; do [ -n "$id" ] && CHAT_IDS+=("$id"); done < "$HOME/.config/mus-bench/telegram_chat_ids"
fi
[ -n "${TELEGRAM_CHAT_ID:-}" ] && CHAT_IDS+=("$TELEGRAM_CHAT_ID")

if [ -z "${TELEGRAM_KEY:-}" ]; then
  echo "[watch] TELEGRAM_KEY not set; skipping notification"
elif [ "${#CHAT_IDS[@]}" -eq 0 ]; then
  echo "[watch] no chat ids configured; skipping notification"
else
  for cid in "${CHAT_IDS[@]}"; do
    python3 - "$cid" "$SUMMARY" <<'PY'
import os, sys, json, urllib.parse, urllib.request
cid, text = sys.argv[1], sys.argv[2]
tok = os.environ["TELEGRAM_KEY"]
data = urllib.parse.urlencode({"chat_id": cid, "text": text,
                               "disable_web_page_preview": "false"}).encode()
req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data)
try:
    urllib.request.urlopen(req, timeout=30)
    print(f"[watch] telegram sent to {cid}")
except Exception as e:
    print(f"[watch] telegram failed for {cid}: {e}")
PY
  done
fi
echo "[watch] done at $(date -u +%FT%TZ)"
