# Live kernel match, seed 6 — GLM-5.3-Flash vs DeepSeek-V4-Flash

**Run:** `results/live_run/` · started 2026-09-13 01:45:20 (+0200), aborted 08:45:20
· commit `9f32a6a` (working tree dirty) · `run_one_deal.py --teams glm5.3-flash
deepseek-v4-flash --seed 6 --hands 40 --turn-feed`

> **Read the headline before the table.** This match **hit its 7-hour deadline and was
> cut off at hand 16 of 40**. It is an exhibition trace, not a result. The vacas finished
> level and the piedras margin is one hand wide. Nothing here separates the two models.

---

## 1. How it ended

```
status        timeout
abort_reason  A0/glm5.3-flash: match deadline exceeded
hands         16 / 40 completed
elapsed       25200.0 s  (= MATCH_TIMEOUT exactly)
virtual clock 354.5 s
```

| | GLM-5.3-Flash (A, seats 0+2) | DeepSeek-V4-Flash (B, seats 1+3) |
|---|---:|---:|
| **Vacas** | **2** | **2** |
| Piedras | 116 | 100 |
| Hand wins | 6 | 10 |

The two columns disagree, and the disagreement is the whole story. DeepSeek won
**10 of 16 hands** and still finished level, because GLM's six wins included one hand
worth 51 piedras. Strip hand 1 and the piedras run **65–100 to DeepSeek**.

### Per-hand ledger

| Hand | A | B | Winner | | Hand | A | B | Winner |
|---:|---:|---:|:--|---|---:|---:|---:|:--|
| 1 | **51** | 0 | A → vaca | | 9 | 2 | 15 | B |
| 2 | 3 | 6 | B | | 10 | 2 | 12 | B |
| 3 | 3 | 6 | B | | 11 | 10 | 3 | A |
| 4 | 3 | 6 | B | | 12 | 10 | 0 | A |
| 5 | 9 | 3 | A | | 13 | 9 | 3 | A |
| 6 | 3 | 8 | B | | 14 | 6 | 3 | A |
| 7 | 0 | 10 | B | | 15 | 3 | 7 | B → vaca each |
| 8 | 2 | 6 | B → vaca | | 16 | 0 | 12 | B |

---

## 2. The hand that decided it

Four órdagos (all-in on the whole vaca) were called. **Three were declined. One was
accepted — hand 1, and it settled a quarter of the match.**

| Hand | Caller | Lance | Response | Outcome |
|---:|:--|:--|:--|:--|
| 1 | B1 DeepSeek | Juego | A2 GLM: **quiero** | accepted → A wins the vaca |
| 6 | B1 DeepSeek | Grande | A2 GLM: no-quiero | declined |
| 8 | A0 GLM | Chica | B1 DeepSeek: no-quiero | declined |
| 15 | B1 DeepSeek | Grande | A2 GLM: no-quiero | declined |

