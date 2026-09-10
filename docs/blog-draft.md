# Teaching LLMs to wink: partner signals in a Spanish card game

*Draft — numbers from clean kernel matches only (DeepSeek-V4-Flash vs GLM-5.3-Flash, seeds 0–1). A 6-seed replication is running; refresh the tables when it finishes.*

---

Mus is a 2v2 Spanish card game where partners sit across from each other and are not allowed to see each other's cards. In the real game, players invent tiny facial gestures — *señas* — to smuggle information past the opponents: raise an eyebrow for duples, bite a lip for a strong Grande, wink for thirty-one.

That constraint is almost exactly what multi-agent LLM systems claim to care about and almost never measure: **cooperate under partial observability, with a noisy, time-limited channel, while adversaries watch for leaks.**

`mus_bench` turns that into a reproducible harness. The interesting variant is not the turn-gated “strict” table — it is the **virtual-time kernel**, where a partner can gesture *while the other seat is still thinking*, and a gesture that nobody catches before its TTL expires is simply gone.

## What we measured

Two flash models sat as full teams (seats 0+2 vs 1+3), ten hands each, both seatings:

| Match | Vacas | Hand wins | Señas published / caught / missed | Bluffs | LLM calls | Fallbacks |
|-------|------:|----------:|----------------------------------:|-------:|----------:|----------:|
| DeepSeek vs GLM (seed 0) | **1–0** | 6–4 | 73 / 63 / 10 | 15 | 372 | 12 |
| GLM vs DeepSeek (seed 1) | **0–1** | 4–6 | 38 / 26 / 12 | 13 | 286 | 12 |

**DeepSeek took the only vaca in both orientations.** That is a tiny sample, but it is seating-symmetric: the same model won whether it dealt first or second. Across both matches: **111 gestures published, 89 caught (80%), 22 missed**, and **28 false gestures**.

Vacas are games to 40 points. Hand wins (6–4, 4–6) show the matches were competitive; the single vaca each way is where the night ended.

## Models invent real partner codes

Seats start silent. They must *declare* a signal policy — which gesture, which lance, which offset into the partner's deliberation window, how long it lives. Examples from the winning DeepSeek seats:

- `elevar-las-cejas` during Pares declaration, offset 0.5 into partner’s window, TTL 4s — “I have duples.”
- `cerrar-los-ojos` during Chica envite, offset 0.6, TTL 5s — “I’m ciego / don’t back me here.”

GLM answered with its own codes (`torcer-los-labios` for Pares, `muerde-el-labio-inferior` for Grande). The channel is private and partner-directed: opponents never see the gesture object, only whatever leaks into public table talk.

Catch rates are not free. In seed 0, 10 of 73 gestures expired unseen. In seed 1, nearly a third missed (12/38). That is the blog hook in one number: **even when both partners want to cooperate, timing still drops signals on the floor.**

## They reason about the partner out loud (privately)

Private `thought` fields are recorded but never broadcast. A few lines that would not look out of place at a Basque table:

> “Weak hand: no pairs, sums flat, no juego. Best to ask for mus to replace. **Signal ciego to partner** since it's true… and may guide their later calls.”
> — DeepSeek, seat A0

> “My hand is ciego… **partner's sena confirms he's ciego too**, so he also wants to draw. My only real strength is Chica (as + dos)…”
> — DeepSeek, seat A2

> “Cuatro sietes = cuatro iguales… Gesture **elevar-las-cejas** (duples) so A2 knows to back me in Pares.”
> — DeepSeek, planning a mid-window raise of the eyebrows

That is not prompt theatre about “being a helpful assistant.” It is an agent allocating a scarce nonverbal bit to a teammate under imperfect information.

## And they lie

With bluffs allowed, 28 of 111 published gestures were false (~25%). Some false eyebrows still arrived (`delivered_at` set); some winked into the void. The harness treats bluffing as a first-class outcome, not a bug: a seña is a *claim*, and partners have to decide whether to trust it when the stake climbs.

## A cautionary footnote: Qwen’s “perfect” night

The same tournament also scheduled Qwen3.8-Flash. Three of those matches finished with scores like 6–4 and 5–5 — and **0–8 real LLM calls**, dozens of fallbacks, and zero señas. Provider 429s opened a circuit breaker; the kernel’s legal default actions (`ordago` / `quiero`) played the match alone.

Those rows are now marked **degraded** and excluded from the leaderboard. The lesson for any LLM benchmark blog: **if you do not gate on call volume and fallback rate, your ranking will crown the model that crashed hardest.**

## Why this is worth a post (and a preprint later)

Most multi-agent demos assume free chat. Mus forces:

1. **Hidden teammate state** — partners never see each other’s cards.
2. **A structured nonverbal vocabulary** — fixed Don Naipe–style gestures, not free text to the partner.
3. **Time** — gestures fire mid-deliberation and expire.
4. **Adversarial pressure** — the other team wants the same 40 points.
5. **Truth as a rules constraint** — false *declarations* (`tengo` / `no-tengo`) are rejected; false *gestures* are optional strategy.

The skill floor from offline baselines is thin (heuristic ≈ 0.55 vs random on vacas share), so LLM differences need repetition. That is what the running six-seed DeepSeek↔GLM series is for.

## Status / next refresh

- Publishable so far: **DeepSeek 2–0 vacas** vs GLM, rich seña play.
- In flight: seeds 10–15, both orientations, `results/tournament_ds_glm/`.
- After that: either bring Qwen back at `workers=1`, or stop at a clean two-model story and ship.

Commands to reproduce the clean path:

```bash
python -m unittest discover -s tests -v
python run_tournament.py \
  --pairings "deepseek-v4-flash vs glm5.3-flash;glm5.3-flash vs deepseek-v4-flash" \
  --hands 10 --seeds 10,11,12,13,14,15 --workers 1 \
  --out results/tournament_ds_glm
```

Leaderboard aggregation already drops degraded matches (`bench_results.is_publishable_match`: ≥50 LLM calls and ≤15% fallback share).
