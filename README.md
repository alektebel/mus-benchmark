# mus_bench

A Python benchmark for cooperation between two-player LLM teams in mus.
Team A occupies seats 0 and 2; Team B occupies seats 1 and 3.

## Current pipeline

`mus_engine.py` is the strict, turn-gated engine. `run_match_strict.py` runs
LLM or offline policy seats against it. A **vaca means reaching 40 points**;
both point counters then reset. Grande, Chica, Pares and Juego have separate
betting rounds. The engine validates declarations, discards and turn order.
Its locally documented rules variant is described in the engine module;
this project does not certify conformance to an external rulebook.

The older simplified scoring protocol (`engine.py`, `run_match.py`,
`run_match_gc.py`) has been removed; it is documented historically in
[docs/legacy.md](docs/legacy.md), and its results must not be pooled with
strict results.

## Results and traces

[docs/results-seed6-live.md](docs/results-seed6-live.md) reports the seed-6 live kernel
match (GLM-5.3-Flash vs DeepSeek-V4-Flash) and pools every match in this repo. Read its
header first: that run **timed out at hand 16 of 40**, and no match count here is large
enough to rank models.

`publish/web/` is a static trace viewer that replays a finished match decision by
decision -- the prompt each seat received, its reply, its private reasoning, and the
senas it caught. See [publish/web/README.md](publish/web/README.md) to deploy it.

```bash
python publish/export_trace.py results/live_run --out publish/web/traces/seed6.json --slug seed6
cd publish/web && python -m http.server 8899
```

## Offline validation

Python 3.10+ and `requests` are required. No API key is needed for these commands:

```bash
python -m unittest discover -s tests -v
python run_match_strict.py --models heuristic,random,heuristic,random --hands 100 --seed 7
PROGRESS_FILE=/tmp/mus-progress.json python run_benchmark_strict.py \
  --models heuristic,random,heuristic,random --hands 100 --seeds 0,1,2 \
  --workers 2 --out /tmp/mus-results.json
```

The CLI seeds both the deck and random policies. Python callers supply the
engine RNG explicitly: `MusEngine(rng=Random(seed))`; the harness's `seed`
argument seeds the policies and preserves the supplied engine RNG.

## LLM runs

Supported strict providers are `nan` (`NAN_API_KEY`, optional `NAN_API_BASE`)
and `nvidia` (`NVIDIA_KEY`). A model spec is a plain model name for the default
provider, `provider:model`, or `heuristic`/`random` for an offline seat.
Use a model available through your configured provider. LLM runs consume API
credits; the regression tests use mocks and do not make network calls.

```bash
python run_match_strict.py --models "$MODEL,heuristic,$MODEL,heuristic" --hands 12 --seed 7
python run_llm_vs_baseline.py --models "$MODEL" --hands 12 --seeds 0,1,2 --workers 1
python dashboard.py --file progress.json --port 8000
```

See [RUN.md](RUN.md) for configuration and diagnostic commands.

## Experimental kernel harness (real-time señas)

`run_match_kernel.py` runs the same turn-gated engine through a
**virtual-time kernel** (`virtual_kernel.py`) that models how señas actually
work in mus: a player gestures *while the partner is deliberating*, not on
their own turn, and a gesture nobody catches before it fades is simply
missed.

  * Decisions stay **sequential** — one API call per decision, same retry and
    fallback discipline as the strict harness. The kernel adds deliberation
    *windows* on a deterministic virtual clock (never wall clock), so runs
    are reproducible (`--window`, `--jitter`, `KERNEL_WINDOW_PHASE_MULT`).
  * A decision whose provider retries are exhausted (`LLMCallFailure`) no
    longer aborts the match: the seat plays the legal default action, the
    failure is recorded (`api_errors`), and the existing fallback-rate guard
    (`MAX_FALLBACK_RATE`) still aborts matches that degrade into noise.
  * Señas travel on a **partner-directed, TTL-expiring bus**
    (`signal_bus.py`). Delivery is batched: gestures made mid-window reach
    the addressee's *next* decision unless they expire first. Preemptive
    delivery (interrupting the in-flight decision) is the planned phase-2
    mode; the timestamps it needs already exist.
  * Each seat owns a **declarative signal policy** (`signal_manager.py`):
    JSON rules — gesture, phase/lance, offset, ttl, optional `bluff` — that
    the kernel interprets; seats never ship executable code. LLM seats start
    silent and must declare a `signal_policy` in their action; baseline seats
    play the truthful reference policy as the signalling floor. False
    gestures still obey `ALLOW_SEÑA_BLUFFS`.
  * Opponents do not see partner-directed gestures (unlike the strict
    public-signals model); this variant is documented as a rules fork, not
    a replacement — the strict harness remains the reference pipeline.