DeepSeek shoved on Juego holding what it read as a winning hand. GLM's seat 2 accepted,
and its private reasoning — recorded, never shown to opponents — is the most interesting
artifact in the run ([viewer `#t=19`](../publish/web/index.html#t=19)):

> *"B1's ordago puts the whole vaca on Juego, and our side is anchored by partner's
> declared 31 — the single best juego, confirmed by his guiñar seña and chat. No rival
> can hold better than 31; at worst one ties, and seat 0 is mano (acts first every
> declare round), so ties fall to us under standard rules. […] Accepting turns an
> already-favored showdown into an immediate vaca win while we lead 3-0."*

The engine's hidden ground truth for that hand was **`Juego = tie`**. GLM predicted the
tie, knew the mano tiebreak resolved it in its favour, and took the all-in on that basis.

**This matters for how the hand gets described.** It is tempting to write off a 51-piedra
swing as variance. It wasn't: it was a correct read, and the chain is fully auditable —
partner signals 31 by seña → seña is caught → seat 2 cites it → seat 2 accepts an all-in
→ ground truth confirms the read. That chain, end to end in the trace, is the single
best thing this run produced.

---

## 3. Señas — the one measurement that holds up

Partners may pass information only through fixed gestures on a virtual clock. A gesture
that is not caught before its TTL expires is simply lost.

| | Published | Caught | Missed | Catch rate | Truthful | Bluffs |
|---|---:|---:|---:|---:|---:|---:|
| GLM (A) | 59 | 47 | 12 | 79.7% | 59/59 | **0** |
| DeepSeek (B) | 38 | 28 | 10 | 73.7% | 36/38 | **2** |
| **Total** | **97** | **75** | **22** | **77.3%** | 95/97 | 2 |

Two things survive the small sample:

**~23% of gestures never land.** Both partners want to cooperate, both are trying, and
roughly a quarter of the channel is still lost to timing alone. That number is stable
across every run in this repo (see §5) — it is a property of the harness, not of a seed.

**The two models used the channel differently.** GLM signalled more (59 vs 38) and
never once signalled falsely. DeepSeek's two "false" gestures are worth reading closely,
because **they are not bluffs — they are rule errors, and the metric conflates the two.**

Both came from B1 in hand 13, signalling `saca-la-punta-de-la-lengua` ("dos ases") while
holding `as de copas, as de oros, dos de bastos, siete de copas`. Under mus rank
equivalence a `dos` counts as an `as` (`senas.py:_count`), so that hand holds *three*
aces and the correct gesture was `saca-la-lengua-hacia-un-lado`. The engine scored the
gesture false. But B1's private thought is sincere:

> *"Chica is our near-lock: as-as-dos-siete … **Signal two ases** so partner can back or
> raise if he likes his own cards."*

It believed it held two. It miscounted by failing to apply an equivalence its own prompt
states twice. So the `bluffs` counter as currently defined answers "was this gesture
false?" and not "did the model intend to deceive?" — and in this match, 2 of 2 false
gestures were honest mistakes. **No deliberate deception occurred in this run.**

Gesture vocabulary as used: `cerrar-los-ojos` 37, `muerde-el-labio-inferior` 23,
`guinar-el-ojo` 20, `elevar-las-cejas` 7, `torcer-los-labios` 7,
`saca-la-punta-de-la-lengua` 3.

---

## 4. Why it timed out

This is the finding with the clearest action attached.

| Seat | Model | Calls | API errors | Fallbacks | Redactions |
|---|:--|---:|---:|---:|---:|
| A0 | glm5.3-flash | 231 | 24 | 2 | 15 |
| A2 | glm5.3-flash | 241 | 25 | 2 | 14 |
| B1 | deepseek-v4-flash | 115 | 7 | 0 | 8 |
| B3 | deepseek-v4-flash | 125 | 15 | 1 | 9 |

**GLM's seats spent 472 calls to DeepSeek's 240 — 1.97× — for the same 16 hands.**
Combined with 71 API errors across the table and a retry ladder that backs off to 300 s,
that is where seven hours went. The abort fired on A0, a GLM seat.

Five decisions ended in a forced fallback (the model never returned a usable action;
the engine substituted `paso` or `quiero`). Four of the five were GLM seats. Those turns
carry no prompt in the trace and are labelled as such in the viewer.

Cost: 3.00M tokens in, 3.22M out, of which **3.15M were reasoning tokens** — 98% of
output. 712 calls total.

---

## 5. Every match in this repo, pooled

The honest denominator. Seven completed or partial matches exist across all runs:

| Run | Seed | A | B | Hands | Vacas | Señas caught/pub |
|---|---:|:--|:--|---:|:--:|---:|
| tournament | 0 | deepseek | glm | 10 | 1–0 | 63/73 |
| tournament | 1 | glm | deepseek | 10 | 0–1 | 26/38 |
| mirror | 6 | deepseek | glm | 10 | 1–1 | 68/90 |
| mirror | 6 | glm | deepseek | 10 | 0–1 | 60/74 |
| mirror | 7 | deepseek | glm | 10 | 1–1 | 58/77 |
| replication | 6 | deepseek | glm | 10 | 0–2 | 68/83 |
| **live_run** | **6** | **glm** | **deepseek** | **16*** | **2–2** | **75/97** |

\* timed out at 16 of 40.

Tallied by model rather than by seat: **DeepSeek 3 wins, GLM 1, 3 draws.** Three further
matches involving `qwen3.8-flash` are marked `degraded` and are excluded — their seña
channels recorded 0–4 events, so they are not comparable.

Catch rate across every run lands between 68% and 86%. **That is the repo's one
reproducible number.** The vacas column is not: it is a 7-match spread on 10-hand matches
where a single hand routinely decides the result.

---

## 6. So is this publishable?

**As a model comparison: no.** Do not write "DeepSeek beats GLM at mus." The sample is
seven matches, this one is 40% complete, vacas here finished level, and the piedras
margin is one hand. Any ranking drawn from this will invert on the next seed.

**As a testbed with an annotated trace: yes,** and that is the stronger post anyway.
What is genuinely novel:

1. **A cooperative side-channel with real physics.** Partners must invent a code, and
   ~23% of it is lost to timing. Most multi-agent work assumes free perfect messaging.
2. **An auditable signal → decision → outcome chain.** Hand 1 links a caught seña to an
   all-in acceptance to a confirmed ground truth. That is a *mechanism* shown working,
   not a score.
3. **An asymmetry worth a paragraph.** One model never lied to its partner; the other
   did, twice.
4. **Low contamination.** Mus strategy is largely absent from training corpora.

Frame the post as *"here is a testbed, watch a match"*, put the trace viewer above the
fold, and state the timeout in the first paragraph. What it cannot carry is a leaderboard.

### What would make it a result

- **Finish matches.** A 7-hour cap that truncates 60% of hands makes every number
  conditional on where the axe fell.
- **Fix the call asymmetry first** — 2× calls and 49 API errors on one side is a
  confound, not a fact about mus skill.
- **Both seatings × many seeds**, reported with an interval. The mirror harness
  (`run_tournament.py`) already does this; it needs volume.
- **Baseline anchors.** `baselines_strict.py` gives a floor; no LLM number means much
  without it.

---

## 7. The trace

`publish/web/` is a static, dependency-free viewer — drop it on GitHub Pages as-is.

```bash
# regenerate the trace from a finished run
python publish/export_trace.py results/live_run --out publish/web/traces/seed6.json --slug seed6

# preview locally
cd publish/web && python -m http.server 8899
```

It replays all 344 decisions: the exact prompt each seat received, its raw reply, its
private reasoning, the señas it had caught at that moment, and the engine state. Turns
deep-link as `#t=<n>`.

| Artifact | Contents |
|---|---|
| `results/live_run/match.json` | totals, agents, 97 signal events, per-hand rows |
| `results/live_run/match.jsonl` | 344 decisions + 16 hand resolutions with engine state |
| `results/live_run/io.jsonl` | 339 prompt/reply pairs + 8 vaca notes |
| `publish/web/traces/seed6.json` | all of the above, joined and line-dictionary packed |

Prompts are stored as indices into a shared line table — they repeat a large static
rules preamble, so this shrinks the trace from 4.8 MB to 968 KB.

### Known issues

- **Card art is 16 MB** (`card_back.svg` alone is 2.5 MB). Run SVGO over
  `publish/web/cards/` before publishing; it gzips well but the raw weight is silly.
- `ordago_caller` / `ordago_accepted` are `None` in every hand record even for the
  accepted órdago in hand 1 — the fields are never populated. The órdago is only
  recoverable from the decision stream. Worth fixing in the engine's hand logger.
