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

Keep tournament `--workers` at 1 unless your provider tolerates concurrent
chats; a 429 cascade opens the nan circuit breaker and can turn a whole
match into default-action noise. `bench_results` marks those finishes as
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
