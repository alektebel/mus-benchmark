# Running mus_bench

## Validate locally

```bash
python -m unittest discover -s tests -v
python run_match_strict.py --models heuristic,random,heuristic,random --hands 100 --seed 7
```

The test suite covers strict and legacy rules, hidden-hand access, discard
atomicity, communication, retry behavior and runner failures using offline mocks.
It does not validate live model availability or external rulebook conformance.

## Configure LLM seats

The strict harness supports `nan` and `nvidia`. Set `NAN_API_KEY` or `NVIDIA_KEY`
for the seats you use. `NAN_API_BASE` overrides the nan endpoint.
`DEFAULT_PROVIDER` defaults to `nan`; explicit `provider:model` specs override it.
OpenRouter is not configured in the current strict harness.

| Setting | Default | Purpose |
|---|---|---|
| `REASONING_MODE` | `minimal` | `omit` leaves the provider field out; other values are sent as `reasoning_effort`. Keep low so verbose reasoning does not truncate the answer |
| `THINK_BUDGET` | 600 | Per-thought token ceiling sent as `max_tokens` and told to the model; escalation bound is `3x` |
| `ALLOW_SEÑA_BLUFFS` | `1` | Broadcast gestures even when they do not match the sender's hand (`1`/`0`). Off = truthful signal channel |
| `MAX_RESP` / `MAX_RESP_CAP` | `THINK_BUDGET` / `THINK_BUDGET*3` | Legacy response budget and truncation escalation ceiling |
| `NAN_TIMEOUT` | 180 seconds | Per-request timeout for either provider |
| `RESP_RETRIES` | 3 | Malformed/truncated response attempts |
| `CALL_ATTEMPTS` | 6 | HTTP/transport attempts |
| `MATCH_TIMEOUT` | 3600 seconds | Match deadline checked between turns, API calls and backoffs |
| `MAX_TURNS_PER_HAND` | 200 | Engine loop guard |
| `MAX_FALLBACK_RATE` | 0.15 | Abort threshold among LLM decision turns |
| `FALLBACK_MIN_TURNS` | 10 | Minimum LLM turns before threshold applies |
| `PROGRESS_FILE` | `progress.json` | Batch progress path |

The request timeout and retry sleeps are limited by the remaining match deadline.
The HTTP library's timeout is a connect/read timeout, so this is not an
interruptible wall-clock process kill. Choose provider-supported reasoning values;
permanent client errors abort rather than retrying an incompatible payload.

```bash
python run_match_strict.py --models "$MODEL,heuristic,$MODEL,heuristic" --hands 12 --seed 7
python run_match_strict.py --teams "$MODEL_A" "$MODEL_B" --hands 12 --seed 7
python run_llm_vs_baseline.py --models "$MODEL" --hands 12 --seeds 0,1,2 --workers 1 --out batch.json
python run_benchmark_strict.py --models "$MODEL,heuristic,$MODEL,heuristic" --hands 12 --seeds 0,1,2 --workers 1
python dashboard.py --port 8000 --file progress.json
```

`--teams TEAM_A TEAM_B` is a convenience for the 4-agent conflict-of-interest
match: it expands to the seat matrix `[TEAM_A, TEAM_B, TEAM_A, TEAM_B]`, i.e.
the first model occupies both Team A seats (0+2) and the second both Team B
seats (1+3). Partners still cannot see each other's cards, so signalling is the
only cooperation channel.

Batch jobs preserve errors and exit nonzero if any match fails. Give separate
concurrent batch processes different `PROGRESS_FILE` values. The dashboard serves
on all interfaces and can display either strict batch output shape.

## Diagnostic entry points

`probe_reasoning.py`, `single_test.py`, `error_hunt.py` and `complete_game.py`
are explicit live API diagnostics. Importing their modules does not start runs.
Run them deliberately with credentials configured; their default model names
are examples from earlier experiments and may need adjustment.

## Interpretation

Use seeded repetitions and both team orientations before interpreting a vaca
share. Strict vacas are games to 40 points, not the legacy per-lance units.
Existing JSON/log results predate the review fixes and remain historical artifacts.
The perception budget currently records expenditure but permits listening on
credit after zero. A hard attention-budget experiment would require a separately
specified protocol change. See [README.md](README.md).

## Live table (play vs LLMs in the browser)

```bash
python live_server.py --port 8123 \
    --seats human,glm5.3-flash,deepseek-v4-flash,heuristic --hands 12
```

Open the printed seat URLs (one per human seat, token-authenticated); a
tokenless visit is a spectator. The sidebar has a Bench tab that aggregates
everything under `--results-dir` (default `results/`): tournament summaries
(`run_tournament.py --out results/tournament`) and strict batch outputs
(`run_llm_vs_baseline.py --out ...`). Poll it during long runs — the tab
refreshes every 20 s and shows the vacas leaderboard plus per-match rows.
`GET /api/results` exposes the same aggregation as JSON.

## Rank equivalence fix (2026-09-10)

The engine previously treated `as` and `dos` as the same rank ("8 reyes y 8
ases"), which (a) counted `as+dos` as pares and (b) misplaced `tres/rey` at
the bottom of the Chica ordering. The engine now uses Fournier-aligned maps:
the only rank equivalence is **tres = rey**; pares require two equal cards
within that scheme; Grande orders `dos > as`; Chica orders `as < dos <
tres/rey < cuatro ... < caballo`. The prompt builder's rules note was updated
to match. Any results produced before this fix are invalid and were deleted.
