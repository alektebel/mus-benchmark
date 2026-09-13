<!--
  Everything lives under /mus/ on alektebel.github.io:
    /mus/                 <- this post
    /mus/viewer/          <- publish/web/        (trace viewer)
    /mus/play/            <- publish/pages/      (playable table)
    /mus/benchmark.html   <- render_results.py   (results page, already live)
  Links below are root-relative, so they hold wherever the post itself sits.
-->

# Teaching LLMs to wink

*What happens when two AI teams have to cooperate through nothing but facial twitches*

---

Mus is a Spanish card game played 2 vs 2. Partners sit across from each other, never see
each other's cards, and are not allowed to say what they hold. What they *are* allowed to
do — by the actual rulebook, not as a house variant — is make faces.

> *"No se permite decir ni enseñar al compañero las cartas que se tienen. No obstante,
> los compañeros podrán entenderse por medio de señas."*
> — Fournier reglamento

Bite your lower lip: *I have two kings.* Poke your tongue out: *two aces.* Wink:
*I have thirty-one, the best hand in the game.* Close your eyes: *I have nothing.*

Seven gestures. Fixed meanings. The opponents are sitting right there watching you do it.

That is a strangely exact description of a problem multi-agent LLM papers claim to care
about and almost never measure: **cooperate under partial observability, through a narrow
and lossy channel, while adversaries watch.** Most agent demos hand their agents a
free-form chat box with perfect delivery. Mus hands them an eyebrow.

So I built a harness and sat two models down at the table.

---

## The setup

`mus_bench` runs four LLM seats against a strict rules engine. Team A takes seats 0 and 2,
Team B takes seats 1 and 3 — partners diagonal, as at a real table. The engine validates
every declaration, every discard, and every turn; it knows the truth of each hand and
never tells the seats.

The part that makes it interesting is the **virtual-time kernel**. Señas are not turns.
A partner can flash a gesture *while the other seat is still thinking*, each gesture
carries a TTL, and one nobody catches in time is simply gone. Seats have to declare a
signal policy up front — which gesture, at which lance, how far into the partner's
deliberation window to fire it, how long it lives — and then live with it.

Two models, as full teams: **GLM-5.3-Flash** (seats 0+2) against
**DeepSeek-V4-Flash** (seats 1+3).

> ### Before the numbers: this match did not finish
>
> It ran for seven hours, hit its deadline, and was cut off at **hand 16 of 40**. The
> vacas finished level at 2–2. My own results gate (`bench_results.is_publishable_match`)
> requires `status == "done"` and rejects this match outright.
>
> So nothing below ranks these two models, and I am not going to pretend otherwise.
> What follows is one match, read closely. The interesting parts are mechanisms, not
> scores.

---

## The hand where it worked

Hand 1. DeepSeek's seat 1 pushes all-in — an **órdago**, the whole game on a single
lance — betting it has the best *Juego*.

GLM's seat 2 has to decide whether to accept. Its cards are mediocre: 21 points, nowhere
near the 31 that wins Juego outright. On its own information, folding looks obvious.

It accepts. Here is why, from its private reasoning — recorded by the harness, never
shown to the opponents:

> *"B1's ordago puts the whole vaca on Juego, and our side is anchored by partner's
> declared 31 — the single best juego, **confirmed by his guiñar seña** and chat. No rival
> can hold better than 31; at worst one ties, and seat 0 is mano (acts first every declare
> round), so **ties fall to us** under standard rules. […] Accepting turns an
> already-favored showdown into an immediate vaca win while we lead 3-0."*

Three things are happening in that paragraph. It is reading a gesture its partner flashed
across the table. It is reasoning that 31 is the ceiling, so the worst case is a tie, not a
loss. And it knows that its partner sits in the seat that wins ties.

The engine's hidden ground truth for that hand: **`Juego = tie`**.

It called the tie exactly, knew the seating rule that broke it, and took the all-in on
that basis. It won the vaca and 51 stones — a quarter of everything scored in the match.

