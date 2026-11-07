"""Live dashboard: serves an HTML page that polls progress.json in real time.

CLI:
  python dashboard.py [--port 8000] [--file progress.json]
"""
from __future__ import annotations

import argparse
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

PROGRESS_FILE = os.environ.get("PROGRESS_FILE", "progress.json")

HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>mus_bench — live</title>
<style>
 body{font-family:system-ui,monospace;background:#0f1115;color:#e6e6e6;margin:0;padding:24px}
 h1{font-size:18px} .card{background:#1a1d24;border:1px solid #2a2e38;border-radius:8px;padding:16px;margin-bottom:16px}
 table{border-collapse:collapse;width:100%} td,th{border:1px solid #2a2e38;padding:6px 10px;font-size:13px;text-align:left}
 .ok{color:#4ade80}.run{color:#facc15}.err{color:#f87171}.que{color:#94a3b8}
 .big{font-size:28px;font-weight:700} #log{max-height:300px;overflow:auto;font-size:12px;white-space:pre-wrap}
 .tag{display:inline-block;background:#2a2e38;border-radius:4px;padding:2px 6px;margin-right:4px;font-size:11px}
</style></head><body>
<h1>mus_bench — live benchmark</h1>
<div class="card"><div id="summary"></div></div>
<div class="card"><h3>Matches</h3><table id="jobs"><thead><tr>
 <th>#</th><th>seed</th><th>status</th><th>hand</th><th>vacas A</th><th>vacas B</th><th>elapsed</th><th>note</th>
</tr></thead><tbody></tbody></table></div>
<div class="card"><h3>Live log</h3><div id="log"></div></div>
<script>
function cell(row, value, cls='') {
  const td = document.createElement('td');
  td.textContent = value ?? '—'; td.className = cls; row.appendChild(td);
}
async function refresh(){
  try {
    const r = await fetch('/progress', {cache:'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const p = await r.json();
    document.getElementById('summary').textContent =
      `Status: ${p.status} · matches ${p.completed||0}/${p.total||0} · hands done ${p.done_hands||0} · vacas A ${p.running_a||0} · vacas B ${p.running_b||0}`;
    const tb = document.querySelector('#jobs tbody'); tb.replaceChildren();
    for(const j of (p.jobs||[])){
      const row = document.createElement('tr');
      const cls = j.status==='done'?'ok':j.status==='running'?'run':j.status==='error'?'err':'que';
      cell(row,j.id); cell(row,j.seed); cell(row,j.status,cls);
      cell(row,`${j.hand||0}/${j.hands}`);
      cell(row,j.vacas_a??j.vacas_llm); cell(row,j.vacas_b??j.vacas_base);
      cell(row,j.elapsed); cell(row,j.msg||''); tb.appendChild(row);
    }
    const el = document.getElementById('log');
    const text = (p.log||[]).slice(-60).join('\\n');
    if(el.textContent!==text){el.textContent=text; el.scrollTop=el.scrollHeight;}
  } catch(error) {
    document.getElementById('summary').textContent = `Progress unavailable: ${error.message}`;
  } finally { setTimeout(refresh, 2000); }
}
refresh();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/progress":
            try:
                with open(PROGRESS_FILE) as f:
                    body = f.read().encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
            except FileNotFoundError:
                body = b'{"status":"no file yet"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    global PROGRESS_FILE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--file", default=os.environ.get("PROGRESS_FILE", "progress.json"))
    args = ap.parse_args()
    PROGRESS_FILE = args.file
    print(f"Dashboard on http://localhost:{args.port}/  (reading {args.file})")
    HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
