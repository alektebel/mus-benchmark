"""README leaderboard panels, drawn as SVG in the llmleaderboard.com style.

`score` writes four images and one Markdown block:

  docs/leaderboard.svg  "Best overall": provider-coloured Elo bars, logo chips
  docs/speed.svg        "Elo vs speed": scatter with a "Most attractive" corner
  docs/heatmap.svg      "Mus heatmap": one tile per skill, in the leader's colour
  docs/skills.svg       "Best models per skill": top-5 cards

GitHub shows SVGs through <img>, which allows CSS (including dark mode and
animation) but no scripts or web fonts, so everything is static markup with
class-based colours. Fills never use CSS variables, so non-browser renderers
(rsvg, previews) draw the same picture.
"""
from __future__ import annotations

import html
import math

from musbench.leaderboard import icons

W = 880
MIN_N = 5            # decisions a model needs before it can lead a skill
FONT = "'Inter Tight','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

STYLE = f"""<style>
text{{font-family:{FONT}}}
.mono{{font-family:{MONO}}}
.card{{fill:#ffffff;stroke:#e5e7e0}} .t{{fill:#181c21}} .m{{fill:#5d646d}} .f{{fill:#737a83}}
.grid{{stroke:#e9ebe4}} .base{{stroke:#9aa0a8}} .soft{{fill:#f6f7f3}} .line{{stroke:#e5e7e0}}
.lime{{fill:#d7f77d}} .limeink{{fill:#2f3d06}} .quad{{fill:#c7ef5c;fill-opacity:.28}}
.chip{{fill:#ffffff;stroke:#e5e7e0}} .ico{{color:#16191d}} .halo{{paint-order:stroke;stroke:#ffffff;stroke-width:4px;stroke-linejoin:round}}
.pill{{fill:#16191d}} .pillt{{fill:#ffffff}}
@media (prefers-color-scheme:dark){{
 .card{{fill:#121518;stroke:#252a30}} .t{{fill:#eceef1}} .m{{fill:#a7aeb7}} .f{{fill:#8b929c}}
 .grid{{stroke:#20252b}} .base{{stroke:#6f7680}} .soft{{fill:#1a1e23}} .line{{stroke:#252a30}}
 .lime{{fill:#c9ef5f}} .limeink{{fill:#1d2604}} .quad{{fill:#c9ef5f;fill-opacity:.10}}
 .halo{{stroke:#121518}} .pill{{fill:#eceef1}} .pillt{{fill:#121518}}}}
.rise{{transform-box:fill-box;transform-origin:50% 100%;animation:rise .7s cubic-bezier(.2,.7,.2,1) backwards}}
.fade{{animation:fade .5s ease-out backwards}}
@keyframes rise{{from{{transform:scaleY(0)}}}}
@keyframes fade{{from{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.rise,.fade{{animation:none}}}}
</style>"""

SKILL_KEYS = {"fold_accuracy": "fold_n", "call_accuracy": "call_n", "bluff_success": "bluff_n",
              "value_rate": "bet_n", "ordago_wins": "ordago_n", "reads": "why_n",
              "partner": "why_n", "lance_Grande": "lance_Grande_n",
              "lance_Chica": "lance_Chica_n", "lance_Pares": "lance_Pares_n",
              "lance_Juego": "lance_Juego_n"}
HARNESS = {"claude-cli": "Claude Code", "codex-cli": "Codex CLI", "cursor-cli": "Cursor CLI"}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def harness(spec: str) -> str:
    head = spec.split(":", 1)[0] if ":" in spec else ""
    if spec in ("heuristic", "random") or spec.startswith("eps:"):
        return "offline"
    return HARNESS.get(head, "API")


def ink(hex_color: str) -> str:
    """Dark text on light fills, white on dark ones (WCAG relative luminance)."""
    n = int(hex_color.lstrip("#"), 16)
    ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255]
    lin = [(c / 255) / 12.92 if c / 255 <= .03928 else (((c / 255) + .055) / 1.055) ** 2.4 for c in ch]
    lum = .2126 * lin[0] + .7152 * lin[1] + .0722 * lin[2]
    return "#15181c" if lum > .3 else "#ffffff"


