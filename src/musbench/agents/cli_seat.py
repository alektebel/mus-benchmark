"""Seats that play through a coding-agent CLI: Claude Code, Codex, Cursor.

Spec forms:
    claude-cli:claude-fable-5-2       ->  claude -p --model ...
    codex-cli:gpt-5.3-codex           ->  codex exec -m ...
    cursor-cli:gpt-5.6-sol-high       ->  cursor-agent -p --model ...
    claude-cli:claude-opus-5-5@low    ->  ... --effort low
    codex-cli:gpt-6-sol@high          ->  ... model_reasoning_effort="high"

The optional @effort suffix pins thinking effort, so the same model can sit on
the roster once per effort level. Without it Claude Code uses its default and
Codex uses CODEX_SEAT_EFFORT.

These reach models with no API key in this environment (the CLIs use the
user's own login). Each decision is one fresh, stateless CLI call run in an
empty temporary directory, with tools disabled or a read-only sandbox, so the
seat sees exactly the prompt and nothing else. The CLIs still wrap the model
in their own agent system prompt (Claude Code accepts --system-prompt and is
replaced; Codex and Cursor are not), so results are labelled by CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from musbench.agents.core import SeatBase
from musbench.live.apifail import LLMCallFailure, MatchTimeout

CLI_TIMEOUT = float(os.environ.get("CLI_SEAT_TIMEOUT", "240"))
CODEX_EFFORT = os.environ.get("CODEX_SEAT_EFFORT", "medium")
SYSTEM = ("You are a mus (Spanish card game) player in a benchmark. Decide "
          "from the information given. Answer only with the requested JSON.")
BACKENDS = ("claude-cli", "codex-cli", "cursor-cli")
EFFORTS = {"claude-cli": ("low", "medium", "high", "xhigh", "max"),
           "codex-cli": ("minimal", "low", "medium", "high", "xhigh")}


def read_reply(text: str) -> tuple[dict | None, str | None]:
    """The reply as one JSON object, or (None, what is wrong with it).

    Only a reply that is exactly one JSON object counts (a ```json fence is
    fine). Two objects, or text after the object ("wait, correction..."),
    is ambiguous: the model is told so and asked again rather than us
    guessing which answer it meant."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    if start == -1:
        return None, "it has no JSON object"
    try:
        obj, end = json.JSONDecoder().raw_decode(raw, start)
    except json.JSONDecodeError as e:
        return None, f"its JSON is malformed ({e.msg})"
    if not isinstance(obj, dict):
        return None, "it is not a JSON object"
    extra = (raw[:start] + raw[end:]).strip()
    if extra:
        return None, "it has text besides the one JSON object, so the answer is ambiguous"
    return obj, None


def menu_schema(n: int) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["choice", "why"],
            "properties": {"choice": {"type": "integer", "minimum": 1, "maximum": n},
                           "why": {"type": "string"}}}


_VERSIONS: dict[str, str] = {}
_VERSION_CMD = {"claude-cli": ["claude", "--version"], "codex-cli": ["codex", "--version"],
                "cursor-cli": ["cursor-agent", "--version"]}


def cli_version(provider: str) -> str:
    """The CLI's own version string, once per process, for reproducibility:
    the CLIs wrap the model in their own prompts, which change by release."""
    if provider not in _VERSIONS:
        try:
            p = subprocess.run(_VERSION_CMD[provider], capture_output=True, text=True,
                               timeout=30)
            _VERSIONS[provider] = (p.stdout or p.stderr).strip().splitlines()[0][:80]
        except Exception:                        # noqa: BLE001 -- best effort
            _VERSIONS[provider] = "unknown"
    return _VERSIONS[provider]


class CliAgent(SeatBase):
    is_llm = True

    def __init__(self, name: str, backend: str, model: str, seat: int, team: int):
        if backend not in BACKENDS:
            raise ValueError(f"unknown CLI backend {backend!r}")
        model, _, effort = model.partition("@")
        if effort and effort not in EFFORTS.get(backend, ()):
            raise ValueError(f"{backend} does not take effort {effort!r} "
                             f"(allowed: {EFFORTS.get(backend, ())})")
        self.name, self.model, self.seat, self.team = name, model, seat, team
        self.effort = effort or (CODEX_EFFORT if backend == "codex-cli" else "")
        self.provider = backend
        self.deadline = None
        self.cost_usd = 0.0
        self._dir = Path(tempfile.mkdtemp(prefix=f"mus-{backend}-"))
        self._env = dict(os.environ)
        if backend == "codex-cli":
            # Fresh CODEX_HOME holding only the login: none of the user's
            # config, hooks or MCP servers reach the seat.
            home = self._dir / "codex-home"
            home.mkdir()
            auth = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
            if auth.exists():
                (home / "auth.json").symlink_to(auth)
            self._env["CODEX_HOME"] = str(home)
        self._init_state()

    def _cmd(self, out_file: Path, schema: dict | None = None) -> list[str]:
        if self.provider == "claude-cli":
            return ["claude", "-p", "--model", self.model, "--output-format", "json",
                    "--tools", "", "--setting-sources", "", "--strict-mcp-config",
                    "--no-session-persistence", "--system-prompt", SYSTEM,
                    *(["--effort", self.effort] if self.effort else []),
                    *(["--json-schema", json.dumps(schema)] if schema else [])]
        if self.provider == "codex-cli":
            extra = []
            if schema:
                sf = self._dir / "schema.json"
                sf.write_text(json.dumps(schema))
                extra = ["--output-schema", str(sf)]
            return ["codex", "exec", "-m", self.model, "-s", "read-only",
                    "-c", f'model_reasoning_effort="{self.effort}"',
                    "--skip-git-repo-check", "--ephemeral", *extra,
                    "-o", str(out_file), "-"]
        return ["cursor-agent", "-p", "--model", self.model, "--output-format", "json",
                "--mode", "ask", "--trust", "--workspace", str(self._dir)]

    def decide(self, prompt: str, schema: dict | None = None) -> dict:
        """One decision. CLI failures (exit, timeout) retry here and finally
        raise LLMCallFailure. A reply the CLI delivered but that is not one
        JSON object is the model's own answer: it comes back as
        {"_error": why, "_raw": reply} so the harness can tell the model
        what was wrong and ask again, like a failed tool call."""
        timeout = CLI_TIMEOUT
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise MatchTimeout("match deadline reached before CLI call")
            timeout = min(timeout, remaining)
        out_file = self._dir / "last.txt"
        text = prompt if self.provider == "claude-cli" else f"{SYSTEM}\n\n{prompt}"
        last_err = None
        for attempt in range(3):
            if attempt:
                time.sleep(10 * attempt)         # ride out DNS / network blips
            try:
                p = subprocess.run(self._cmd(out_file, schema), input=text, cwd=self._dir,
                                   env=self._env, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                last_err = "timeout"
                continue
            if p.returncode != 0:
                last_err = f"exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
                continue
            self.calls += 1
            content = self._content(p.stdout, out_file)
            self.last_io = {"prompt": prompt, "raw": content}
            if isinstance(self._structured, dict):
                return self._structured
            data, err = read_reply(content)
            return data if data is not None else {"_error": err, "_raw": content[:300]}
        self.api_errors += 1
        raise LLMCallFailure(f"{self.name}/{self.provider}:{self.model}: {last_err}")

    def _content(self, stdout: str, out_file: Path) -> str:
        self._structured = None
        if self.provider == "codex-cli":
            return out_file.read_text() if out_file.exists() else stdout
        try:
            d = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout
        u = d.get("usage") or {}
        self.tokens_in += int(u.get("input_tokens") or 0) + int(
            u.get("cache_read_input_tokens") or 0) + int(
            u.get("cache_creation_input_tokens") or 0)
        self.tokens_out += int(u.get("output_tokens") or 0)
        self.cost_usd += float(d.get("total_cost_usd") or 0)
        self._structured = d.get("structured_output")
        return d.get("result") or d.get("text") or ""