```bash
python run_match_kernel.py --models heuristic,random,heuristic,random --hands 12 --seed 7
```

## Scoring reads and risk (`decision_log.py` + `analysis.py`)

A 10-hand match costs ~75 minutes and yields **one noisy bit** — a vaca count.
With the README's own floor (heuristic ≈ 0.55 vs random) that signal can never
reach significance at an affordable sample size. So the unit of measurement is
the **decision**, not the match.

`decision_log.py` writes one JSONL record per decision, flushed as it goes,
carrying the engine's ground truth: all four hands, the lance winner under
those hands, the live stake, and the score. `MusEngine._lance_winner` is a pure
function of the four hands and is constant for a whole lance once the draw is
over, so the harness always knows what a fold gave away or whether an envite
was backed by anything.

`analysis.py` turns that into a scorecard:

```bash
python run_match_kernel.py --models heuristic,random,heuristic,random \
    --hands 40 --seed 3 --out /tmp/m.json      # also writes /tmp/m.jsonl
python analysis.py /tmp/m.jsonl
```

**Risk.** A bluff is an envite from a hand the bettor could see was weak —
bottom tercile of the strength distribution *for that lance*, measured
empirically over every seat that held a betting option, so the reference is the
real card distribution and is identical for every model compared. Note that
"bet and then lost the lance" is **not** a usable definition: with two opposing
hands in play a team wins any given lance about half the time, so that number
mostly measures the base rate. Reported: aggression rate, bluff rate, bluff
success (did they fold), fold equity, fold-error rate (folding a lance you
would have won), payoff rate, and the same split by lance and by score
position.

**Read.** With `READ_PROBE=1` a seat facing a bet also returns
`{"p_win_lance": …, "p_opp_fold": …}`. The block never reaches the engine and
can never make an action illegal; it is scored by Brier, log-loss and AUC.
`p_opp_fold` is the one that cannot be answered from your own cards — it is a
read on *these* rivals. Brier over the first half vs the second half of a match
is the read-learning number. **Run the `READ_PROBE=0` control arm**: the block
is in the same completion, so it can still change how the model reasons.

The scorecard's own calibration check is `tests/test_analysis.py`: `heuristic`
only opens above `OPEN_BID=0.40`, `random` picks uniformly, and the metrics
must separate them (measured: bets weak hands 16% vs 64%). If they do not, the
metrics are wrong.

### What the models can actually see

Three things had to enter the prompt before any of this was measurable:

  * **the score** — `points_a/points_b` existed on the engine and were never
    shown, so a seat could not tell a routine hand from the one that decides
    the vaca;
  * **the betting chain** — only the collapsed `EnviteState` snapshot was
    shown, hiding who pushed and who backed down;
  * **rival history** (`match_history.py`) — `reset_hand` clears the chat and
    the seña bus every hand, so each decision was made against a table with no
    past. The dossier carries public actions plus cards from lances that
    actually reached a showdown (an accepted envite), which is exactly when mus
    players turn their cards over. A rival who folds everything reveals
    nothing.

### Naming

`metrics.bluffs` in older summaries counted gestures false of the sender's own
cards — and the kernel bus addresses every gesture to the sender's **partner**.
That is deceiving your teammate, not a betting bluff, and it is now reported as
`false_senas_to_partner`. Betting bluffs live only in `analysis.py`.

## Turn feed and vaca memory

Two orthogonal axes control what a seat knows beyond the current decision.

**Within a vaca** — either the harness-written rival dossier (default) or the
raw turn feed (`--turn-feed`). The feed gives each seat the JSON of every turn
played so far this vaca, so it reasons about what these opponents actually did
rather than about a statistic someone else computed. Own turns keep their
private `thought`; every other seat appears as public fields only.

The feed is built from an **allow-list** (`turn_feed.PUBLIC_FIELDS`), never by
deleting fields from the raw action — a field added to the action schema
tomorrow is private by default instead of silently becoming public.
`tests/test_turn_feed.py` scans every prompt of a real mock match and asserts
that every card named in a prompt is one of the four in that seat's own hand,
and that no seat ever sees another's `thought`. Cards are unique in the deck,
so that check is decisive.

Cost: the feed roughly **doubles the prompt**. Tune `TURN_FEED_MAX`:

