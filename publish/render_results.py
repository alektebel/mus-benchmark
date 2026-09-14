#!/usr/bin/env python3
"""Render mus_bench LLM results to a static HTML page for alektebel.github.io.

Reads one or more run directories (each with a summary.json produced by
run_tournament.py) and writes a self-contained page in the site's Nocturne-ish
style. Used by the publish watcher that fires when a tournament finishes.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path


def load_entries(results_dirs: list[Path]) -> list[dict]:
    rows = []
    for d in results_dirs:
        sp = d / "summary.json"
        if not sp.exists():
            continue
        try:
            data = json.loads(sp.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for e in data.get("entries", []):
            m = e.get("metrics") or {}
            rows.append({
                "job": e.get("job", "?"),
                "team_a": e.get("team_a"),
                "team_b": e.get("team_b"),
                "seed": e.get("seed"),
                "status": e.get("status", "?"),
                "vacas_a": m.get("vacas_a"),
                "vacas_b": m.get("vacas_b"),
                "hands": m.get("hand_wins"),
                "calls": m.get("llm_calls"),
                "fallbacks": m.get("fallbacks"),
                "senas": (m.get("senas_published"), m.get("senas_caught"),
                          m.get("senas_missed")),
                "bluffs": m.get("bluffs"),
                "wall": round(e.get("wall") or 0),
            })
    return rows


def leaderboard(rows: list[dict]) -> list[dict]:
    lb: dict[str, dict] = {}

    def key(model):
        return lb.setdefault(model, {"model": model, "matches": 0, "wins": 0,
                                     "losses": 0, "ties": 0, "vacas_for": 0,
                                     "vacas_against": 0, "hands_won": 0,
                                     "hands_lost": 0, "calls": 0,
                                     "fallbacks": 0, "senas_pub": 0,
                                     "senas_caught": 0})

    for r in rows:
        if r["status"] not in ("done", "finished"):
            continue
        for team, model in ((0, r["team_a"]), (1, r["team_b"])):
            if not model:
                continue
            k = key(model)
            k["matches"] += 1
            vf = r["vacas_a"] if team == 0 else r["vacas_b"]
            va = r["vacas_b"] if team == 0 else r["vacas_a"]
            k["vacas_for"] += vf or 0
            k["vacas_against"] += va or 0
            if vf is not None and va is not None:
                if vf > va:
                    k["wins"] += 1
                elif vf < va:
                    k["losses"] += 1
                else:
                    k["ties"] += 1
            if r["hands"] and "-" in r["hands"]:
                hw, hl = (int(x) for x in r["hands"].split("-"))
                k["hands_won"] += hw if team == 0 else hl
                k["hands_lost"] += hl if team == 0 else hw
            k["calls"] += (r["calls"] or 0) // 2
            k["fallbacks"] += (r["fallbacks"] or 0) // 2
            k["senas_pub"] += (r["senas"][0] or 0) // 2
            k["senas_caught"] += (r["senas"][1] or 0) // 2
    out = []
    for k in lb.values():
        k["vaca_diff"] = k["vacas_for"] - k["vacas_against"]
        out.append(k)
    out.sort(key=lambda k: (k["vaca_diff"], k["vacas_for"]), reverse=True)
    return out


def esc(x) -> str:
    return html.escape(str(x)) if x is not None else "—"


def render(rows: list[dict], results_dirs: list[Path], live_url: str = "") -> str:
    lb = leaderboard(rows)
    done = [r for r in rows if r["status"] in ("done", "finished")]
    running = [r for r in rows if r["status"] not in ("done", "finished")]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if live_url:
        view_url = live_url + ("&" if "?" in live_url else "?") + "reveal=all"
        lp = Path(__file__).resolve().parent / "live_lineup.txt"
        lineup = esc(lp.read_text().strip()) if lp.exists() else ""
        lineup_html = f"<b>{lineup}</b> · " if lineup else ""
        live_html = f"""  <div class="card">
    <h2>Mesa en vivo</h2>
    <div class="sub">{lineup_html}Partida LLM en directo sobre el mismo motor y kernel de
    señas; se ven todas las manos, las señas con su significado y los pensamientos en
    tiempo real.
    <a href="{esc(view_url)}" target="_blank" rel="noopener">abrir en pestaña nueva ↗</a></div>
    <div style="position:relative;width:100%;height:780px;border-radius:10px;
    overflow:hidden;border:1px solid var(--divider);background:#0f111c">
      <iframe src="{esc(view_url)}" title="mus en vivo" loading="lazy"
      style="width:100%;height:100%;border:0"></iframe>
    </div>
    <div class="meta" style="margin-top:8px">Enlace de túnel temporal; si la mesa
    deja de cargar, el servidor local o el túnel se han detenido.</div>
  </div>

