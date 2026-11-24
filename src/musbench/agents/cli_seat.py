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

from musbench.agents.core import SeatBase, _extract_json
from musbench.live.apifail import LLMCallFailure, MatchTimeout

CLI_TIMEOUT = float(os.environ.get("CLI_SEAT_TIMEOUT", "240"))
CODEX_EFFORT = os.environ.get("CODEX_SEAT_EFFORT", "medium")
SYSTEM = ("You are a mus (Spanish card game) player in a benchmark. Decide "
          "from the information given. Answer only with the requested JSON.")
BACKENDS = ("claude-cli", "codex-cli", "cursor-cli")
EFFORTS = {"claude-cli": ("low", "medium", "high", "xhigh", "max"),
           "codex-cli": ("minimal", "low", "medium", "high", "xhigh")}


def last_object(text: str) -> dict | None:
    """The last JSON object in a reply. A model that answers, then writes
    "wait, correction" and answers again means its last answer."""
    dec, found, i = json.JSONDecoder(), None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            found = obj
        i = end
    return found


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

    def _cmd(self, out_file: Path) -> list[str]:
        if self.provider == "claude-cli":
            return ["claude", "-p", "--model", self.model, "--output-format", "json",
                    "--tools", "", "--setting-sources", "", "--strict-mcp-config",
                    "--no-session-persistence", "--system-prompt", SYSTEM,
                    *(["--effort", self.effort] if self.effort else [])]
        if self.provider == "codex-cli":
            return ["codex", "exec", "-m", self.model, "-s", "read-only",
                    "-c", f'model_reasoning_effort="{self.effort}"',
                    "--skip-git-repo-check", "--ephemeral",
                    "-o", str(out_file), "-"]
        return ["cursor-agent", "-p", "--model", self.model, "--output-format", "json",
                "--mode", "ask", "--trust", "--workspace", str(self._dir)]

    def decide(self, prompt: str) -> dict:
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
                p = subprocess.run(self._cmd(out_file), input=text, cwd=self._dir,
                                   env=self._env, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                last_err = "timeout"
                continue
            if p.returncode != 0:
                last_err = f"exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
                continue
            self.calls += 1
            content = self._content(p.stdout, out_file)
            try:
                data = json.loads(_extract_json(content))
            except json.JSONDecodeError:
                data = last_object(content)
            self.last_io = {"prompt": prompt, "raw": content}
            # The CLI worked, so an unreadable reply is the MODEL's answer:
            # hand it back (as no choice) and let the harness re-ask it, then
            # end the match as no_answer. Only CLI failures retry here.
            return data if isinstance(data, dict) else {"_unparsed": content[:300]}
        self.api_errors += 1
        raise LLMCallFailure(f"{self.name}/{self.provider}:{self.model}: {last_err}")

    def _content(self, stdout: str, out_file: Path) -> str:
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
        return d.get("result") or d.get("text") or ""
