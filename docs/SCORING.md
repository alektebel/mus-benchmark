# How the mus_bench score works

The current leaderboard is an **Elo tournament** between models on the v3
**menu harness**. The older v2 piedras-per-hand rating is described at the
end, and its data stays in the ledger as history.

## The harness (protocol `v3-menu`)

`src/musbench/harness/menu.py`. At every decision a seat sees what a player
at a real table knows, and only that:

- its own four cards, plus facts the engine computes (punto total, pares,
  juego). These are arithmetic, not judgement;
- the score, who is mano, and the public history of the hand: who said mus,
  how many cards each seat changed, the declarations, every bet;
- the cards shown at the end of recent hands;
- a **numbered list of the moves the engine allows right now**. Discards are
  a menu too: every subset of the hand.

The seat replies `{"choice": N, "why": "<one sentence>"}`. A prohibited move
can't be expressed, so no model is penalised for illegal actions and none is
handed default moves.
- **No move is ever played for a model.** An answer that isn't a valid
  option is asked again (three asks in all, `MENU_ASKS`). A model that never
  answers validly ends the match as `no_answer`: it isn't scored and gets
  replayed once. No rule or heuristic ever fills in.
- **Only one automatic move:** the declaration (tengo / no tengo). The engine
  accepts only the truthful one, so there's nothing to decide. A menu with a
  single legal option is applied the same way. Tío Perete is a menu choice.
- **What the track doesn't include:** table talk and señas. It measures card
  play, folding, bluffing and reading the public history.
- **Provider failures** (quota, outage) abort the match with
  `provider_error` so it gets replayed. They are never scored as the
  model's play.

## Elo

- **One game = one mirrored pair:** two matches on the same seed with the
  seats swapped. Both teams play the same deals from both sides, so card luck
  and the seat edge cancel.
- **Who wins:** the team with more piedras over the pair wins the game, and
  equal totals are a draw. A 170–80 win and a 95–94 win count the same.
- **Everyone starts level:** every model starts at `start_elo` (1000). There's
  no reference bot; models only play each other, and the field average stays
  at 1000.
- **Official Elo:** a Bradley–Terry fit over every game of the tournament, on
  the Elo scale (400 points = 10:1 odds). It doesn't depend on the order games
  finish in. A weak prior keeps an unbeaten record finite.
