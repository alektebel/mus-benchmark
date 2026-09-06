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

The older `engine.py`, `run_match.py` and `run_match_gc.py` implement a different,
simplified scoring protocol. Their results must not be pooled with strict
results. Historical documentation and baseline figures are in
[docs/legacy.md](docs/legacy.md).

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

## Communication and measurement limits

Strict seats hear public table talk and can request access to public, fixed
seña gestures on their next turn. Gestures are validated against the sender's
hand at decision time; opponents may read them too. Card-name and numeric
juego-total redaction is a lexical filter, not a guarantee against all verbal
or encoded disclosures.

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