def _shade(hex_color: str, k: float) -> str:
    """Darken a #rrggbb colour by factor k (0..1)."""
    n = int(hex_color.lstrip("#"), 16)
    r, g, b = (int(((n >> sh) & 255) * k) for sh in (16, 8, 0))
    return f"#{r:02x}{g:02x}{b:02x}"


def _fit(text: str, max_chars: float) -> str:
    m = int(max_chars)
    return text if len(text) <= m else text[:max(m - 1, 1)].rstrip() + "…"


def color(meta: dict) -> str:
    return icons.BRAND.get(meta.get("provider", ""), "#8a8f9e")


def _logo(meta: dict, cx: float, cy: float, size: float, uid: str, chip: str = "circle") -> str:
    slug = meta.get("model_icon") or meta.get("provider_icon")
    if chip == "circle":
        out = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{size / 2 + 4:.1f}" fill="#ffffff"/>'
    else:
        r = size / 2 + 4
        out = (f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" '
               f'rx="6" class="chip"/>')
    if slug:
        out += icons.inline(slug, cx - size / 2, cy - size / 2, size, uid)
    else:
        out += (f'<text x="{cx:.1f}" y="{cy + 4:.1f}" font-size="11" font-weight="700" '
                f'text-anchor="middle" fill="#333">{esc((meta.get("provider") or meta["name"])[:1])}</text>')
    return out


def _card(h: float, title: str, sub: str, pill: str | None = None) -> list[str]:
    out = [f'<rect x=".5" y=".5" width="{W - 1}" height="{h - 1:.0f}" rx="14" class="card"/>',
           f'<text x="24" y="40" font-size="20" font-weight="600" class="t">{esc(title)}</text>',
           f'<text x="24" y="62" font-size="12.5" class="m">{esc(sub)}</text>']
    if pill:
        pw = 14 + 6.6 * len(pill)
        out += [f'<rect x="{W - 24 - pw:.1f}" y="24" width="{pw:.1f}" height="26" rx="8" class="pill"/>',
                f'<text x="{W - 24 - pw / 2:.1f}" y="41" font-size="12" text-anchor="middle" class="pillt">{esc(pill)}</text>']
    return out


def _open(h: float, label: str) -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h:.0f}" '
            f'viewBox="0 0 {W} {h:.0f}" role="img" aria-label="{esc(label)}">', STYLE]


