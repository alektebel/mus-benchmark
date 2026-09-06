> Historical legacy-pipeline document. This is not a description or validation
> of the current strict engine; see [README](../README.md).

# mus_bench: Do LLMs Cooperate Under a Limited Attention Budget?
### A 2v2 Spanish card-game benchmark for multi-agent coordination

**Draft outline for an arXiv preprint.** Placeholders in `[...]`. Target venue
class: arXiv cs.AI / cs.CL / cs.MA (benchmark + analysis). This is a *working
skeleton* — the numbers below are from the baseline floor and must be replaced by
the full LLM matrix.

---

## Abstract

We introduce **mus_bench**, a benchmark for evaluating whether large language
models (LLMs) can cooperate as partners in **mus**, a Spanish 2v2 card game, when
their communication is mediated by a **finite attention budget**. Unlike prior
agent benchmarks that assume free, perfect communication, mus_bench makes
signalling *costly*: partner signals are hidden by default and must be decoded by
spending scarce per-hand attention credits, while detecting opponent signalling
competes for the same budget. We evaluate every ordered pair of four LLMs as a
dyad against a fixed reference dyad, scoring the fraction of *vacas* won. We
report a skill floor from non-LLM baselines (random ≈ 0.50; a rule-based
heuristic ≈ 0.55 vs random) and show that the vacas signal is noisy, so
resolving LLM differences requires substantial repetition. We find that
[FINDINGS]. We release the engine, harness, and baselines for reproducibility.

## 1. Introduction

- Motivation: multi-agent LLM systems (agents, tool-use, debate, teams) must
  coordinate under *partial observability* and *bounded attention* — yet most
  benchmarks assume free communication.
- Why mus: a real, culturally-specific, imperfect-information 2v2 game with a
  rich signalling tradition (encoded partner signals) and a compact, deterministic
  rule set. It is a natural testbed for *implicit theory-of-mind* and
  *information-economy* decisions.
- Contributions:
  1. A reproducible mus engine + 2v2 harness with a partial-observability
     signal channel and a per-hand attention budget.
  2. A pairwise cooperation benchmark over LLM dyads vs a reference dyad.
  3. Non-LLM baselines establishing the skill floor.
  4. [Findings + analysis of attention-budget sensitivity.]

## 2. Related Work

- LLM agent benchmarks (e.g., [SWE-bench, GAIA, AgentBench, ...]) — mostly
  single-agent or free-communication multi-agent.
- Multi-agent LLM coordination (e.g., [ChatDev, AutoGen, debate, ...]).
- Imperfect-information game AI (poker, Hanabi, bridge) — Hanabi is the closest
  analogue: cooperative, hidden information, limited communication. Position
  mus_bench relative to Hanabi.
- Attention/cost-aware agents (token budgets, tool budgets) — we extend this to
  *information* budgets.

## 3. The Game and the Benchmark

### 3.1 Mus rules (variant)
- Deck, teams, phases, jugadas, vacas, ordago. (See README + `engine.py`.)
- Explicit statement of the rules *variant* and any deviations from the
  Federación Española de Mus reglamento.

### 3.2 The attention channel
- Signal bus, hidden-by-default partner signals, decode cost, opponent-detect
  cost, per-hand budget. Formalize the budget constraint.

### 3.3 Protocol
- Participants: [4 models]. Reference dyad: [model].
- Every ordered pair of participants forms the benchmark team; the reference
  model fills both opponent seats.
- Metric: vacas win-rate = vacas_A / (vacas_A + vacas_B), averaged over seatings
  and repetitions.
- Reproducibility: seeded RNG, deterministic engine, model IDs + access dates.

## 4. Baselines and Skill Floor

- `RandomAgent`, `HeuristicAgent` (rule-based, no API).
- Floor results (12 hands × 20 matches):

| Matchup                | symmetric win-rate |
|------------------------|--------------------|
| random vs random       | 0.49               |
| heuristic vs heuristic | 0.52               |
| heuristic vs random    | 0.55–0.57          |

- Interpretation: the vacas signal between *reasonable* and *random* play is
  small (~0.05). This bounds the effect size we can expect between LLMs and
  motivates large sample sizes.

## 5. Results

- Vaca win-rate matrix (from `report.py`).
- Ranked cooperation pairs.
- [Statistical analysis: CIs, significance, effect sizes.]
- [Ablations: attention budget on/off; signal channel on/off; decode vs detect
  trade-off.]

## 6. Discussion

- Do LLMs beat the heuristic floor? By how much?
- Does the attention budget change *which* pairs cooperate best?
- Failure modes: malformed JSON, illegal actions, over/under-signalling,
  attention misallocation.
- Limitations: model version drift, rules subset, no human ceiling, small
  sample, API cost.

## 7. Conclusion

- Summary of findings and the benchmark's value as a coordination testbed.
- Future work: self-play Elo, human baseline, budget sensitivity, more models.

## Reproducibility

- Code: [repo URL]. Env: `NAN_API_BASE`, `NAN_API_KEY`.
- Commands: `python run_baseline.py`, `python benchmark.py`, `python report.py`.
- Model snapshots + dates recorded in `results.json`.

## Ethics / Broader Impact

- No human subjects. API costs. Model-version dependence. Cultural note: mus is
  a real game; the benchmark is a *simplified variant* and should not be read as
  authoritative on the real game's rules.

---

## TODO before submission

- [ ] Run the full LLM matrix with enough reps for significance (cost/time).
- [ ] Add a human-expert or strong-agent ceiling.
- [ ] Add self-play Elo ranking (not just fixed reference).
- [ ] Ablations on attention budget and signal channel.
- [ ] Verify rules against the official reglamento; document deviations.
- [ ] Pin model versions; record access dates.
- [ ] Add license, repo, and a proper LaTeX build.
