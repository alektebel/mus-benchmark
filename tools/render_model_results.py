"""One-image summary of mus_bench model results: wins, bluffs, highlights.

Sources:
  - Published leaderboard (alektebel.github.io/mus/benchmark.html, rendered from
    results/tournament*/summary.json): 6 completed publishable matches, both
    seatings, pooled per model.
  - Seed-6 live trace (publish/web/traces/seed6.json): the only artifact with
    per-agent bluff attribution.
  - docs/results-seed6-live.md: match highlights.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import json
import textwrap

GLM, DS = "glm5.3-flash", "deepseek-v4-flash"
C_GLM, C_DS = "#7c5cff", "#ff9f43"
C_GLM_L, C_DS_L = "#b8a6ff", "#ffd9a8"

# ---------------------------------------------------------------- data ----
# 6 completed publishable matches (published page)
matches = [  # (label, vacas_a, vacas_b, a_team, seed)
    ("tournament", 1, 0, DS, 0),
    ("tournament", 0, 1, GLM, 1),
    ("mirror", 1, 1, DS, 7),
    ("mirror", 0, 1, GLM, 6),
    ("mirror", 1, 1, DS, 6),
    ("replication", 0, 2, DS, 6),
]
lb = {GLM: dict(M=6, W=1, L=3, T=2, vf=4, va=5, hw=29, hl=28),
      DS:  dict(M=6, W=3, L=1, T=2, vf=5, va=4, hw=28, hl=29)}

# seed-6 live match: per-model señas + bluffs (from trace agents)
sena = {GLM: dict(pub=59, caught=47, bluffs=0),
        DS:  dict(pub=38, caught=28, bluffs=2)}
live = dict(vacas=(2, 2), piedras=(116, 100), hand_wins=(6, 10), hands=16)

# per-match bluff totals from the page (match order above)
bluffs_per_match = [15, 13, 5, 2, 0, 0]
total_pub = sum(m[2] + m[1] for m in matches)  # vacas col is not señas; use live+page pub
# señas published per match from the page: 73, 38, 77, 74, 90, 83
senas_pub_per_match = [73, 38, 77, 74, 90, 83]
pool_pub = sum(senas_pub_per_match)
pool_bluffs = sum(bluffs_per_match)

models = [DS, GLM]
cols = {DS: C_DS, GLM: C_GLM}
cols_l = {DS: C_DS_L, GLM: C_GLM_L}

fig = plt.figure(figsize=(15.5, 10.5), facecolor="#0f111c")
fig.suptitle("mus_bench — model results", color="white", fontsize=21,
             fontweight="bold", y=0.975)
fig.text(0.5, 0.945, "6 completed publishable matches (both seatings, 10 hands each)"
         " + the seed-6 live match (timed out at 16/40 — shown separately)",
         ha="center", color="#9aa0b5", fontsize=10.5)

gs = fig.add_gridspec(3, 3, hspace=0.52, wspace=0.3,
                      left=0.06, right=0.97, top=0.88, bottom=0.06)

def style(ax, title):
    ax.set_facecolor("#171a28")
    ax.set_title(title, color="white", fontsize=12, fontweight="bold", pad=10)
    ax.tick_params(colors="#c7ccdd", labelsize=10)
    for s in ax.spines.values():
        s.set_color("#2a2e42")
    ax.grid(axis="y", color="#232741", lw=0.7)

# ------------------------------------------------ 1. match win-rate ----
ax = fig.add_subplot(gs[0, 0])
style(ax, "Match wins (6 publishable)")
w = [lb[m]["W"] for m in models]
l = [lb[m]["L"] for m in models]
t = [lb[m]["T"] for m in models]
x = range(len(models))
ax.bar(x, w, 0.55, color=[cols[m] for m in models], label="wins")
ax.bar(x, l, 0.55, bottom=w, color=[cols_l[m] for m in models], label="losses")
for i, m in enumerate(models):
    ax.text(i, lb[m]["W"] + lb[m]["L"] + 0.12,
            f"{lb[m]['W']}W–{lb[m]['L']}L–{lb[m]['T']}T",
            ha="center", color="white", fontsize=11, fontweight="bold")
ax.set_xticks(x, models, fontsize=10)
ax.set_ylim(0, 4.6)
ax.set_yticks(range(5))
ax.legend(facecolor="#171a28", edgecolor="#2a2e42", labelcolor="#c7ccdd",
          fontsize=9, loc="upper left")

# ------------------------------------------------ 2. vaca share ----
ax = fig.add_subplot(gs[0, 1])
style(ax, "Vaca share (for / for+against)")
share = [lb[m]["vf"] / (lb[m]["vf"] + lb[m]["va"]) for m in models]
b = ax.bar(range(2), [s * 100 for s in share], 0.55,
           color=[cols[m] for m in models])
ax.axhline(50, color="#e05c5c", ls="--", lw=1.2)
ax.text(1.42, 50.8, "even", color="#e05c5c", fontsize=8.5)
for i, s in enumerate(share):
    ax.text(i, s * 100 + 1.2, f"{s*100:.1f}%", ha="center", color="white",
            fontsize=12, fontweight="bold")
ax.set_xticks(range(2), models)
ax.set_ylim(0, 66)
ax.set_ylabel("% of vacas won", color="#c7ccdd", fontsize=9)

# ------------------------------------------------ 3. hand wins ----
ax = fig.add_subplot(gs[0, 2])
style(ax, "Hand wins (28 hands)")
hw = [lb[m]["hw"] for m in models]
ax.bar(range(2), hw, 0.55, color=[cols[m] for m in models])
for i, v in enumerate(hw):
    ax.text(i, v + 0.4, str(v), ha="center", color="white",
            fontsize=12, fontweight="bold")
ax.set_xticks(range(2), models)
ax.set_ylim(0, 34)
ax.text(0.5, 32.5, "effectively even — vacas decide, not hands",
        ha="center", color="#9aa0b5", fontsize=8.5, style="italic")

# --------------------------------- 4. bluff rate (seed-6, per model) ----
ax = fig.add_subplot(gs[1, 0])
style(ax, "False-seña rate — seed-6 live only")
rates = [sena[m]["bluffs"] / sena[m]["pub"] * 100 for m in models]
ax.bar(range(2), rates, 0.55, color=[cols[m] for m in models])
for i, m in enumerate(models):
    ax.text(i, rates[i] + 0.22,
            f"{sena[m]['bluffs']}/{sena[m]['pub']}  ({rates[i]:.1f}%)",
            ha="center", color="white", fontsize=10.5, fontweight="bold")
ax.set_xticks(range(2), models)
ax.set_ylim(0, 7)
ax.text(0.5, 6.4, "both DeepSeek bluffs = honest miscounts (hand 13, \"2 aces\" "
        "while holding 3)\nGLM: 0 false gestures in 59", ha="center",
        color="#9aa0b5", fontsize=8, style="italic")

# --------------------------------- 5. pooled bluffs (6 matches) ----
ax = fig.add_subplot(gs[1, 1])
style(ax, "False señas pooled — 6 matches")
ax.bar([0], [pool_bluffs], 0.4, color="#e05c5c")
ax.text(0, pool_bluffs + 0.5, f"{pool_bluffs} / {pool_pub} published "
        f"({pool_bluffs/pool_pub*100:.1f}%)", ha="center", color="white",
        fontsize=11, fontweight="bold")
ax.set_xticks([0], ["all models pooled"], fontsize=10)
ax.set_ylim(0, 21)
ax.text(0, 18.6, "per-team split not recoverable:\nsummary.json files only existed "
        "on the machine\nthat ran the tournaments", ha="center",
        color="#9aa0b5", fontsize=8, style="italic")

# --------------------------------- 6. seña catch rate ----
ax = fig.add_subplot(gs[1, 2])
style(ax, "Seña catch rate (per match)")
rates = [63/73, 26/38, 58/77, 60/74, 68/90, 68/83, 75/97]
labels = ["t0", "t1", "m7", "m6", "m6", "r6", "live"]
barcols = [C_DS, C_GLM, C_DS, C_GLM, C_DS, C_DS, C_GLM]
ax.bar(range(len(rates)), [r * 100 for r in rates], 0.6, color=barcols)
ax.axhspan(68, 86, color="#2a2e42", alpha=0.4, zorder=0)
ax.text(5.95, 77, "68–86%\nreproducible band", color="#9aa0b5", fontsize=7.5,
        va="center", ha="right")
ax.set_xticks(range(len(rates)), labels)
ax.set_ylim(0, 100)

# ------------------------------------------------ 7. highlights ----
ax = fig.add_subplot(gs[2, :])
ax.axis("off")
ax.set_facecolor("#0f111c")
box = FancyBboxPatch((0.005, 0.02), 0.99, 0.96, boxstyle="round,pad=0.012",
                     transform=ax.transAxes, fc="#171a28", ec="#2a2e42", lw=1)
ax.add_patch(box)
ax.text(0.015, 0.87, "Highlights", color="white", fontsize=13,
        fontweight="bold", transform=ax.transAxes)
hl = [
    ("Hand 1, seed-6 live — the órdago read",
     "DeepSeek shoved all-in on Juego; GLM seat 2 accepted a mediocre hand because its "
     "partner's caught wink (\"I hold 31\") + the mano tiebreak made the worst case a tie. "
     "Engine ground truth: Juego = tie. GLM won the vaca + 51 piedras — 44% of all "
     "piedras in the match, from one audited decision chain: seña → caught → cited → all-in → confirmed."),
    ("Seña channel physics",
     "77.3% caught in the live match; every run in the repo lands 68–86%. ~a quarter of "
     "gestures are lost to timing alone — the channel is lossy by design, in every configuration."),
    ("Honesty asymmetry (seed 6)",
     "GLM: 59 gestures, 0 false. DeepSeek: 38 gestures, 2 false — both hand-13 "
     "miscounts (dos counts as as), not bluffs. No deliberate deception occurred."),
    ("Operational confound",
     "GLM made 472 API calls vs DeepSeek's 240 (1.97×) with 71 API errors and 4 of 5 "
     "forced fallbacks; 98% of output tokens were reasoning. The live match timed out at 16/40 hands."),
    ("Caveat",
     "6 matches on 10-hand deals, where one hand routinely decides. DeepSeek leads "
     "3–1–2 but docs/results-seed6-live.md: any ranking drawn from this can invert on the next seed."),
]
y = 0.70
for head, body in hl:
    ax.text(0.025, y, "▸ " + head, color="#ffd9a8",
            fontsize=10.5, fontweight="bold", transform=ax.transAxes)
    body_w = "\n".join(textwrap.wrap(body, 148))
    ax.text(0.045, y - 0.115, body_w, color="#c7ccdd", fontsize=9,
            transform=ax.transAxes)
    y -= 0.175

fig.text(0.985, 0.012,
         "sources: published leaderboard (results/tournament*/summary.json), "
         "publish/web/traces/seed6.json, docs/results-seed6-live.md",
         ha="right", color="#565b73", fontsize=7.5)

out = "docs/model-results.png"
fig.savefig(out, dpi=140, facecolor="#0f111c")
print("wrote", out)
