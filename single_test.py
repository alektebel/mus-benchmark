"""Single 1-hand test on nan + nvidia only (openrouter dropped)."""
from mus_engine import MusEngine
from run_match_strict import run_match_strict

SPECS = [
    "deepseek-v4-flash",                        # A1 seat0 (nan)
    "heuristic",                                # B1 seat1 (baseline floor)
    "deepseek-v4-flash",                        # A2 seat2 (nan, partner)
    "heuristic",                                # B2 seat3 (baseline floor)
]

def main() -> None:
    res = run_match_strict(MusEngine(), SPECS, hands=1, seed=0, verbose=True)
    print("\n==== RESULT ====")
    print("vacas LLM=%d baseline=%d status=%s" % (res["vacas_a"], res["vacas_b"], res["status"]))
    print("elapsed=%.1fs calls=%d fallbacks=%d/%d" % (
        res["elapsed"], res["usage"]["calls"], res["usage"]["fallbacks"], res["usage"]["turns"]))
    print("tokens_in=%d out=%d reasoning=%d" % (
        res["usage"]["tokens_in"], res["usage"]["tokens_out"], res["usage"]["reasoning"]))


if __name__ == "__main__":
    main()