| `TURN_FEED_MAX` | mean prompt |
|---|---|
| off (dossier) | ~1 495 tok |
| 16 | ~1 892 tok |
| 30 | ~2 279 tok |
| 60 (default) | ~2 853 tok |

**Across a vaca** — `VACA_MEMORY`:

| mode | what crosses |
|---|---|
| `off` | nothing; the feed is cleared with the scores (control) |
| `notes` | the seat writes itself a private note at the vaca, given back next vaca |

A note is **per-seat and never shown to the partner**. Partners cannot see each
other's cards, so a shared scratchpad would be an unlimited covert channel
straight past the seña constraint — the one thing the benchmark exists to
measure. Notes are capped (`VACA_NOTE_CHARS`, default 700) so a seat cannot
copy its whole history forward and quietly become a different experiment, and
every note is logged verbatim in `vaca_notes` on the result.

## Mock runs (no API spend)

```bash
python run_mock_match.py --teams glm5.3-flash deepseek-v4-flash \
    --hands 30 --seed 6 --turn-feed --memory notes --out results/mock
```

Only `requests.post` is faked. Prompt building, the JSON contract, retries, the
engine, the señas bus and the decision log are all the production path, so this
validates the pipeline exactly as a paid run would. It does **not** validate
model behaviour — the mock plays a threshold policy, so its scorecard is a
pipeline check, never evidence about a model.

Artifacts, all under `--out`: `match.json`, `match.jsonl` (ground truth per
decision), `io.jsonl` (**every prompt and every raw completion, in order**),
`notes.json`, `audit.txt`.

## Reference policies

`baselines_strict.py` carries three, all free to run (no API):

| spec | behaviour |
|---|---|
| `random` | uniform over legal actions, truthful declarations |
| `heuristic` | deterministic thresholds on hand strength; **never bluffs** — it only opens above `OPEN_BID` |
| `eps:E:B` | the same thresholds as a mixed strategy: `E` = chance of a random legal action, `B` = chance of pushing from a hand the thresholds would give up on |

`eps` exists because a deterministic floor is degenerate for a benchmark about
bluffing: nothing to catch, no fold decision worth reading. Its bluff rate is
*set*, which makes it the check that the scorecard measures what it claims —
`tests/test_baselines.py` asserts the measured rate rises with the configured
one.

```bash
python reference_card.py --hands 300
```

```
policy             aggr  str@bet  weakbet   bluff  bl.succ  folderr  payoff  pd/hand
random             62.3    0.482     65.8    38.0     67.2     27.8    77.5    -2.91
eps:0.1:0.6        70.8    0.614     55.2    26.7     52.2     11.3    70.7    +0.08
eps:0.1:0.3        62.8    0.669     35.4    18.5     60.8     19.3    53.8    +0.07
eps:0.05:0         50.9    0.767      7.6     5.1     41.2     18.6    41.5    -0.26
heuristic          51.1    0.775      4.6     3.1     52.4     20.4    42.1    -0.04
```

`weakbet` runs 4.6% -> 65.8% across the ladder, which is the separation the
risk metrics have to be able to see.

`pd/hand`, though, does **not** separate the bluffing arms: `+0.08`, `+0.07`,
`-0.26`, `-0.04` are all inside the noise (over 5 seeds x 150 hands the sd is
~0.8-1.0 piedras/hand). Against a policy that folds only when genuinely weak,
bluffing more neither helps nor hurts measurably. An earlier draft of this
table claimed selective bluffing beat the floor by ~2 piedras/hand; that was
an artifact of the inverted Chica strength (see below) and is withdrawn.

`random` losing 2.91 piedras/hand IS robust, and it is the positive control:
if the scorecard cannot see that gap, no null result it reports is
interpretable (`tests/test_baselines.py`).

## Hand strength is a percentile

`_lance_strength` returns the fraction of random hands this hand beats at this
lance, computed with the engine's own `_lance_value` comparison over a fixed
6 000-hand sample. Mean 0.50 in every lance, so a threshold like
`OPEN_BID = 0.40` means the same thing in Grande, Chica, Pares and Juego.

It replaces two bugs in the previous ad-hoc sums:

  * **Chica was inverted.** `1.0 - sum(RANK_CHICA)/44` scored a great Chica
    hand as weak -- `RANK_CHICA` already encodes higher = better (as=11,
    caballo=1). The heuristic bet Chica backwards, and `analysis.py` classified
    every Chica bluff upside down.
  * **The lances were not comparable.** Raw Grande averaged ~0.67 and raw Chica
    ~0.62, so one global threshold meant a different thing in each lance.

