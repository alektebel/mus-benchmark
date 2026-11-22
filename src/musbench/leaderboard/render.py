"""Turn a rating into the README block and the animated leaderboard SVG."""
from __future__ import annotations

import html
import re

START = "<!-- leaderboard:start -->"
END = "<!-- leaderboard:end -->"


def _fmt(x: float) -> str:
    return f"{x:+.1f}"


def svg(result: dict, names: dict[str, str], protocol: str) -> str:
    """Bars fade in one by one, best model first. CSS animation only, so it
    plays inside GitHub's <img> sandbox; reduced-motion users get it static."""
    rows = result["rows"]
    w, row_h, top, left, right = 760, 46, 86, 210, 120
    h = top + row_h * len(rows) + 46
    lo = min([0.0] + [r["ci_low"] for r in rows])
    hi = max([0.0] + [r["ci_high"] for r in rows])
    pad = (hi - lo) * 0.06 or 1.0
    lo, hi = lo - pad, hi + pad
    plot_w = w - left - right

    def x(v: float) -> float:
        return left + (v - lo) / (hi - lo) * plot_w

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d">',
           '<title id="t">mus_bench leaderboard</title>',
           '<desc id="d">' + html.escape("; ".join(
               f"#{r['rank']} {names.get(r['model'], r['model'])} {_fmt(r['score'])} "
               f"piedras/hand" for r in rows)) + '</desc>',
           """<style>
.bg{fill:#ffffff} text{fill:#1b1d27} .mut{fill:#6b7086} .grid{stroke:#e4e6ee}
.bar{fill:#8f96b3} .top{fill:#c8102e} .ci{stroke:#1b1d27}
@media (prefers-color-scheme: dark){.bg{fill:#0f111c} text{fill:#eef0f7} .mut{fill:#9aa0b5}
.grid{stroke:#262a3b} .bar{fill:#59607d} .top{fill:#ff4d5e} .ci{stroke:#eef0f7}}
text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.row{animation:in .55s cubic-bezier(.2,.7,.2,1) backwards}
@keyframes in{from{opacity:0;transform:translateX(-14px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion: reduce){.row{animation:none}}
</style>""",
           f'<rect width="{w}" height="{h}" rx="14" class="bg"/>',
           '<text x="24" y="38" font-size="20" font-weight="700">'
           'Who plays mus best?</text>',
           f'<text x="24" y="62" font-size="12.5" class="mut">Score = piedras per hand '
           f'won vs an average opponent · 95% bootstrap interval · protocol '
           f'{html.escape(protocol)} · {result["n_matches"]} matches</text>']
    zero = x(0.0)
    out.append(f'<line x1="{zero:.1f}" y1="{top - 8}" x2="{zero:.1f}" '
               f'y2="{top + row_h * len(rows)}" class="grid" stroke-width="1.5"/>')
    for i, r in enumerate(rows):
        y = top + i * row_h
        cy = y + row_h / 2
        is_top = i == 0
        cls = "top" if is_top else "bar"
        x0, x1 = sorted((zero, x(r["score"])))
        label = names.get(r["model"], r["model"])
        delay = 0.25 + i * 0.45
        weight = "700" if is_top else "500"
        out.append(f'<g class="row" style="animation-delay:{delay:.2f}s">')
        out.append(f'<text x="24" y="{cy + 5:.1f}" font-size="15" '
                   f'font-weight="{weight}">{r["rank"]}. {html.escape(label)}</text>')
        out.append(f'<rect x="{x0:.1f}" y="{cy - 9:.1f}" width="{max(x1 - x0, 1.5):.1f}" '
                   f'height="18" rx="4" class="{cls}"/>')
        out.append(f'<line x1="{x(r["ci_low"]):.1f}" y1="{cy:.1f}" x2="{x(r["ci_high"]):.1f}" '
                   f'y2="{cy:.1f}" class="ci" stroke-width="1.6" opacity=".7"/>')
        for v in (r["ci_low"], r["ci_high"]):
            out.append(f'<line x1="{x(v):.1f}" y1="{cy - 5:.1f}" x2="{x(v):.1f}" '
                       f'y2="{cy + 5:.1f}" class="ci" stroke-width="1.6" opacity=".7"/>')
        out.append(f'<text x="{w - 24}" y="{cy + 5:.1f}" font-size="15" text-anchor="end" '
                   f'font-weight="{weight}">{_fmt(r["score"])}</text>')
        out.append('</g>')
    foot = top + row_h * len(rows) + 28
    note = ("#1 is clear of #2 (intervals do not overlap)" if result.get("top_separated")
            else "#1 is NOT yet separated from #2 — intervals overlap")
    out.append(f'<text x="24" y="{foot}" font-size="12" class="mut">{html.escape(note)}</text>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


def markdown(result: dict, names: dict[str, str], protocol: str,
             svg_path: str = "docs/leaderboard.svg") -> str:
    rows = result["rows"]
    if not rows:
        return f"{START}\n_No rated matches yet ({result.get('error', 'empty ledger')})._\n{END}"
    best = rows[0]
    bname = names.get(best["model"], best["model"])
    verdict = (f"**Best at mus right now: {bname}, {_fmt(best['score'])} piedras/hand** "
               f"(95% CI {_fmt(best['ci_low'])} to {_fmt(best['ci_high'])}; "
               f"ranked #1 in {best['p_best']:.0%} of {result['n_boot']} bootstrap resamples).")
    if not result.get("top_separated"):
        verdict += " Its interval still overlaps #2, so treat the order as provisional."
    lines = [START, "",
             f'<p align="center"><img src="{svg_path}" alt="mus_bench leaderboard" '
             f'width="760"></p>', "", verdict, "",
             "| # | Model | Score | 95% CI | P(#1) | Matches | Opponents | Fallback % † |",
             "|--:|:--|--:|:-:|--:|--:|--:|--:|"]
    for r in rows:
        name = names.get(r["model"], r["model"])
        flag = " ⚠️" if r["opponents"] < 2 else ""
        lines.append(f"| {r['rank']} | {'**' + name + '**' if r['rank'] == 1 else name}{flag} "
                     f"| {_fmt(r['score'])} | {_fmt(r['ci_low'])} … {_fmt(r['ci_high'])} "
                     f"| {r['p_best']:.0%} | {r['matches']} | {r['opponents']} "
                     f"| {r['fallback_rate']:.1%} |")
    lines += ["",
              f"<sub>Score: piedras per hand won against an average opponent of this field, "
              f"from a seat-corrected paired rating over {result['n_matches']} mirrored "
              f"matches (protocol `{protocol}`). "
              + ("⚠️ = rated against a single opponent; its score leans on that "
                 "opponent's rating. " if any(r["opponents"] < 2 for r in rows) else "")
              + "† Share of LLM decisions that fell back to a default action; for the "
              "imported v2 matches this is per match (both teams), not per model. "
              + "Method and how to add a model: [docs/SCORING.md](docs/SCORING.md). "
              "Regenerate with `python -m musbench.leaderboard score`.</sub>",
              "", END]
    return "\n".join(lines)


def splice_readme(readme: str, block: str) -> str:
    if START in readme and END in readme:
        return re.sub(re.escape(START) + r".*?" + re.escape(END),
                      lambda _: block, readme, count=1, flags=re.S)
    # first insert: right under the H1 title
    head, sep, rest = readme.partition("\n")
    return head + "\n\n" + block + "\n" + sep + rest
