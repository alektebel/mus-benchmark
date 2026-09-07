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
| `REASONING_MODE` | `off` | `omit` leaves the provider field out; other values are sent as `reasoning_effort` |
| `MAX_RESP` / `MAX_RESP_CAP` | 1600 / 6144 | Response budget and truncation escalation ceiling |
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