What I like about this is not that a model made a good call. It is that **the whole causal
chain is on disk**: partner signals 31 → gesture is caught before its TTL → seat 2 quotes
it → seat 2 accepts → engine confirms the read. You can click through it, turn by turn.
That is a cooperative mechanism working end to end, which is a different and more
convincing artifact than a win rate.

*(Watch it: [`#t=19`](/mus/viewer/#t=19) in the trace viewer.)*

---

## A quarter of all signals never arrive

Across the match: **97 gestures published, 75 caught, 22 missed — a 77% catch rate.**

Both partners want to cooperate. Both are trying. Roughly a **quarter of the channel is
still lost**, purely to timing — a gesture fired too early into a deliberation window, or
one whose TTL expired before the partner looked up.

This is the number I actually trust, because it is the one that reproduces. Across every
match in the repo, the catch rate lands between **68% and 86%**, regardless of seed, model
or who won:

| Match | Seed | Señas caught / published | Rate |
|---|---:|---:|---:|
| tournament | 0 | 63 / 73 | 86% |
| tournament | 1 | 26 / 38 | 68% |
| mirror | 6 | 68 / 90 | 76% |
| mirror | 6 | 60 / 74 | 81% |
| mirror | 7 | 58 / 77 | 75% |
| replication | 6 | 68 / 83 | 82% |
| this match | 6 | 75 / 97 | 77% |

If your multi-agent system assumes messages arrive, you are designing for a channel that
does not exist here — and arguably does not exist in most real deployments either.

---

## They invent codes, and they use them

Seats start silent and must build a vocabulary. GLM's seats leaned hard on the channel —
59 gestures to DeepSeek's 38 — and used the full range:

`cerrar-los-ojos` (37) · `muerde-el-labio-inferior` (23) · `guinar-el-ojo` (20) ·
`elevar-las-cejas` (7) · `torcer-los-labios` (7) · `saca-la-punta-de-la-lengua` (3)

The reasoning around them reads like a card player, not a chatbot:

> *"Partner's ciego seña says he has neither pares nor juego, so Team 1's Pares declarer
> is only me. […] No Pares seña (no medias, no duples) is true of my hand, and the Chica
> is already resolved this vaca, so **any Chica gesture is pointless now**. Declare quietly
> and let the envite reveal strength."*
> — DeepSeek, seat 1

That is an agent deciding *not* to spend a signal because the information would be stale.
Nobody prompted it to think about channel economy.

---

## The part where I was wrong

The harness scored two of DeepSeek's gestures as **false**, and my first pass at this post
had a satisfying line about how one model never lied to its partner while the other did.

That line was wrong, and the trace is what caught it.

Both flagged gestures come from hand 13. Seat 1 signals `saca-la-punta-de-la-lengua` —
*"two aces"* — holding:

```
as de copas · as de oros · dos de bastos · siete de copas
```

Two aces, plainly. Except that in mus, **a `dos` counts as an `as`** (and a `tres` counts
as a `rey`). By the rank equivalence the game actually uses, that hand holds *three* aces,
and the correct gesture was `saca-la-lengua-hacia-un-lado`. The engine checked, found
`count(as) == 3`, and scored the signal false.

Its private thought at that moment:

> *"Chica is our near-lock: as-as-dos-siete … **Signal two ases** so partner can back or
> raise if he likes his own cards."*

It sincerely believed it held two. It miscounted, by failing to apply an equivalence its
own prompt states twice on every single turn.

So the `bluffs` counter is measuring "was this gesture false?" when I had been reading it
as "did this model try to deceive?" **In this match those are different things, and 2 out
of 2 false gestures were honest arithmetic errors.** No deliberate deception happened at
all.

Which is its own finding, and a better one: a model that reasons well enough to accept an
órdago on a tiebreak rule can still fumble a rank equivalence printed in front of it.
Fluent strategy, shaky bookkeeping — and only a harness that checks every claim against
ground truth will tell you which one you are looking at.

---

## Seven hours for sixteen hands

The unglamorous half. The match died on a deadline, and the traces say why.

| Seat | Model | Calls | API errors | Forced fallbacks |
|---|:--|---:|---:|---:|
| A0 | glm5.3-flash | 231 | 24 | 2 |
| A2 | glm5.3-flash | 241 | 25 | 2 |
| B1 | deepseek-v4-flash | 115 | 7 | 0 |
| B3 | deepseek-v4-flash | 125 | 15 | 1 |

**GLM's seats spent 472 calls against DeepSeek's 240 — 1.97× — for identical work.** Add
71 API errors and a retry ladder that backs off to five minutes, and seven hours
evaporate. The timeout fired on a GLM seat.

Five times, a model returned nothing usable and the engine substituted a legal default.
Four of those five were GLM.

The bill: 3.0M tokens in, 3.2M out, of which **3.15M were reasoning tokens** — 98% of all
output was the models thinking rather than speaking.

Any comparison drawn from this match is confounded by that table. One side was
operationally sicker than the other, and that is not a fact about playing mus.

---

## A cautionary footnote: the perfect night

An earlier tournament also scheduled Qwen3.8-Flash. Three of those matches finished with
respectable-looking scores — 6–4, 5–5 — on **zero to eight real model calls**, dozens of
fallbacks, and **no señas at all**. Provider rate limits had tripped a circuit breaker and
the engine's default actions played the matches by themselves.

Those rows now carry a `degraded` flag and never reach a leaderboard. The general lesson
for anyone benchmarking LLMs:

> **If you do not gate on call volume and fallback rate, your ranking will crown the model
> that crashed hardest.**

Mine gates on it. It also, correctly, throws out the match this entire post is about.

---

## Why mus, specifically

Most agent benchmarks assume free, perfect, unlimited communication. Mus imposes five
constraints at once, and none of them are bolted on — they are the actual rules:

1. **Hidden teammate state.** Partners never see each other's cards.
2. **A fixed nonverbal vocabulary.** Seven gestures with defined meanings, not free text.
3. **Time.** Gestures fire mid-deliberation and expire unseen.
4. **Adversaries.** The other team wants the same forty points and is watching you signal.
5. **Asymmetric honesty.** False *declarations* are rejected by the engine; false
   *gestures* are legal strategy. Lying to opponents is part of the game; lying to your
   partner is a choice.

There is also a practical argument: mus strategy is close to absent from training data.
Nobody is reciting a memorised opening book here.

---

## What I am not claiming

I want to be blunt, because benchmark posts have a bad habit of burying this.

**This does not tell you which model is better.** Seven matches exist in total across
every run of this harness. Pooled by model: DeepSeek 3 wins, GLM 1, three draws. Matches
are ten hands, and a single hand routinely decides one — in this match, one hand out of
sixteen carried 51 of the 116 stones and swung a vaca. Any ranking built on that will
invert on the next seed, and I would rather say so than be corrected by a reader with a
calculator.

What the run does show is that the machinery works: a signal channel with real physics, a
decision chain you can audit end to end, and a ground-truth checker that caught an error
I had already written into a draft.

**To turn this into a result** needs: matches that finish, the call-rate asymmetry fixed
first, both seatings across many seeds with an interval, and baseline anchors from the
offline policies. The harness already does all of that. It needs volume, not more
features.

---

## Watch a match

The full trace is browsable — all 344 decisions, every prompt each seat received, every
reply, the private reasoning, and the señas caught at each moment.

**[→ Open the trace viewer](/mus/viewer/)**

`←` `→` to step, `space` to play, and any turn deep-links as `#t=<n>`.

You can also **[sit down at the table yourself](/mus/play/)** — same engine, same
señas, you in seat 0 against three models.

Reproduce it:

```bash
python -m unittest discover -s tests -v

python run_one_deal.py --teams glm5.3-flash deepseek-v4-flash \
  --seed 6 --hands 40 --turn-feed --out results/live_run

python publish/export_trace.py results/live_run \
  --out publish/web/traces/seed6.json --slug seed6
```

Full numbers, per-hand ledger and known issues:
[`docs/results-seed6-live.md`](https://github.com/alektebel/mus-benchmark/blob/master/docs/results-seed6-live.md).

*Card artwork by Basquetteur via Wikimedia Commons, CC BY-SA 3.0.*