"""
    else:
        live_html = ""

    lb_rows = "\n".join(
        f"""      <tr>
        <td class="model">{esc(k['model'])}</td>
        <td class="num">{k['matches']}</td>
        <td class="num">{k['wins']}–{k['losses']}–{k['ties']}</td>
        <td class="num strong">{k['vacas_for']}–{k['vacas_against']}</td>
        <td class="num">{k['hands_won']}–{k['hands_lost']}</td>
        <td class="num">{k['senas_pub']}</td>
        <td class="num">{k['senas_caught']}</td>
        <td class="num">{k['fallbacks']}</td>
        <td class="num">{k['calls']}</td>
      </tr>""" for k in lb) or \
        '      <tr><td colspan="9" class="muted">no completed matches yet</td></tr>'

    def match_rows(items):
        out = []
        for r in items:
            sp, sc, sm = r["senas"]
            out.append(f"""      <tr>
        <td class="mono">{esc(r['team_a'])} vs {esc(r['team_b'])}</td>
        <td class="num">{esc(r['seed'])}</td>
        <td class="status {esc(r['status'])}">{esc(r['status'])}</td>
        <td class="num strong">{esc(r['vacas_a'])}–{esc(r['vacas_b'])}</td>
        <td class="num">{esc(r['hands'])}</td>
        <td class="num">{esc(sp)}/{esc(sc)}/{esc(sm)}</td>
        <td class="num">{esc(r['bluffs'])}</td>
        <td class="num">{esc(r['fallbacks'])}</td>
        <td class="num">{esc(r['calls'])}</td>
        <td class="num">{esc(r['wall'])}s</td>
      </tr>""")
        return "\n".join(out)

    done_html = match_rows(done)
    run_html = match_rows(running)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mus_bench · LLM results · Diego Rodríguez Atencia</title>
<meta name="description" content="Live results from mus_bench: two-player LLM teams playing mus under partial observability, with partner-directed señas.">
<link rel="icon" href="data:,">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#161826;--surface:#232532;--text:#e9e9ed;--accent:#9184d9;
--divider:color-mix(in srgb,#e9e9ed 16%,transparent);--muted:#9397ab;
--heading:"Inter",system-ui,sans-serif}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:var(--heading);font-size:14px;line-height:1.5;color:var(--text);
background:radial-gradient(120% 80% at 15% -10%,#1d2036 0%,var(--bg) 55%)}}
a{{color:#b5abfc;text-decoration:none}}a:hover{{color:#e7e5fe}}
.wrap{{max-width:1000px;margin:0 auto;padding:48px 24px}}
.top{{display:flex;gap:16px;align-items:baseline;margin-bottom:8px}}
.eyebrow{{font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:#b5abfc}}
h1{{font-size:clamp(30px,4.5vw,48px);font-weight:500;letter-spacing:-.02em;margin:8px 0 12px}}
p.lede{{color:#cfd3e5;max-width:62ch;font-size:15px}}
.meta{{color:var(--muted);font-size:12px;margin-top:8px}}
.pill{{display:inline-flex;align-items:center;gap:6px;font-size:11px;letter-spacing:.08em;
text-transform:uppercase;padding:4px 10px;border-radius:6px;background:#423a6a;color:#e7e5fe}}
.card{{background:var(--surface);border-radius:14px;padding:22px;margin:28px 0}}
.card h2{{font-size:16px;font-weight:600;margin:0 0 4px}}
.card .sub{{color:var(--muted);font-size:12px;margin-bottom:16px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;font-weight:500;color:var(--muted);font-size:11px;letter-spacing:.06em;
text-transform:uppercase;padding:8px 10px;border-bottom:1px solid var(--divider);white-space:nowrap}}
td{{padding:9px 10px;border-bottom:1px solid color-mix(in srgb,#e9e9ed 7%,transparent)}}
tr:last-child td{{border-bottom:none}}
.num{{text-align:right;font-variant-numeric:tabular-nums;font-family:ui-monospace,monospace}}
.model,.mono{{font-family:ui-monospace,monospace;font-size:12px}}
.strong{{font-weight:600;color:#e7e5fe}}
.status{{font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
.status.done,.status.finished{{color:#9ee6b4}}
.status.degraded,.status.failed{{color:#c98a8a}}
.status.running,.status.queued{{color:#b5abfc}}
.muted{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-top:6px}}
.stat{{background:color-mix(in srgb,#e9e9ed 4%,transparent);border-radius:10px;padding:14px}}
.stat .k{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}
.stat .v{{font-size:22px;font-weight:600;margin-top:4px}}
footer{{border-top:1px solid var(--divider);margin-top:40px;padding-top:18px;color:var(--muted);font-size:12px}}
code{{font-family:ui-monospace,monospace;font-size:12px;color:#cfd3e5}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <span class="pill">mus_bench</span>
    <span class="meta">LLM cooperation under partial observability</span>
  </div>
  <h1>mus contra la máquina — LLM benchmark</h1>
  <p class="lede">Two frontier models each fill a full mus team (seats 0+2 vs 1+3). Partners
  cannot see each other's cards; the only cooperation channel is <em>señas</em> —
  partner-directed, TTL-expiring gestures. Vacas are games to 40 points. Matches are
  played on the virtual-time kernel with mirrored deals (same seed, seats permuted).</p>
  <div class="meta">Last updated {now} · sources: {esc(', '.join(str(d) for d in results_dirs))}</div>

{live_html}  <div class="card">
    <h2>Leaderboard</h2>
    <div class="sub">Completed, publishable matches only (≥50 real LLM calls, ≤15% fallback).</div>
    <div class="grid">
      <div class="stat"><div class="k">completed</div><div class="v">{len(done)}</div></div>
      <div class="stat"><div class="k">in progress</div><div class="v">{len(running)}</div></div>
      <div class="stat"><div class="k">total matches</div><div class="v">{len(rows)}</div></div>
    </div>
    <table style="margin-top:18px">
      <thead><tr>
        <th>model</th><th class="num">M</th><th class="num">W–L–T</th>
        <th class="num">vacas</th><th class="num">hands</th><th class="num">señas pub</th>
        <th class="num">caught</th><th class="num">fallbacks</th><th class="num">calls</th>
      </tr></thead>
      <tbody>
{lb_rows}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Completed matches</h2>
    <div class="sub">vacas A–B · hands · señas published/caught/missed · bluffs · fallbacks · calls</div>
    <table>
      <thead><tr>
        <th>match</th><th class="num">seed</th><th>status</th><th class="num">vacas</th>
        <th class="num">hands</th><th class="num">señas p/c/m</th><th class="num">bluffs</th>
        <th class="num">fb</th><th class="num">calls</th><th class="num">wall</th>
      </tr></thead>
      <tbody>
{done_html}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>In progress / queued</h2>
    <table>
      <thead><tr>
        <th>match</th><th class="num">seed</th><th>status</th><th class="num">vacas</th>
        <th class="num">hands</th><th class="num">señas p/c/m</th><th class="num">bluffs</th>
        <th class="num">fb</th><th class="num">calls</th><th class="num">wall</th>
      </tr></thead>
      <tbody>
{run_html or '      <tr><td colspan="10" class="muted">none</td></tr>'}
      </tbody>
    </table>
  </div>

  <footer>
    Generated automatically from <code>summary.json</code> by <code>mus_bench/publish/render_results.py</code>.
    Vacas are games to 40 points. Señas are private to the partner; opponents never see them.
    <a href="index.html">← back to the table</a> · <a href="../index.html">home</a>
  </footer>
</div>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--live-url", default=None,
                    help="public URL of the live table; default reads "
                         "publish/live_url.txt next to this script")
    args = ap.parse_args()
    live_url = args.live_url
    if live_url is None:
        p = Path(__file__).resolve().parent / "live_url.txt"
        live_url = p.read_text().strip() if p.exists() else ""
    dirs = [Path(d) for d in args.results_dir]
    rows = load_entries(dirs)
    Path(args.out).write_text(render(rows, dirs, live_url), encoding="utf-8")
    print(f"rendered {len(rows)} match rows (live_url={live_url or 'none'}) -> {args.out}")


if __name__ == "__main__":
    main()