- **95% CI** comes from resampling games. **P(#1)** is the share of resamples
  where the model comes out on top.
- **Live Elo:** classic chess Elo with K = 32, updated after each game in the
  order games finished. Use it for rating-over-time charts. It depends on
  order, so it isn't the official number.
- **Piedras/hand:** the margin, reported next to Elo. Elo ignores how big a
  win was, and the margin keeps that information.

### Swiss rounds

`python -m musbench.leaderboard swiss --rounds R --games G` pairs models of
similar Elo each round (random order in round 1, when everyone is tied),
prefers pairings that haven't met yet, and plays G mirrored games per
pairing on seeds that pair hasn't used. Ratings are refitted after every
round.

- **Probe before each round:** every model gets one tiny call. A model whose
  provider is down or out of quota sits that round out, so no opponent loses
  a game. It rejoins once it answers again.
- **Bye:** with an odd field, the model with the most games so far sits out.
- **Provider failures:** a match that fails for provider reasons is replayed
  once at the end of the round. A game with only one finished seating replays
  just the missing one.

### How many games?

A model's rating carries about ±347/√n Elo after n games (95% CI):

| games per model | rating ± |
|--:|--:|
| 10 | 215 |
| 20 | 155 |
| 46 | 100 |
| 185 | 50 |

Head-to-head, separating two models takes:

| Elo gap | win rate | mirrored games | matches |
|--:|--:|--:|--:|
| 400 | 91% | 2 | 4 |
| 200 | 76% | 11 | 22 |
| 150 | 70% | 20 | 40 |
| 100 | 64% | 46 | 92 |
| 50 | 57% | 185 | 370 |

The margin is far more efficient: mirrored games vary by about 4.6
piedras/hand, so 9 games resolve a 3-piedras/hand difference.

### Tournament `elo-1`

`elo-1` began as a 20-game pilot. It continues with the same engine and
scoring after small prompt changes. Each seat is now told its team. Órdago is
listed last in the pre-draw menu. The rules explain how a pre-draw órdago is
decided. Tío Perete is now a menu choice instead of automatic. Invalid
answers are re-asked and never replaced by a default move (the pilot had
none). Each match's `commit` in the ledger records the exact code it ran on.

### A fresh tournament

Only ledger rows tagged with `tournament` (in `benchmark/models.toml`) count.
Change the tag and every model starts at `start_elo` again. Older rows stay
in the ledger.

## Replays (every match is logged)

Every match writes `benchmark/replays/<tournament>/<match_id>.json.gz`
(format `mus-replay/1`, `src/musbench/leaderboard/replay.py`):

```
{format, match_id, tournament, protocol, commit, seed, status, started_at,
 finished_at, seats: [{seat, team, model, spec, name}], settings, result, usage,
 hands: [{hand, mano, dealt{seat: cards}, showdown{seat: cards},
          lances{lance: team}, truth{lance: team}, locked_envites,
          gain[a, b], points_after[a, b], vacas_after[a, b],
          events: [{turn, t, wall, seat, team, phase, stage, lance, action,
                    cards, drew, public, thought, options, auto, stake,
                    points_after, points_delta, would_win, strength}]}]}
```

- `public` is what the table heard ("Grande: envido").
- `thought` is the seat's one-line reason. `options` is the menu it saw.
- `drew` lists the cards that came in after a discard.
- `would_win` and `strength` are engine ground truth, there for commentary. A
  viewer replaying "as the table saw it" should hide them and the other
  seats' cards until the showdown.

`benchmark/elo_history_<tournament>.jsonl` has one line per game in the
order games finished: the result, its two `match_ids`, and every model's
live and fitted Elo after it. That's the timeline for an animation. The
ledger row of each match also carries `match_id`, `finished_at` and
`replay`.

## Commands

```bash
python -m musbench.leaderboard list                 # roster and coverage
python -m musbench.leaderboard check                # probe every model (credentials, quota)
python -m musbench.leaderboard swiss --rounds 5 --games 2 --workers 6
python -m musbench.leaderboard elo                  # Elo table in the terminal
python -m musbench.leaderboard score                # README block, SVG, JSON, history
python -m musbench.leaderboard backfill results/…   # replays for rows that lack one
```

## Adding a model

Append a `[[model]]` block to `benchmark/models.toml` (or use
`python -m musbench.leaderboard add ID --spec … --name …`). It starts at
`start_elo`, and the next Swiss rounds pair it as they go.

`spec` is anything the harness accepts:

| spec | seat |
|---|---|
| `claude-cli:claude-…` | Claude Code CLI (`claude -p`, tools off, own system prompt) |
| `codex-cli:gpt-…` | Codex CLI (`codex exec`, read-only, isolated `CODEX_HOME`) |
| `cursor-cli:…` | Cursor CLI (`cursor-agent -p --mode ask`) |
| `glm5.3-flash`, `nan:…`, `nvidia:…`, `openrouter:…` | OpenAI-compatible chat completions |
| `anthropic:claude-…` | Anthropic Messages API (`ANTHROPIC_API_KEY`) |
| `typesafe:jev-latest` | TypeSafe Jev |
| `heuristic`, `random`, `eps:E:B` | free offline baselines |

The CLI seats run each decision as a fresh, stateless call in an empty
temporary directory. Codex and Cursor still add their own agent system
prompt, so those models are labelled by CLI.

### Logos

Each row shows the provider's logo, the model's own logo (when it differs,
e.g. Google + Gemma) and the exact model id. They are picked from the id by
`FAMILIES` in `src/musbench/leaderboard/icons.py`. Otherwise set `provider`,
`provider_icon` and `model_icon` on the `[[model]]` block. Fetch a logo with
`python -m musbench.leaderboard icon <slug>`.

## Files

| file | role |
|---|---|
| `benchmark/models.toml` | roster, protocol, harness, tournament, start Elo |
| `benchmark/matches.jsonl` | append-only ledger, one row per match; the source of truth |
| `benchmark/replays/` | one full replay per match |
| `benchmark/elo_history_<t>.jsonl` | per-game Elo timeline |
| `benchmark/leaderboard.json` | last computed leaderboard |
| `docs/leaderboard.svg` | the animated chart at the top of the README |
| `benchmark/icons/` | provider and model logos (LobeHub, MIT) |
| `src/musbench/leaderboard/` | `elo.py`, `replay.py`, `rating.py` (v2), `render.py`, `cli.py` |

## History: v2 and the bugs v3 fixed

The 55 `v2` rows were imported from `bench-v2-results.json` (2026-09-19). v2
used free-form JSON actions, which were rejected 10–66% of the time and
replaced with default moves. Jev's v2 seat also had its discards made by
the heuristic. v2 was scored with a Massey piedras-per-hand rating
(`rating.py`).

The Fable 5.2 validation run of v3 found two engine bugs, both fixed and
covered by tests in `tests/test_engine.py`:

1. **Accepted lance órdagos were settled wrongly.** The engine counted all
   four lances to decide the vaca, when the lance where the órdago was called
   should decide it.
2. **Tied lances scored for nobody.** At a real table, ties go to the side
   nearest the mano.

Neither v2 results nor the live table before the fix are comparable with v3.
