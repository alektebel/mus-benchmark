# Deploying the playable table

The goal: **`alektebel.github.io/mus/play/` where anyone can sit down against
the models.**

GitHub Pages serves static files only, and `live_server.py` is a stateful
Python process (each game holds an engine, four seats, a signal bus and a
kernel thread in memory). So the split is:

```
alektebel.github.io/mus/play/      <- static page (publish/pages/)  ── iframe ──┐
                                                                                │
mus-table.fly.dev                  <- live_server.py --public  <─────────────────┘
```

The page is yours and costs nothing to serve. The table wakes when somebody
presses **Jugar**, and stops when the last player leaves.

---

## 1. What `--public` changes

`live_server.py` was written for one person on one laptop. `--public` adds the
three things that were missing, via `live_public.py`:

| Problem on the open internet | What `--public` does |
|---|---|
| One global game — any visitor pressing "Nueva partida" stopped everyone else's | `SessionRegistry`: one `LiveTable` per browser |
| Every visitor turn spends your API credits, with no ceiling | `Budget`: daily call cap, persisted across restarts |
| Abandoned games keep engine threads alive forever | idle sessions reaped after `MUS_SESSION_IDLE_TTL` |

When the budget runs out the table **does not go down** — new games are dealt
with offline heuristic seats and the UI says so. Same if `NAN_API_KEY` is
missing entirely.

Local single-player mode is untouched: `./play.sh` behaves exactly as before.

## 2. Deploy the backend

```bash
# once
fly launch --no-deploy            # accept the existing fly.toml
fly secrets set NAN_API_KEY=...   # never bake this into the image

# every time
fly deploy
```

Check it:

```bash
curl https://mus-table.fly.dev/healthz     # -> ok
curl https://mus-table.fly.dev/api/status  # -> budget + session counts
```

`fly.toml` sets `auto_stop_machines = "stop"` and `min_machines_running = 0`,
so an idle table costs nothing. An active player holds an SSE connection on
`/events`, which counts as a live request and keeps the machine awake for as
long as they are playing. The first visitor after an idle period waits a few
seconds for the boot — the page shows "despertando la mesa…" during it.

**One machine only.** Sessions live in process memory, so a second machine
would serve half the requests a table the visitor does not have. Do not scale
this horizontally without moving session state out of the process.

## 3. Publish the page

```bash
mkdir -p /path/to/alektebel.github.io/mus/play
cp publish/pages/index.html /path/to/alektebel.github.io/mus/play/
```

If the backend is not at `mus-table.fly.dev`, change the one line at the top of
the page's script:

```js
const API = "https://mus-table.fly.dev";
```

and set the matching origin on the backend:

```bash
fly secrets set MUS_ALLOW_ORIGINS=https://alektebel.github.io
```

CORS is an allowlist — an origin that is not listed gets no
`Access-Control-Allow-Origin` header at all, so keep those two in sync or the
status badge will read "la mesa no responde".

## 4. Spend controls

Every one of these is an environment variable, so you can retune without a
redeploy (`fly secrets set NAME=value`):

| Variable | Default | What it bounds |
|---|---:|---|
| `MUS_DAILY_CALL_BUDGET` | 4000 | model calls per UTC day; after this, offline seats |
| `MUS_SESSION_CALL_CAP` | 240 | calls in a single game |
| `MUS_PUBLIC_HANDS` | 4 | hands per game — the main lever on cost per visitor |
| `MUS_MAX_SESSIONS` | 12 | concurrent tables |
| `MUS_MAX_LLM_SESSIONS` | 4 | of those, tables facing real models |
| `MUS_GAMES_PER_IP_HOUR` | 6 | games one address may start per hour |
| `MUS_SESSION_IDLE_TTL` | 900 | seconds before an abandoned game is reaped |

The budget is stored at `MUS_BUDGET_STATE` (`/tmp/mus-budget.json`) and re-read
on boot, so a crash loop cannot hand out a fresh day's budget on every restart.
It is not on a volume: losing the file costs at most one day's accounting.

**Start conservative.** A four-hand game against three models runs roughly
60–90 calls. At the default 4000/day that is ~45–65 games before the table
falls back to offline seats. Watch the first day and adjust:

```bash
fly logs
curl https://mus-table.fly.dev/api/status
```

## 5. Things to know before you open it up

- **Cost is real and visitor-driven.** The ceilings above are what stands
  between a link on social media and a surprising invoice. The per-IP limit is
  trivially bypassed with a VPN — it stops accidents, not determined abuse.
  `MUS_DAILY_CALL_BUDGET` is the only hard ceiling.
- **Sessions are in-memory.** A deploy or a machine stop ends games in
  progress. Fine for four-hand games; worth knowing.
- **`X-Forwarded-For` is trusted** for rate-limiting only, because Fly sets it.
  Never use it for anything security-bearing.
- **The API key lives only in Fly secrets.** It is not in the image, not in
  `fly.toml`, and not in the repo.

## 6. Local testing

```bash
# public mode locally, offline seats, no credits spent
python live_server.py --port 8132 --seats human,heuristic,heuristic,heuristic \
  --public --allow-origin http://127.0.0.1:8141

python -m unittest tests.test_live_public -v
```