# ------------------------------------------------------------- overall ----
def overall_svg(rows: list[dict], meta: dict, start: float, tag: str) -> str:
    rows = [r for r in rows if r["games"] > 0]
    H, L, R, T, B = 450, 56, 24, 96, 136
    out = _open(H, "Best overall: Elo by model")
    games = rows and max(1, sum(r["games"] for r in rows) // 2)
    out += _card(H, "Best overall",
                 f"Elo from mirrored games between models · everyone started at {start:.0f}",
                 pill=f"tournament {tag}")
    if not rows:
        out.append(f'<text x="24" y="120" font-size="13" class="f">No games yet.</text></svg>')
        return "\n".join(out)
    lo = math.floor((min([start] + [r["elo"] for r in rows]) - 60) / 50) * 50
    hi = math.ceil((max([start] + [r["elo"] for r in rows]) + 30) / 50) * 50
    plot_h = H - T - B

    def y(v):
        return T + plot_h - (v - lo) / (hi - lo) * plot_h

    step_v = 100 if hi - lo > 400 else 50
    lo = math.floor(lo / step_v) * step_v
    hi = math.ceil(hi / step_v) * step_v
    for v in range(int(lo), int(hi) + 1, step_v):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{L - 8}" y="{y(v) + 4:.1f}" font-size="11" text-anchor="end" class="f mono">{v}</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(start):.1f}" y2="{y(start):.1f}" class="base" stroke-dasharray="4 4"/>')
    step = (W - L - R) / len(rows)
    bw = min(56.0, step - 12)
    for i, r in enumerate(rows):
        m = meta[r["model"]]
        cx = L + step * i + step / 2
        top = y(r["elo"])
        delay = .15 + i * .12
        out.append(f'<g><title>{esc(m["name"])}: {r["elo"]:.0f} Elo (95% CI {r["ci_low"]:.0f}–'
                   f'{r["ci_high"]:.0f}), {r["games"]} games, {r["record"]}</title>')
        out.append(f'<rect class="rise" style="animation-delay:{delay:.2f}s" x="{cx - bw / 2:.1f}" '
                   f'y="{top:.1f}" width="{bw:.1f}" height="{T + plot_h - top:.1f}" rx="5" fill="{color(m)}"/>')
        out.append(f'<g class="fade" style="animation-delay:{delay + .35:.2f}s">'
                   f'<text x="{cx:.1f}" y="{top - 8:.1f}" font-size="12.5" font-weight="700" '
                   f'text-anchor="middle" class="t mono">{r["elo"]:.0f}</text>')
        if T + plot_h - top > 44:
            out.append(_logo(m, cx, top + 20, 15, f"ov{i}"))
        out.append('</g>')
        out.append(f'<text transform="translate({cx + 5:.1f},{T + plot_h + 16}) rotate(-38)" '
                   f'font-size="12" text-anchor="end" class="t">{esc(m["name"])}</text></g>')
    out.append(f'<text x="24" y="{H - 16}" font-size="11.5" class="f">{len(rows)} models with games · '
               f'{games} games · dashed line = starting Elo</text>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- speed ----
def speed_svg(rows: list[dict], meta: dict, skills: dict) -> str:
    pts = [(r["model"], r["elo"], skills[r["model"]]["sec_per_move"]) for r in rows
           if r["games"] > 0 and (skills.get(r["model"]) or {}).get("sec_per_move")]
    H, L, R, T, B = 440, 64, 28, 92, 64
    out = _open(H, "Elo against seconds per decision")
    out += _card(H, "Elo vs speed: who plays well, fast",
                 "Fitted Elo against the average seconds a model takes per decision")
    if len(pts) < 2:
        out.append('<text x="24" y="120" font-size="13" class="f">Needs two models with games.</text></svg>')
        return "\n".join(out)
    sx = [p[2] for p in pts]
    lx0, lx1 = math.log10(min(sx) * .8), math.log10(max(sx) * 1.3)
    e0, e1 = min(p[1] for p in pts) - 40, max(p[1] for p in pts) + 40

    def x(v):
        return L + (math.log10(v) - lx0) / (lx1 - lx0) * (W - L - R)

    def y(v):
        return T + (1 - (v - e0) / (e1 - e0)) * (H - T - B)

    def med(a):
        b = sorted(a)
        n = len(b)
        return b[n // 2] if n % 2 else (b[n // 2 - 1] + b[n // 2]) / 2

    ms, me = med(sx), med([p[1] for p in pts])
    out.append(f'<rect x="{L}" y="{T}" width="{x(ms) - L:.1f}" height="{y(me) - T:.1f}" class="quad"/>')
    out.append(f'<text x="{L + 10}" y="{T + 18}" font-size="12" font-weight="600" class="t">Most attractive</text>')
    for t in (0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if lx0 <= math.log10(t) <= lx1:
            out.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{T}" y2="{H - B}" class="grid"/>'
                       f'<text x="{x(t):.1f}" y="{H - B + 16}" font-size="11" text-anchor="middle" class="f mono">{t:g}s</text>')
    v = math.ceil(e0 / 50) * 50
    while v <= e1:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{L - 8}" y="{y(v) + 4:.1f}" font-size="11" text-anchor="end" class="f mono">{v}</text>')
        v += 50
    out.append(f'<line x1="{x(ms):.1f}" x2="{x(ms):.1f}" y1="{T}" y2="{H - B}" class="base" stroke-dasharray="4 4"/>'
               f'<line x1="{L}" x2="{W - R}" y1="{y(me):.1f}" y2="{y(me):.1f}" class="base" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{L}" y="{T - 8}" font-size="11" class="f">Elo · higher is better</text>'
               f'<text x="{(L + W - R) / 2:.0f}" y="{H - 22}" font-size="11" text-anchor="middle" class="f">'
               f'Seconds per decision · log scale · lower is better (CLI seats include start-up)</text>')
    placed, dots, labels = [], [], []
    for mid, e, s in sorted(pts, key=lambda p: (y(p[1]), x(p[2]))):
        m = meta[mid]
        px, py = x(s), y(e)
        right = px + 11 + 6.6 * len(m["name"]) > W - R     # flip only if it would overflow
        ly = py + 4
        while any(abs(qy - ly) < 15 and abs(qx - px) < 150 for qx, qy in placed):
            ly += 15
        placed.append((px, ly))
        lx = px - 11 if right else px + 11
        if abs(ly - py - 4) > 1:
            dots.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{lx:.1f}" y2="{ly - 4:.1f}" class="line"/>')
        dots.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7" fill="{color(m)}" stroke="#ffffff" stroke-width="2">'
                    f'<title>{esc(m["name"])}: {e:.0f} Elo, {s:.1f} s per decision</title></circle>')
        labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" class="t halo" '
                      f'text-anchor="{"end" if right else "start"}">{esc(m["name"])}</text>')
    out += dots + labels + ['</svg>']
    return "\n".join(out) + "\n"


# ------------------------------------------------------------- skills ----
def ranked(skills: dict, key: str, meta: dict) -> list[tuple[str, float, int]]:
    nk = SKILL_KEYS[key]
    out = [(mid, s[key], s.get(nk, 0)) for mid, s in skills.items()
           if mid in meta and s.get(key) is not None and s.get(nk, 0) >= MIN_N]
    return sorted(out, key=lambda t: (-t[1], meta[t[0]]["name"]))


def heatmap_svg(skills: dict, meta: dict, defs: dict) -> str:
    layout = [  # key, col, row, colspan, rowspan  (6 columns)
        ("lance_Grande", 0, 0, 2, 2), ("lance_Chica", 2, 0, 2, 2),
        ("lance_Pares", 4, 0, 2, 1), ("lance_Juego", 4, 1, 2, 1),
        ("fold_accuracy", 0, 2, 1, 1), ("call_accuracy", 1, 2, 1, 1),
        ("bluff_success", 2, 2, 1, 1), ("value_rate", 3, 2, 1, 1), ("ordago_wins", 4, 2, 2, 1),
        ("reads", 0, 3, 3, 1), ("partner", 3, 3, 3, 1)]
    gap, top, rh = 6, 84, 96
    cw = (W - 48 - 5 * gap) / 6
    H = top + 4 * rh + 3 * gap + 44
    out = _open(H, "Mus heatmap: the leader of each skill")
    out += _card(H, "Mus heatmap", "Who leads each part of the game. Tiles take the leader's colour.",
                 pill=f"{len(layout)} skills")
    for i, (key, c, r, cs, rs) in enumerate(layout):
        x0 = 24 + c * (cw + gap)
        y0 = top + r * (rh + gap)
        w = cs * cw + (cs - 1) * gap
        h = rs * rh + (rs - 1) * gap
        lead = ranked(skills, key, meta)
        name = defs[key][0]
        delay = .1 + i * .06
        if not lead:
            out.append(f'<g class="fade" style="animation-delay:{delay:.2f}s"><rect x="{x0:.1f}" y="{y0:.1f}" '
                       f'width="{w:.1f}" height="{h:.1f}" rx="6" class="soft"/>'
                       f'<text x="{x0 + 12:.1f}" y="{y0 + 22:.1f}" font-size="13" font-weight="600" class="f">{esc(name)}</text>'
                       f'<text x="{x0 + 12:.1f}" y="{y0 + h - 14:.1f}" font-size="12" class="f">needs {MIN_N}+ decisions</text></g>')
            continue
        mid, val, n = lead[0]
        col = color(meta[mid])
        txt = ink(col)
        ties = sum(1 for _m, v2, _n in lead if abs(v2 - val) < 1e-9) - 1
        gid = f"hg{i}"
        label = meta[mid]["name"] + (f" + {ties} tied" if ties else "")
        label = _fit(label, (w - 52) / 6.7)
        narrow = w < 200
        out.append(f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
                   f'<stop offset="0" stop-color="{col}"/><stop offset="1" stop-color="{_shade(col, .78)}"/>'
                   f'</linearGradient></defs>')
        out.append(f'<g class="fade" style="animation-delay:{delay:.2f}s">'
                   f'<title>{esc(name)}: {esc(meta[mid]["name"])} {val:.0%} ({n} decisions)</title>'
                   f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" fill="url(#{gid})"/>'
                   f'<text x="{x0 + 12:.1f}" y="{y0 + 22:.1f}" font-size="13" font-weight="600" fill="{txt}">{esc(name)}</text>')
        if narrow:
            out.append(f'<text x="{x0 + 12:.1f}" y="{y0 + 40:.1f}" font-size="12" fill="{txt}" class="mono" '
                       f'opacity=".92">{val:.0%}</text>')
        else:
            out.append(f'<text x="{x0 + w - 12:.1f}" y="{y0 + 22:.1f}" font-size="12" text-anchor="end" '
                       f'fill="{txt}" class="mono" opacity=".92">{val:.0%}</text>')
        out.append(_logo(meta[mid], x0 + 22, y0 + h - 22, 13, f"hm{i}", chip="rect")
                   + f'<text x="{x0 + 40:.1f}" y="{y0 + h - 18:.1f}" font-size="12.5" font-weight="500" '
                   f'fill="{txt}">{esc(label)}</text></g>')
    out.append(f'<text x="24" y="{H - 16:.0f}" font-size="11.5" class="f">Card play, betting and table talk · '
               f'a model needs {MIN_N}+ decisions of a kind to lead it · scored against engine ground truth '
               f'(table talk: from the models\' own reasons)</text>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


def skills_svg(skills: dict, meta: dict, defs: dict) -> str:
    pick = ["fold_accuracy", "call_accuracy", "bluff_success", "value_rate", "reads", "partner"]
    cw, gap, ch, top = (W - 16) / 2, 16, 270, 0
    H = 3 * ch + 2 * gap
    out = _open(H, "Best models per skill")
    for i, key in enumerate(pick):
        col_i, row_i = i % 2, i // 2
        x0 = col_i * (cw + gap)
        y0 = top + row_i * (ch + gap)
        name, _unit, definition = defs[key]
        tag = "from reasons" if key in ("reads", "partner") else "vs ground truth"
        out.append(f'<g class="fade" style="animation-delay:{.1 + i * .1:.2f}s">')
        out.append(f'<rect x="{x0 + .5:.1f}" y="{y0 + .5:.1f}" width="{cw - 1:.1f}" height="{ch - 1}" rx="14" class="card"/>')
        out.append(f'<text x="{x0 + 20:.1f}" y="{y0 + 36:.1f}" font-size="17" font-weight="600" class="t">'
                   f'Best in {esc(name.lower())}</text>')
        pw = 14 + 6.2 * len(tag)
        out.append(f'<rect x="{x0 + cw - 20 - pw:.1f}" y="{y0 + 20:.1f}" width="{pw:.1f}" height="22" rx="7" '
                   f'fill="none" class="line"/><text x="{x0 + cw - 20 - pw / 2:.1f}" y="{y0 + 35:.1f}" '
                   f'font-size="11" text-anchor="middle" class="m">{tag}</text>')
        rows = ranked(skills, key, meta)[:5]
        if not rows:
            out.append(f'<text x="{x0 + 20:.1f}" y="{y0 + 80:.1f}" font-size="12.5" class="f">Not enough decisions yet.</text>')
        for j, (mid, val, n) in enumerate(rows):
            ry = y0 + 66 + j * 36
            first = j == 0
            out.append(f'<rect x="{x0 + 20:.1f}" y="{ry - 12:.1f}" width="24" height="17" rx="4" '
                       f'class="{"lime" if first else "soft"}"/>'
                       f'<text x="{x0 + 32:.1f}" y="{ry + 1:.1f}" font-size="10.5" text-anchor="middle" '
                       f'class="mono {"limeink" if first else "f"}" font-weight="{600 if first else 500}">{j + 1:02d}</text>')
            out.append(_logo(meta[mid], x0 + 62, ry - 4, 12, f"sk{i}{j}", chip="rect"))
            out.append(f'<text x="{x0 + 80:.1f}" y="{ry + 1:.1f}" font-size="13" class="t">{esc(meta[mid]["name"])}'
                       f'<title>{n} decisions</title></text>'
                       f'<text x="{x0 + cw - 20:.1f}" y="{ry + 1:.1f}" font-size="13" font-weight="700" '
                       f'text-anchor="end" class="t mono">{val:.0%}</text>')
            tw = cw - 100
            out.append(f'<rect x="{x0 + 80:.1f}" y="{ry + 9:.1f}" width="{tw:.1f}" height="5" rx="2.5" class="soft"/>'
                       f'<rect x="{x0 + 80:.1f}" y="{ry + 9:.1f}" width="{max(tw * val, 2):.1f}" height="5" rx="2.5" '
                       f'fill="{color(meta[mid])}"/>')
        out.append(f'<text x="{x0 + 20:.1f}" y="{y0 + ch - 18:.1f}" font-size="11.5" class="f">'
                   f'{esc(definition[0].upper() + definition[1:])}.</text></g>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


# ------------------------------------------------------------ markdown ----
def markdown(res: dict, live: dict, meta: dict, skills: dict, cfg: dict, paths: dict,
             start: str, end: str, icon_dir: str = "benchmark/icons") -> str:
    rows = res["rows"]
    if not rows:
        return (f"{start}\n_No games yet in tournament `{cfg.get('tournament')}`: every "
                f"model starts at {cfg['start_elo']:.0f} Elo._\n{end}")
    best = rows[0]
    sep = len(rows) > 1 and best["ci_low"] > rows[1]["ci_high"]
    verdict = (f"**Best at mus right now: {meta[best['model']]['name']}, {best['elo']:.0f} Elo** "
               f"(95% CI {best['ci_low']:.0f}–{best['ci_high']:.0f}; #1 in {best['p_best']:.0%} "
               f"of resamples over {best['games']} games).")
    if not sep:
        verdict += " Its interval still overlaps #2, so the order is provisional."

    def img(key, alt):
        return f'<p align="center"><img src="{paths[key]}" alt="{alt}" width="{W}"></p>'

    def chip(mid, key):
        slug = meta[mid].get(key)
        return (f'<img src="{icon_dir}/{slug}.svg" width="16" height="16" alt=""> '
                if slug else "")

    def pct(mid, k, nk):
        s = skills.get(mid) or {}
        return "—" if s.get(k) is None else f"{s[k]:.0%}"

    lines = [start, "", img("overall", "Best overall: Elo by model"), "", verdict, "",
             img("speed", "Elo against seconds per decision"), "",
             img("heatmap", "Mus heatmap: the leader of each skill"), "",
             img("skills", "Best models per skill"), "",
             "### Model comparison", "",
             "| Model | Provider | Harness | Elo | 95% CI | Games | W-L-D | Piedras/hand | Fold acc. | Call acc. | Bluff rate | s/decision |",
             "|:--|:--|:--|--:|:-:|--:|:-:|--:|--:|--:|--:|--:|"]
    for r in rows:
        mid, m = r["model"], meta[r["model"]]
        s = skills.get(mid) or {}
        sec = s.get("sec_per_move")
        nm = f"**{m['name']}**" if r is best else m["name"]
        lines.append(
            f"| {chip(mid, 'model_icon') or chip(mid, 'provider_icon')}{nm} | {m['provider']} "
            f"| {harness(cfg['models'][mid]['spec'])} | {r['elo']:.0f} | {r['ci_low']:.0f}–{r['ci_high']:.0f} "
            f"| {r['games']} | {r['record']} | {r['per_hand']:+.1f} "
            f"| {pct(mid, 'fold_accuracy', 'fold_n')} | {pct(mid, 'call_accuracy', 'call_n')} "
            f"| {pct(mid, 'bluff_rate', 'bet_n')} | {'—' if not sec else f'{sec:.1f}'} |")
    lines += ["",
              f"<sub>Every model starts at {cfg['start_elo']:.0f}. One game is two matches on the same "
              f"deals with the seats swapped; whoever scores more piedras over the pair wins it. **Elo** "
              f"is a Bradley–Terry fit over all {res['games']} games of tournament "
              f"`{cfg.get('tournament')}`, with bootstrap intervals. **Fold/call accuracy**: share of "
              f"folds that gave up a losing lance, and of calls on a winning one, by the engine's ground "
              f"truth. **Bluff rate**: bets from a bottom-third hand. Every match is replayable from "
              f"`benchmark/replays/`. Method: [docs/SCORING.md](docs/SCORING.md).</sub>", "", end]
    return "\n".join(lines)
