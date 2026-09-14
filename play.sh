#!/usr/bin/env bash
# Play the live table against the NAN models.
#
# Seats are comma-separated: seat0 is you (human), seats 1..3 are the models.
# Team A is seats 0+2, team B is seats 1+3, so one model is your partner and
# two are your rivals.
#
#   ./play.sh                      # human + glm5.3 / deepseek-v4 / qwen3.8
#   SEATS=human,glm5.3-flash,glm5.3-flash,glm5.3-flash ./play.sh
#   PORT=9000 HANDS=6 ./play.sh
#
# Credentials: NAN_API_KEY (and optionally NAN_API_BASE) must be in the
# environment. If they are not, this sources ~/.bashrc once and retries.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -z "${NAN_API_KEY:-}" ]]; then
  # shellcheck disable=SC1090
  source "$HOME/.bashrc" >/dev/null 2>&1 || true
fi
if [[ -z "${NAN_API_KEY:-}" ]]; then
  echo "NAN_API_KEY is not set. Export it, or add it to ~/.bashrc." >&2
  exit 1
fi

PORT="${PORT:-8125}"
HANDS="${HANDS:-12}"
SEATS="${SEATS:-human,glm5.3-flash,deepseek-v4-flash,qwen3.8-flash}"

echo "mus en vivo on port ${PORT} — seats: ${SEATS}"
exec python3 live_server.py --port "${PORT}" --seats "${SEATS}" --hands "${HANDS}"