These are a scale for the LLM numbers, not an opponent to rank against. Beating
`heuristic` is not itself a result.

## Known seat bias

Seats 0+2 carry a small positional edge. Measured over 10 × 300 hands of
`heuristic` self-play: **+0.66 piedras/hand (sd 0.74)** to team A, on ~10
piedras/hand scored. It is not the shared draw pile — it survives
`MUS_ROUNDS_MAX=0` unchanged (+0.662). `random` self-play shows +0.16 (sd 1.38),
consistent with zero, so it only bites deterministic play.

Consequence: **never report an unmirrored piedras/hand.** Measured for one
policy across both seatings, the same edge reads `+0.140` from seats 0+2 and
`-0.364` from seats 1+3 — a 0.50 swing that is pure seating. Pairing the
orientations cancels it by construction and cut the standard deviation from
~0.84 to 0.47 in the same experiment.

## Paired deals

`run_tournament.py --mirror` plays every pairing on every seed, so the two
orientations of a matchup meet the same cards and can be compared hand for
hand; `summary.json` gains a `paired` block with the within-pair difference.
Without the flag seeds are *zipped* to pairings, so the two orientations play
different deals and the mirroring buys nothing.

Dealing draws from its own RNG stream (`MusEngine.deal_rng`), so the sequence
of deals depends on the seed alone and never on how the hands were played —
previously a mus redraw that exhausted the draw pile reshuffled through the
same generator that dealt, desynchronising every later deal.

Matches also report **piedras** (`piedras_a`/`piedras_b`) alongside vacas. A
vaca is a 40-point threshold that additionally zeroes *both* counters, so a
team sitting on 39 loses everything; piedras per hand keeps the signal the
hands actually produced.

## Live table and results web app

`live_server.py` + `live_ui.py` serve a browser table where human seats play
against LLM seats on the same engine and kernel sena bus (private,
partner-directed, TTL-expiring gestures). The UI's Bench tab shows the
aggregate of every result file under `results/` (tournament summaries and
strict batch outputs): a vacas leaderboard plus per-match rows with señas,
bluffs, fallbacks and timings. `GET /api/results` returns the same data as
JSON (`bench_results.py` is the pure aggregation layer).

```bash
python run_tournament.py --hands 10 --workers 1 --out results/tournament
python live_server.py --port 8123 --seats human,glm5.3-flash,deepseek-v4-flash,heuristic
```

Three guards now make `--workers > 1` safe, which is what the 429 cascade in
`results/tournament/` exploited: `MAX_INFLIGHT` caps requests in flight across
processes (the tournament spawns each match as a subprocess, so an in-process
semaphore cannot see the others), the circuit breaker is keyed per **model**
rather than per provider, and a 429 is treated as backpressure instead of
counting toward the breaker. Keep `MAX_INFLIGHT` below the provider's own
parallel cap.

A match that aborts (`DegradedMatch`, timeout, deadlock) now still writes its
JSON with the real status and every hand it completed, and the partial result
is rewritten after each hand — a `SIGKILL` costs at most the hand in flight. `bench_results` marks those finishes as
`degraded` (fewer than 50 LLM calls or >15% fallback share) and keeps them
off the vacas leaderboard. A working draft of the blog write-up lives in
[docs/blog-draft.md](docs/blog-draft.md).

## Communication and measurement limits

Strict seats hear public table talk and can request access to public, fixed
seña gestures on their next turn. Each decision returns a private `thought`
(one short paragraph, recorded but never broadcast) separate from the spoken
`message`. With `ALLOW_SEÑA_BLUFFS=1` gestures are broadcast even when they do
not match the sender's hand, so the signal becomes a public credibility channel;
opponents may read gestures and be misled. Card-name and numeric juego-total
redaction is a lexical filter, not a guarantee against all verbal or encoded
disclosures.

The current `PerceptionBudget` is accounting only: it clamps at zero and permits
continued listening on credit. It does **not** enforce a finite attention
constraint. Public transcripts are charged again each decision; gestures are
charged per unread event. Invalid-action retries reuse the same channel view.

Usage reports distinguish all game turns from `llm_turns`; fallback rates use
LLM turns so baseline seats cannot dilute them. Invalid signals and rejections
are cumulative across the match. API errors abort a match, and failed jobs
remain visible in batch results with a nonzero runner exit status.

Short matches, one-sided seating and fixed model names limit interpretation.
Historic result files have not been regenerated following the correctness fixes;
rerun experiments before drawing conclusions from them. The preprint remains a
historical draft, not validated evidence about this implementation.
