"""Complete game (first team to TARGET_VACAS) with full transcript for review."""
import argparse
import io
import contextlib
import time
from random import Random
from mus_engine import MusEngine, Phase, LANCE_NAMES
import run_match_strict as rms
from groupchat import Channels

SPECS = ["deepseek-v4-flash", "heuristic", "deepseek-v4-flash", "heuristic"]
TARGET_VACAS = 2
MAX_HANDS = 6

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--target", type=int, default=TARGET_VACAS)
    args = ap.parse_args(argv)
    target_vacas = args.target
    if target_vacas <= 0:
        ap.error("--target must be positive")
    engine = MusEngine(rng=Random(args.seed))
    agents = [rms._make_agent(m, s, s % 2, args.seed) for s, m in enumerate(SPECS)]
    for a in agents:
        a.verbose = True
    ch = Channels()
    stats = {"turns": 0, "fallbacks": 0, "events": []}

    t0 = time.time()
    hand = 0
    while max(engine.vacas_a, engine.vacas_b) < target_vacas and hand < MAX_HANDS:
        hand += 1
        print(f"\n{'='*70}\nHAND {hand}  (mano = seat {engine._mano_counter})\n{'='*70}")
        engine.deal()
        rms.reset_hand_channels(agents, ch)
        for s in range(4):
            cards = ", ".join(str(c) for c in sorted(engine.hands[s], key=lambda c: c.rank_index))
            print(f"  seat {s} ({agents[s].name}, team {s % 2}): {cards}")
        print()
        while engine.phase != Phase.DONE:
            a = agents[engine.current_seat]
            lance = LANCE_NAMES[engine.lance_index] if engine.phase == Phase.ENVITE else ""
            print(f"\n--- seat {engine.current_seat} ({a.name}) | {engine.phase.name} "
                  f"{lance} | stake={engine.envite.current} "
                  f"holder={engine.envite.holder} ---")
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    rms.play_turn(engine, a, ch, stats, verbose=True)
            finally:
                print(buf.getvalue().rstrip())
            if engine.phase == Phase.DONE:
                print(f"\n>>> HAND {hand} OVER: vacas A={engine.vacas_a} B={engine.vacas_b}")
                print(f"    jugadas: {[(j.name, j.winner_team) for j in engine.jugadas]}")

    print(f"\n{'='*70}\nGAME OVER after {hand} hands, {round(time.time()-t0)}s "
          f"| VACAS A={engine.vacas_a} B={engine.vacas_b}")
    print(f"LLM usage: calls={sum(a.calls for a in agents if a.is_llm)} "
          f"out_tokens={sum(a.tokens_out for a in agents if a.is_llm)} "
          f"fallbacks={stats['fallbacks']}")
    print("\nSENA LOG (gesture, truthful?):")
    for a in agents:
        if a.is_llm and a.senas_log:
            for g, ok in a.senas_log:
                mark = "OK " if ok else "BLUFF/ERROR"
                print(f"  {a.name}: {g:22s} [{mark}]")
        if a.is_llm and a.invalid_signals:
            print(f"  {a.name}: {a.invalid_signals} invalid (non-reglamento) signals dropped")
    print("\nPUBLIC CHAT:")
    for m in ch.public:
        print(f"  {m.turn}. {m.name}: \"{m.text}\"")
    print("\nSENAS API (final state):")
    for e in ch.signals:
        print(f"  {e.turn}. seat {e.from_seat} -> "
              f"{e.to_seat if e.to_seat is not None else 'ALL'}: {e.text}")


if __name__ == "__main__":
    main()
