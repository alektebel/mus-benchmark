# How the mus_bench score works

## The number

**Score = piedras per hand a model wins against an average opponent of the
rated field.** `+9.5` means that over a hand of mus, with the same deals and
both seatings, the model's team outscores a typical rival team by 9.5 piedras.
0 is the field average (or the `anchor` model, if one is set).

### Why piedras per hand, not vacas or wins

A vaca is a 40-point threshold that also zeroes both counters, so a team on
39 loses everything. An 8-hand match yields 0–5 vacas, which is a very noisy
count. Piedras per hand keeps every point the hands actually produced
(README, "Paired deals").

### The fit

Each match gives one observation, the margin per hand of team A (seats 0+2)
over team B (seats 1+3):

```
margin_per_hand(A vs B) = r_A - r_B + seat_bias
```

This is a Massey rating: weighted least squares (weight = hands), with one
shared `seat_bias` term, because seats 0+2 have a measured positional edge
(README, "Known seat bias"). Every pairing is played on every seed **in both
seatings**, so the two orientations see identical cards. Deal luck and seat
bias cancel inside each pair, and the rating mostly measures play.

Unlike a raw "average margin", the fit corrects for strength of schedule.
Beating the weakest model counts for less than beating the strongest.

### The interval and P(#1)

A block bootstrap (`bootstrap` resamples, seeded so CI output is
reproducible) resamples **(pairing, seed) blocks**, so a mirror pair is never
split. Each resample is refitted:

- **95% CI** is the 2.5/97.5 percentile of the resampled scores.
- **P(#1)** is the share of resamples in which the model has the top score.
- The README states whether #1's interval clears #2's. If it doesn't, the
  order is provisional.

### What is excluded

- Matches from a different `protocol` (see `benchmark/models.toml`). Bump the
  protocol whenever the engine, prompts or schedule change, and re-run.
- Matches with a status other than `done` (timeouts, aborts, partial runs).
  Matches with LLM seats are also excluded when fewer than 50 LLM calls were
  made or more than 15% of decisions fell back to a default action.
- Models that are not on the roster. To remove a model from the leaderboard,
  delete its `[[model]]` block. Its ledger rows stay as history.

The ⚠️ flag marks a model rated against a single opponent. Its score is
`opponent's score + head-to-head margin`, so it inherits that opponent's
uncertainty. Fix this by running its full schedule.

## Adding a model

```bash
# 1. register it (one TOML block is appended to benchmark/models.toml)
python -m musbench.leaderboard add claude-sonnet-5-5 \
    --spec anthropic:claude-sonnet-5-5 --name "Claude Sonnet 5.5"

# 2. see what it will play: every roster model x every seed x both seatings
python -m musbench.leaderboard schedule claude-sonnet-5-5

# 3. play it (API spend; resumable: only missing matches are played)
python -m musbench.leaderboard run claude-sonnet-5-5 --workers 2

# 4. refresh README block, docs/leaderboard.svg, benchmark/leaderboard.json
python -m musbench.leaderboard score
git add benchmark/ docs/leaderboard.svg README.md && git commit
```

`--spec` is anything the harness accepts:

| spec | seat |
|---|---|
| `glm5.3-flash` | default provider (`DEFAULT_PROVIDER`, `nan`) |
| `nan:…` / `nvidia:…` / `openrouter:…` | OpenAI-compatible chat completions |
| `anthropic:claude-…` | Anthropic Messages API (`ANTHROPIC_API_KEY`) |
| `typesafe:jev-latest` | TypeSafe Jev |
| `heuristic`, `random`, `eps:E:B` | free offline baselines |

For a provider that isn't listed, add one line to `PROVIDERS` in
`src/musbench/agents/core.py` if it speaks OpenAI chat completions.
Otherwise add a seat class (see `anthropic_seat.py`).

Cost: a roster of *N* models means 2 × N × |seeds| new matches per model.
At 8 hands that's about 170–300 LLM calls per match.

`python -m musbench.leaderboard list` shows the roster, how many rated
matches each model has, and how many of its scheduled matches are missing.

## Files

| file | role |
|---|---|
| `benchmark/models.toml` | roster + protocol, hands, seeds, anchor |
| `benchmark/matches.jsonl` | append-only ledger, one compact row per match; the source of truth |
| `benchmark/leaderboard.json` | last computed leaderboard (machine-readable) |
| `docs/leaderboard.svg` | the animated chart at the top of the README |
| `src/musbench/leaderboard/` | `rating.py` (fit + bootstrap), `render.py`, `cli.py` |

## Provenance of the current data

The 55 `v2` rows were imported from `bench-v2-results.json` (generated
2026-09-19, published at `/mus/bench-v2-results.json`). That file records
"explicit amounts, corrido sin señas hand 1, CoT · 8 hands · seeds 0-3 · both
seatings". The script that produced it is **not in this repository**, and
its per-match fallback counts are not split by team. New rows written by
`run` carry the git commit, the specs, and per-team calls and fallbacks.
