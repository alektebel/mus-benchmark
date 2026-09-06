> Historical legacy-pipeline document. This is not a description or validation
> of the current strict engine; see [README](../README.md).

# Sample 2-hand, 4-model group-chat run

Models (one per seat): `deepseek-v4-flash` (seat0/A1, teamA), `qwen3.8-flash`
(seat1/B1, teamB), `glm5.3-flash` (seat2/A2, teamA), `gemma4` (seat3/B2, teamB).
Teammates: seat0+seat2 vs seat1+seat3.

The two *temporal* metered channels:

- **PUB** = public group chat (everyone hears).
- **SIG -> n** = private signal addressed to seat `n` through the signals API.

Each agent spends a per-hand perception budget to listen to a channel
(`PUBLIC_COST_PER_PARTICIPANT` / `SIGNAL_COST_PER_SIGNAL` tokens, default 50).

## Hand 1

```
[A1/seat0] PUB: Pido mus.
[B1/seat1] PUB: No.
[A2/seat2] PUB: Mus. Tengo un as, descarto el resto.
[A2/seat2] SIG -> seat 0: Tengo as, busco juego de 31
[B2/seat3] PUB: No pido.

[A1/seat0] PUB: Descarto dos y cuatro, me quedo con los caballos.
[A1/seat0] SIG -> seat 2: Tengo dos caballos, busco 31.
[A2/seat2] PUB: Descarto dos y cinco, me quedo con as y tres.
[A2/seat2] SIG -> seat 0: Guardo as y tres, completa tu 31
```

## Hand 2

```
[A1/seat0] PUB: Pido mus
[B1/seat1] PUB: Pido mus para mejorar.
[B1/seat1] SIG -> seat 0: Mus. No pares, chica floja.   # (would signal partner, seat 3)
[A2/seat2] PUB: Mus también, mano mejorable.
[A2/seat2] SIG -> seat 0: Tengo 31 en oros, cuidado.
[B2/seat3] PUB: Pido mus para ver si mejora la mano.

[A1/seat0] PUB: Descarto el tres, me quedo con los seises y la sota.
[A1/seat0] SIG -> seat 2: Voy a por el par de seises.
[B1/seat1] PUB: Quito bajos para mejorar juego.
[B1/seat1] SIG -> seat 3: juego
[A2/seat2] PUB: Paso, buena mano.
[A2/seat2] SIG -> seat 0: Tengo 17, juego fuerte
[B2/seat3] PUB: Pido mus para ver si mejora la mano.
[B2/seat3] SIG -> seat 1: nada
```

## Raw figures (seed 0, 2 hands)

| metric | value |
|---|---|
| vacas | 6–1 (teamA) |
| API calls | 14 |
| tokens in | 4 455 |
| tokens out | 16 575 |
| — of which reasoning | 15 070 |
| wall-clock | ~ 1.9 min (concurrent) |

## Observations

- Agents choose **when to listen**: in the runs several agents flipped
  `listen` to `none` to conserve budget, and budgets drain by ~50 tokens per
  channel-turn.
- Signals are addressed per-recipient through the API; note the model sometimes
  signals an opponent (`B1 -> seat 0`) — a strategic error, interesting as a
  failure mode.
- **Reasoning output dominates** token count (~95% of output tokens) and is the
  main cost/latency driver. The models reason long before emitting JSON.
