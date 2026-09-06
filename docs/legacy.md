# Legacy pipeline reference

Historical description and results for `engine.py`, not the strict engine.
The legacy harness collects phase decisions concurrently and resolves them in seat
order; its ordago is automatic rather than an explicit accept/decline round.
Legacy points are as=11, dos=2, tres=10, figures=4, other ranks=0.
Observations arrive in later prompts, so a final-phase read cannot change play.

# mus_bench — LLM cooperation in a 2v2 Spanish card game

A benchmark for evaluating how well large language models (LLMs) **cooperate
under partial observability** in **mus**, a Spanish 2v2 trick-taking card game.
Each benchmark is a dyad of two LLMs playing as partners against a fixed
reference-model dyad. The measurement is the fraction of *vacas* (the per-jugada
scoring units) the benchmark pair wins — a 2v2 "win-rate" matrix over model
pairs.

This is *not* a game-AI-strength benchmark in the sense of "can an LLM master
mus." It isolates a narrower, more tractable question: **when two LLMs must
coordinate without seeing each other's cards, and their signalling is mediated by
a limited "attention budget," which pairs cooperate best?**

## The game model

Spanish 40-card deck (paces: oros, copas, espadas, bastos; ranks:
as < dos < tres < cuatro < cinco < seis < siete < sota < caballo < rey).

Four seats: Team A = seats {0, 2}, Team B = seats {1, 3} (partners sit opposite).
Each player holds 4 cards. A hand proceeds through phases:

1. **MUS_REQUEST** — in seat order each player says `mus` (wants to replace
   cards), `no`, or (first seat only) `ordago` (bet the whole hand).
2. **MUS_DRAW** — players who said `mus` discard 1–4 cards and redraw.
3. **JUGADAS** — Grande, Chica, Pares, Juego are compared between teams.

### Scoring (vacas)
Each jugada won by a team awards 1 vaca (≤ 4 per hand). An accepted *ordago*
awards all 4 vacas (tie broken by Grande). A drawn jugada awards 0 to both. The
team with more total vacas across a match wins.

### Rules variant
The engine implements a documented subset/variant of mus rules. **Important:
every jugada is evaluated per player's 4-card hand, and a team's value is the best
of its two players** (the standard 2v2 interpretation), *not* a merged 8-card
hand. Pares follows Duples > Medias (three-of-a-kind) > Pares (one pair). Juego
follows the valid total hierarchy 31<32<…<37<40, with totals above 40 counted as
40. See `engine.py` for exact rules. If your target is a specific regional rule
set, verify these against the Federación Española de Mus reglamento before using
the numbers.

## The coordination / attention channel (the novel part)

Real mus partners use encoded signals (gestures, expressions) that the opponent
can sometimes detect. The benchmark models this with an explicit **partial
observability channel** and a **per-hand attention budget** (`channels.py`):

- Every agent action optionally emits a `signal` string to its partner.
- Partner signals are **hidden by default**. Spending attention credits
  (`observe: "partner"`, cost 2) reveals them.
- Spending credits on `observe: "opp"` (cost 1) only reports a *count* of
  opponent signals, not their content.
- Budgets are per-hand, so attention spent reading your own partner's signals is
  unavailable to glance at opponents — a genuine trade-off.

This makes the benchmark a test of *strategic information economy*: when to pay to
decode your partner, when to pay to detect opponents, and how much to (or not to)
signal. It also makes the benchmark non-trivial even for perfectly-rational
players, since the attention budget is finite.

## Files

| File            | Purpose                                                              |
|-----------------|----------------------------------------------------------------------|
| `deck.py`       | Spanish deck, card ordering, point values.                            |
| `engine.py`     | Deterministic mus engine (deal, jugada comparison, vacas, ordago).    |
| `channels.py`   | Attention budget + sticky signal bus (partial observability).         |
| `agent.py`      | `LLMAgent`: OpenAI-compatible wrapper that returns strict JSON actions.|
| `run_match.py`  | Harness: orchestrates hands, agent turns, attention, vacas.           |
| `benchmark.py`  | Runs the full pairwise matrix vs a reference dyad → `results.json`.   |
| `report.py`     | Renders the vacas win-rate matrix + ranked cooperation pairs.         |
| `baseline.py`   | Non-LLM floors: `RandomAgent`, `HeuristicAgent` (no API).             |
| `run_baseline.py`| Runs baseline self-play to establish the skill floor.                |

## Reproduce the benchmark

Env:
```
export NAN_API_BASE=https://api.nan.builders/v1
export NAN_API_KEY=...
```

Baseline floor (no API, fast):
```
python run_baseline.py --hands 12 --reps 20
```

Full LLM matrix (costs API credits; single decision ≈ seconds to tens of seconds):
```
python benchmark.py --hands 12 --reps 3 --out results.json
python report.py results.json
```

Config via env: `MATCH_HANDS`, `REPS_PER_PAIR`, `NAN_TIMEOUT`.

## Current results

Baseline floor (12 hands × 20 matches, symmetric win-rate):

| Matchup                  | symmetric win-rate |
|--------------------------|--------------------|
| random vs random         | 0.49               |
| heuristic vs heuristic   | 0.52               |
| heuristic vs random      | 0.55–0.57          |

Key takeaway: a careful **rule-based** heuristic only edges out random by roughly
**0.05** on the vacas numerator. The vacas signal is noisy, so *detecting*
meaningful differences between *LLMs* requires many hands and repetitions, and
the LLM-vs-random margin must be interpreted against this small floor.

## Caveats / open issues

- **Statistical power**: 12 hands/match is small; use many reps and report
  confidence intervals. Consider a self-play Elo ranking instead of a single
  fixed reference opponent.
- **Model versioning**: results depend on proprietary model snapshots
  (`deepseek-v4-flash`, etc.). Record model ID + access date and note that
  findings may not be reproducible later.
- **Rules subset**: see variant note above — the engine is a documented
  simplification, not a certified rule implementation.
- **No human baseline**: a human-expert ceiling is absent. Consider adding one.
- **Attention budget realism**: the credits/costs are chosen constants; validate
  sensitivity to different budgets.

## License

(TODO: add a license; see paper for attribution.)
