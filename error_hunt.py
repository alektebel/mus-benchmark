"""Run LLM dyads vs the floor and collect every mistake they make."""
import io
import json
import sys
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path

from mus_engine import MusEngine
from run_match_strict import run_match_strict

SEEDS = [0, 1]
HANDS = 2


def main() -> None:
    models = sys.argv[1].split(",") if len(sys.argv) > 1 else ["deepseek-v4-flash"]
    Path("err_hunt").mkdir(parents=True, exist_ok=True)
    all_results = []
    t0 = time.time()
    for model in models:
        for seed in SEEDS:
            m0 = f"err_hunt/{model.replace('/','_')}_seed{seed}.log"
            buf = io.StringIO()
            print(f"=== {model} seed {seed} -> {m0} ===", flush=True)
            try:
                with redirect_stdout(buf):
                    res = run_match_strict(MusEngine(),
                                           [model, "heuristic", model, "heuristic"],
                                           hands=HANDS, seed=seed, verbose=True)
            except Exception:
                traceback.print_exc(file=buf)
                raise
            finally:
                Path(m0).write_text(buf.getvalue(), encoding="utf-8")
            res["log_file"] = m0
            all_results.append(res)
            Path("err_hunt/summary.json").write_text(
                json.dumps(all_results, indent=2), encoding="utf-8")
            print(f"    vacas {res['vacas_a']}-{res['vacas_b']} | {res['elapsed']}s "
                  f"calls={res['usage']['calls']} fallbacks={res['usage']['fallbacks']}")
            for a in res["agents"]:
                if a["is_llm"]:
                    print(f"    {a['name']}: rejects={a['rejections']} "
                          f"redactions={a['redactions']} bad_senas={a['invalid_signals']} "
                          f"senas={a['senas']}")
            for ev in res["events"]:
                print(f"    EVENT {ev}")

    Path("err_hunt/summary.json").write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"\nTOTAL {time.time()-t0:.0f}s — logs in err_hunt/")


if __name__ == "__main__":
    main()
