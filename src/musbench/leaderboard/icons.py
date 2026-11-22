"""Provider and model logos for the leaderboard.

Logos live in benchmark/icons/<slug>.svg (LobeHub icons, MIT; TypeSafe's from
the live table). A model gets two: its provider's (Google) and its own model
line's (Gemma). When they are the same mark (DeepSeek) it is drawn once.

`guess(model_id)` fills both from the id so `add` needs no extra flags; a
[[model]] block can override with provider / provider_icon / model_icon.
`fetch(slug)` pulls another LobeHub icon into benchmark/icons/.
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parents[3] / "benchmark" / "icons"
LOBEHUB = "https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.45.0/icons/{}.svg"
SVG_NS = "http://www.w3.org/2000/svg"

# (pattern, provider, provider_icon, model_icon) -- first match wins
FAMILIES = [
    (r"^cursor-cli:(composer|auto)", "Cursor", "cursor", "cursor"),
    (r"gemma", "Google", "google-color", "gemma-color"),
    (r"gemini", "Google", "google-color", "gemini-color"),
    (r"qwen", "Alibaba Cloud", "alibabacloud-color", "qwen-color"),
    (r"glm|chatglm|zhipu", "Zhipu AI", "zhipu-color", "chatglm-color"),
    (r"deepseek", "DeepSeek", "deepseek-color", "deepseek-color"),
    (r"claude|anthropic", "Anthropic", "anthropic", "claude-color"),
    (r"gpt|codex|openai|\bo[1-9]", "OpenAI", "openai", "openai"),
    (r"llama|meta", "Meta", "meta-color", "meta-color"),
    (r"mistral|mixtral|codestral", "Mistral AI", "mistral-color", "mistral-color"),
    (r"kimi|moonshot", "Moonshot AI", "moonshot", "kimi-color"),
    (r"grok|xai", "xAI", "xai", "grok"),
    (r"minimax", "MiniMax", "minimax-color", "minimax-color"),
    (r"nemotron|nvidia", "NVIDIA", "nvidia-color", "nvidia-color"),
    (r"jev|typesafe", "TypeSafe", "typesafe", "typesafe"),
    (r"^(heuristic|random|eps:)", "offline baseline", "", ""),
]


def guess(model_id: str) -> dict:
    for pat, provider, picon, micon in FAMILIES:
        if re.search(pat, model_id, re.I):
            return {"provider": provider, "provider_icon": picon, "model_icon": micon}
    return {"provider": "", "provider_icon": "", "model_icon": ""}


def fetch(slug: str) -> Path:
    """Download a LobeHub icon (e.g. 'perplexity-color') into ICON_DIR."""
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError(f"bad icon slug {slug!r}")
    with urllib.request.urlopen(LOBEHUB.format(slug), timeout=20) as r:
        data = r.read()
    _sanitize(data.decode(), "check")       # refuse anything unsafe up front
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    out = ICON_DIR / f"{slug}.svg"
    out.write_bytes(data)
    return out


_UNSAFE = {"script", "foreignObject", "iframe", "image", "use", "a", "style"}


def _sanitize(svg: str, prefix: str) -> tuple[str, str]:
    """Return (viewBox, inner markup) with unsafe nodes/attrs dropped and ids
    prefixed so two logos in one document never share a gradient id."""
    ET.register_namespace("", SVG_NS)
    root = ET.fromstring(svg)
    view_box = root.get("viewBox", "0 0 24 24")
    root_fill = root.get("fill")

    def clean(el):
        for child in list(el):
            tag = child.tag.split("}")[-1]
            if tag in _UNSAFE or tag == "title":
                el.remove(child)
                continue
            for k in list(child.attrib):
                v = child.attrib[k]
                kl = k.split("}")[-1].lower()
                if kl.startswith("on") or (kl == "href" and not v.startswith("#")):
                    del child.attrib[k]
                elif kl == "id":
                    child.attrib[k] = f"{prefix}-{v}"
                elif "url(#" in v:
                    child.attrib[k] = v.replace("url(#", f"url(#{prefix}-")
            clean(child)

    clean(root)
    inner = "".join(ET.tostring(c, encoding="unicode") for c in root)
    inner = inner.replace(f' xmlns="{SVG_NS}"', "")
    if root_fill:                           # e.g. TypeSafe's gold on the root
        inner = f'<g fill="{root_fill}">{inner}</g>'
    return view_box, inner


def inline(slug: str, x: float, y: float, size: float, uid: str) -> str:
    """A nested <svg> drawing the logo at (x, y). Monochrome logos use
    currentColor, so the `ico` class gives them the theme's text colour."""
    if not slug:
        return ""
    path = ICON_DIR / f"{slug}.svg"
    if not path.exists():
        return ""
    view_box, inner = _sanitize(path.read_text(), f"{uid}-{slug}")
    return (f'<svg x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" '
            f'viewBox="{view_box}" class="ico" fill="currentColor">{inner}</svg>')
