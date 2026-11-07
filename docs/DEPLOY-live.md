# Deploying the playable table

The goal: **`alektebel.github.io/mus/play/` where anyone can sit down against
the models.**

GitHub Pages serves static files only, and `src/musbench/live/server.py` is a stateful
Python process (each game holds an engine, four seats, a signal bus and a
kernel thread in memory). So the split is:

```
alektebel.github.io/mus/play/      <- static page (publish/pages/)  ── HTTPS ──┐
                                                                              │
52.31.169.175.sslip.io             <- src/musbench/live/server.py --public   <─────────────┘
   EC2 t4g.nano (eu-west-1) + Caddy TLS (Let's Encrypt via sslip.io)
```

The page is yours and costs nothing to serve. The table is a single
t4g.nano (~$2/month) running one process; Caddy terminates TLS in front of
it. The `*.sslip.io` name resolves to the Elastic IP, which is what lets
Caddy obtain certificates without owning a DNS zone.

---

## 0. Where things live on the instance

| Path | What |
|---|---|
| `/opt/mus/app` | the repo, cloned from `alektebel/mus-benchmark` (runs as user `mus`) |
| `/opt/mus/venv` | python3.11 venv (`requests` is the only dependency) |
| `/etc/mus/mus-bench.env` | secrets/env (`NAN_API_KEY`, budget caps), mode 600 |
| `/etc/caddy/Caddyfile` | TLS site for `https://52.31.169.175.sslip.io` → 127.0.0.1:8080 |
| `mus-table.service` / `caddy.service` | systemd units, both `Restart=always` |

SSH: `ssh -i ~/.ssh/mus-table.pem ec2-user@52.31.169.175` (port 22 restricted
to the owner's current IP — re-authorize it in `mus-table-sg` if your IP
changes). Update the app with `sudo -u mus git -C /opt/mus/app pull` +
`sudo systemctl restart mus-table`.

---

## 1. What `--public` changes

`src/musbench/live/server.py` was written for one person on one laptop. `--public` adds the
three things that were missing, via `src/musbench/live/public.py`:

| Problem on the open internet | What `--public` does |
|---|---|
| One global game — any visitor pressing "Nueva partida" stopped everyone else's | `SessionRegistry`: one `LiveTable` per browser |
| Every visitor turn spends your API credits, with no ceiling | `Budget`: daily call cap, persisted across restarts |
| Abandoned games keep engine threads alive forever | idle sessions reaped after `MUS_SESSION_IDLE_TTL` |

When the budget runs out the table **does not go down** — new games are dealt
with offline heuristic seats and the UI says so. Same if `NAN_API_KEY` is
missing entirely.

Local single-player mode is untouched: `./play.sh` behaves exactly as before.

## 2. The backend on AWS

Provisioned once, on 2026-09-14, with the AWS CLI:

```bash
# security group: 80+443 open (ACME + TLS), 22 restricted to the owner IP
aws ec2 create-security-group --group-name mus-table-sg ...
aws ec2 authorize-security-group-ingress --group-id $SG --ip-permissions [...]

# dedicated keypair + Elastic IP (stable name for sslip.io + Caddy)
aws ec2 create-key-pair --key-name mus-table > ~/.ssh/mus-table.pem
aws ec2 allocate-address --domain vpc          # eipalloc-031c699af163e04b1

# t4g.nano (~$2/mo), AL2023 arm64, user-data installs caddy + python3.11,
# clones the repo and enables caddy.service + mus-table.service
aws ec2 run-instances --image-id ami-0c8fa3e43097681d9 --instance-type t4g.nano \
  --key-name mus-table --security-group-ids $SG \
  --user-data file:///tmp/opencode/mus_userboot.sh ...
aws ec2 associate-address --instance-id i-08312016e954185e7 \
  --allocation-id eipalloc-031c699af163e04b1
```

Secrets go on the box by ssh, never through the console or user-data
(instance metadata is readable by the process):

```bash
printf 'NAN_API_KEY=%s\n' "$KEY" | \
  ssh -i ~/.ssh/mus-table.pem ec2-user@52.31.169.175 \
  'sudo tee /etc/mus/mus-bench.env > /dev/null && sudo systemctl restart mus-table'
```

Check it:

```bash
curl https://52.31.169.175.sslip.io/healthz     # -> ok
curl https://52.31.169.175.sslip.io/api/status  # -> budget + session counts
```

**One machine only.** Sessions live in process memory, so a second machine
would serve half the requests a table the visitor does not have. Do not scale
this horizontally without moving session state out of the process. If the
nano runs out of memory, stop the instance and switch to t4g.micro — the
Elastic IP and sslip.io name survive the type change.

## 3. Publish the page

The table lives at **`diegoatencia.dev/mus/`** and opens straight onto the
mesa; Reglamento and Clasificación are views of the same page (`#reglamento`,
`#clasificacion`). Build it into the Pages checkout:

```bash
publish/build_static_play.sh                       # -> ~/Github/alektebel.github.io/mus/index.html
MUS_BACKEND=https://<host>.sslip.io publish/build_static_play.sh /path/to/out.html
```

The page source (`src/musbench/live/ui.py`) declares its endpoints as two
constants, `API` (empty = same origin) and `CARDS` (`/cards/`); the build
rewrites them to the backend origin and to `/mus/cards/`. The model
leaderboard reads `/mus/bench-v2-results.json` from the site.

Keep the page origin on the backend's CORS allowlist (`--allow-origin
https://diegoatencia.dev`, plus `https://alektebel.github.io` for the
github.io alias). CORS is an allowlist — an origin that is not listed gets no
`Access-Control-Allow-Origin` header at all, and the status reads
"la mesa no responde".

`MUS_HAND_PAUSE` (default 4.5 s) holds the next deal while a human is seated,
so the end-of-hand reveal is visible on the table.

## 4. Spend controls

Every one of these is an environment variable, so you can retune without a
redeploy (`fly secrets set NAME=value`):

| Variable | Default | What it bounds |
|---|---:|---|
| `MUS_DAILY_CALL_BUDGET` | 4000 | model calls per UTC day; after this, offline seats |
| `MUS_SESSION_CALL_CAP` | 240 | calls in a single game |
| `MUS_PUBLIC_HANDS` | 4 | legacy cap; public games now default to ONE vaca (hard cap 40 hands), so the real cost lever is `MUS_DAILY_CALL_BUDGET` |
| `MUS_TRACE_TABLE` | `mus-traces` | DynamoDB table for game traces (gzip JSON, written via the instance role); empty string disables |
| `MUS_TRACE_TTL_DAYS` | 120 | trace expiry (DynamoDB TTL on the `tte` attribute) |
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
python -m musbench.live.server --port 8132 --seats human,heuristic,heuristic,heuristic \
  --public --allow-origin http://127.0.0.1:8141

python -m unittest tests.test_live_public -v
```
