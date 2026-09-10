"""Live mus table: play against LLM seats in your browser, senas included.

Same strict, turn-gated engine and kernel sena bus as the benchmark
(`mus_engine.py`, `virtual_kernel.py`), plus HUMAN seats driven over HTTP:

  * one game thread owns the engine; decisions stay sequential (one API call
    per LLM decision, baseline policies act offline, humans act from the UI);
  * humans gesture like at a real table: pick a reglamentaria sena at any
    time -- it is addressed to your partner and reaches them at their NEXT
    decision window unless the TTL expires first (batched kernel delivery);
  * senas are partner-directed and private: only sender and addressee see
    WHICH gesture was made; everyone else only learns THAT one was made;
  * opponents' hands and every seat's private thoughts are revealed only when
    a hand ends (post-hand review), never during play;
  * the engine stays the sole authority on legality: false declarations are
    rejected, envites follow the named-bet protocol, ordago compares the
    whole game, vaca = 40 piedras. Nothing about the outcome is forced.

CLI:
  python live_server.py --port 8123 \
      --seats human,glm5.3-flash,deepseek-v4-flash,heuristic --hands 12
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import queue
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from random import Random
from urllib.parse import parse_qs, urlparse

from mus_engine import MusEngine, Phase, IllegalAction, TEAM_OF, LANCE_NAMES
from groupchat import Channels
from prompt_builder import build_prompt, redact_card_talk
from agents import _make_agent, _default_legal, SeatBase
from senas import SENAS, is_valid_sena, sena_truthful
from signal_bus import SignalBus
from signal_manager import (SignalManager, partner_of, silent_policy,
                            DEFAULT_TTL)
from virtual_kernel import Kernel
from apifail import (LLMCallFailure, FatalAPIError, MatchTimeout,
                     TurnLimitExceeded, MAX_TURNS_PER_HAND)
from bench_results import aggregate_results
from live_ui import INDEX_HTML

MAX_REJECT_RETRIES = int(os.environ.get("MAX_REJECT_RETRIES", "4"))
HUMAN_TURN_TIMEOUT = float(os.environ.get("HUMAN_TURN_TIMEOUT", "300"))
RESULTS_DIR = os.environ.get("MUS_RESULTS_DIR", "results")
CARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "cards")
CARD_FILE_RE = re.compile(r"^card_(?:back|[a-z]+_\d{2})\.svg$")
ALLOW_SEÑA_BLUFFS = os.environ.get("ALLOW_SEÑA_BLUFFS", "1").strip().lower() \
    in ("1", "true", "yes")


class HumanSeat(SeatBase):
    """A seat played from the browser; actions arrive on an inbox queue."""

    is_llm = False

    def __init__(self, name: str, seat: int, team: int):
        self.name, self.seat, self.team = name, seat, team
        self.model = "human"
        self.token = secrets.token_urlsafe(16)
        self.inbox: queue.Queue = queue.Queue()
        self.invalid_policies = 0
        self._init_state()

    def decide(self, prompt: str) -> dict:  # pragma: no cover - parity only
        raise NotImplementedError


def _make_agent_or_human(spec: str, seat: int, seed: int = 0):
    if str(spec).strip().lower() == "human":
        return HumanSeat(f"Humano{seat + 1}", seat, TEAM_OF[seat])
    return _make_agent(spec, seat, TEAM_OF[seat], seed)


class LiveGame:
    """One match on one engine, kernel sena layer, human seats allowed."""

    def __init__(self, specs: list[str], hands: int = 12, seed: int = 0):
        if len(specs) != 4 or any(not s for s in specs):
            raise ValueError("exactly four non-empty seat specs are required")
        self.specs = list(specs)
        self.hands = hands
        self.seed = seed
        self.engine = MusEngine(rng=Random(seed))
        self.agents = [_make_agent_or_human(s, i, seed)
                       for i, s in enumerate(specs)]
        self.human_agents = [a for a in self.agents
                             if isinstance(a, HumanSeat)]
        self.tokens = {a.token: a.seat for a in self.human_agents}
        self.procs = [SignalManager(seat=a.seat, policy=silent_policy(),
                                    allow_bluffs=ALLOW_SEÑA_BLUFFS)
                      for a in self.agents]
        self.ch = Channels()
        self.bus = SignalBus()
        self.kernel = Kernel(rng=Random(seed + 1))
        self.version = 0
        self.events: list[dict] = []
        self._event_seq = 0
        self.history: list[dict] = []
        self.reveal: dict | None = None
        self.pending_human: dict | None = None
        self.match_status = "running"
        self.error: str | None = None
        self.stats = {"turns": 0, "llm_turns": 0, "fallbacks": 0}
        self.thinking_seat: int | None = None
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None
        self.hands_played = 0
        self.last_delivered: list = []
        self.human_error: dict[int, str] = {}

    # ------------- versioning & event feed -------------
    def touch(self):
        self.version += 1

    def _event(self, kind: str, text: str, seat: int | None = None,
               to_seat: int | None = None, gesture: str | None = None):
        self._event_seq += 1
        self.events.append({"i": self._event_seq, "hand": self.hands_played,
                            "kind": kind, "text": text, "seat": seat,
                            "to_seat": to_seat, "gesture": gesture,
                            "t": round(self.kernel.now, 2)})
        if len(self.events) > 600:
            self.events = self.events[-400:]

    # ------------- sena publishing -------------
    def _publish_sena(self, from_seat: int, gesture: str, hand) -> bool:
        """One-shot gesture at the current virtual time, partner-directed."""
        gesture = str(gesture).strip().lower()
        if not is_valid_sena(gesture):
            return False
        agent = self.agents[from_seat]
        truthful = sena_truthful(gesture, hand, self.engine)
        agent.senas_log.append((gesture, truthful))
        if not truthful and not ALLOW_SEÑA_BLUFFS:
            agent.invalid_signals += 1
            self._event("sena_rejected",
                        "seña falsa rechazada: no encaja con tu mano",
                        seat=from_seat)
            self.touch()
            return False
        if not truthful:
            agent.bluffs += 1
        if self.bus.gesture_live(from_seat, gesture, self.kernel.now):
            self._event("sena_note",
                        "tu compañero ya tiene esa seña en curso",
                        seat=from_seat)
            return True
        self.procs[from_seat].published += 1
        self.bus.publish(from_seat, partner_of(from_seat), gesture,
                         self.kernel.now, DEFAULT_TTL, truthful)
        self._event("sena", "hizo una seña para su compañero", seat=from_seat,
                    to_seat=partner_of(from_seat), gesture=gesture)
        self.touch()
        return True

    # ------------- accepted-action side effects -------------
    def _emit(self, agent, action: dict, hand) -> None:
        msg = action.get("message")
        if isinstance(msg, str) and msg.strip():
            original = " ".join(msg.split()[:20])[:120]
            clean = redact_card_talk(original)
            if clean != original:
                agent.redactions += 1
                self._event("chat_redacted",
                            f"{agent.name}: (mensaje con cartas, censurado)",
                            seat=agent.seat)
            self.ch.say_public(agent.seat, agent.name, clean)
            self._event("chat", f"{agent.name}: \"{clean}\"", seat=agent.seat)
        thought = action.get("thought")
        if isinstance(thought, str) and thought.strip():
            agent.thoughts.append(thought.strip())
        pol = action.get("signal_policy")
        if isinstance(pol, dict):
            if self.procs[agent.seat].install_policy(pol):
                self._event("policy", f"{agent.name} declaró política de "
                                      f"señas ({len(pol.get('rules', []))} reglas)",
                            seat=agent.seat)
            else:
                agent.invalid_policies += 1
                self._event("policy", f"{agent.name}: política de señas "
                                      f"inválida (rechazada)", seat=agent.seat)
        sig = action.get("signal")
        if isinstance(sig, dict):
            sig = sig.get("text") or sig.get("gesture")
        if isinstance(sig, str) and sig.strip():
            if not self._publish_sena(agent.seat, sig, hand):
                agent.invalid_signals += 1

    # ------------- turns -------------
    def _llm_turn(self, agent, hand) -> dict:
        legal = self.engine.legal_actions(agent.seat)
        prompt = build_prompt(agent, self.engine, self.ch, legal,
                              delivered=self.last_delivered)
        last_error = None
        for attempt in range(MAX_REJECT_RETRIES):
            retry_prompt = prompt
            if last_error:
                retry_prompt += (f"\nYour last action was REJECTED: "
                                 f"{last_error}. Return a legal action.")
            try:
                action = agent.decide(retry_prompt)
            except (LLMCallFailure, FatalAPIError, MatchTimeout) as e:
                agent.api_errors += 1
                self._event("api_error",
                            f"{agent.name} ({agent.model}): error de API "
                            f"({type(e).__name__}) -> acción legal por defecto",
                            seat=agent.seat)
                return self._fallback(agent, _default_legal(self.engine,
                                                            agent.seat))
            try:
                self.engine.apply(agent.seat, action)
                self._emit(agent, action, hand)
                return action
            except IllegalAction as e:
                last_error = str(e)
                agent.rejections += 1
                self._event("rejected",
                            f"{agent.name}: acción rechazada ({e})",
                            seat=agent.seat)
                self.touch()
        return self._fallback(agent, _default_legal(self.engine, agent.seat))

    def _fallback(self, agent, action: dict) -> dict:
        agent.fallbacks += 1
        self.stats["fallbacks"] += 1
        self.engine.apply(agent.seat, action)
        self._event("fallback",
                    f"{agent.name}: acción legal por defecto", seat=agent.seat)
        return action

    def _human_turn(self, agent: HumanSeat, hand) -> None:
        seat = agent.seat
        legal = self.engine.legal_actions(seat)
        error = self.human_error.pop(seat, None)
        self.pending_human = {"seat": seat, "legal": legal, "error": error}
        self.touch()
        deadline = time.monotonic() + HUMAN_TURN_TIMEOUT
        while True:
            try:
                item = agent.inbox.get(timeout=0.5)
            except queue.Empty:
                if self.stopped.is_set():
                    self._default_now(agent)
                    return
                if time.monotonic() > deadline:
                    agent.fallbacks += 1
                    self.stats["fallbacks"] += 1
                    self._event("timeout",
                                f"{agent.name} tardó demasiado -> acción legal "
                                f"por defecto", seat=seat)
                    self._default_now(agent)
                    return
                continue
            if item.get("action") == "__default__":
                agent.fallbacks += 1
                self.stats["fallbacks"] += 1
                self._default_now(agent)
                return
            try:
                self.engine.apply(seat, item)
                self._emit(agent, item, hand)
                return
            except IllegalAction as e:
                agent.rejections += 1
                self.human_error[seat] = str(e)
                self._event("rejected",
                            f"{agent.name}: acción rechazada ({e})", seat=seat)
                self.pending_human = {"seat": seat,
                                      "legal": self.engine.legal_actions(seat),
                                      "error": str(e)}
                self.touch()

    def _default_now(self, agent):
        try:
            action = _default_legal(self.engine, agent.seat)
            self.engine.apply(agent.seat, action)
            self._emit(agent, action, list(self.engine.hands[agent.seat]))
        except Exception as e:  # noqa: BLE001
            self.match_status = "error"
            self.error = f"{type(e).__name__}: {e}"
            self._event("error", f"error aplicando acción: {e}")

    # ------------- main loop -------------
    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True,
                                       name="live-game")
        self.thread.start()

    def stop(self):
        self.stopped.set()
        for a in self.human_agents:
            a.inbox.put({"action": "__stop__"})
        if self.thread is not None:
            self.thread.join(timeout=5)

    def run(self):
        try:
            self._run_match()
        except (TurnLimitExceeded, MatchTimeout) as e:
            self.match_status = "error"
            self.error = str(e)
            self._event("error", f"partida abortada: {e}")
            self.touch()
        except Exception as e:  # noqa: BLE001 -- the table must not die silently
            self.match_status = "error"
            self.error = f"{type(e).__name__}: {e}"
            self._event("error", f"error inesperado: {self.error}")
            self.touch()

    def _run_match(self):
        self._event("match", f"Nueva partida a {self.hands} manos (seed "
                             f"{self.seed}). Equipo A = asientos 0 y 2 · "
                             f"Equipo B = asientos 1 y 3.")
        self.touch()
        for h in range(self.hands):
            if self.stopped.is_set():
                self.match_status = "stopped"
                self.touch()
                return
            self.play_hand(h + 1)
            if self.match_status == "error":
                return
        self.match_status = "finished"
        self._event("match_end",
                    f"Fin de la partida: vacas {self.engine.vacas_a}"
                    f"-{self.engine.vacas_b}.")
        self.touch()

    def play_hand(self, hand_no: int):
        engine = self.engine
        self.hands_played = hand_no
        self.human_error = {}
        self.last_delivered = []
        self.reveal = None
        v_a0, v_b0 = engine.vacas_a, engine.vacas_b
        engine.deal()
        self.ch.clear()
        self.bus.clear()
        for a in self.agents:
            a.budget.reset()
            a.signals_read = 0
            a.want_signals = False
        self._event("hand_start",
                    f"Mano {hand_no}/{self.hands} · mano (primer hablante): "
                    f"asiento {engine.mano}")
        self.touch()
        turns = 0
        while engine.phase != Phase.DONE:
            if self.stopped.is_set():
                self.match_status = "stopped"
                self.touch()
                return
            turns += 1
            if turns > MAX_TURNS_PER_HAND:
                raise TurnLimitExceeded(
                    f"la mano superó {MAX_TURNS_PER_HAND} turnos")
            self._step()
        self._finish_hand(v_a0, v_b0)

    def _step(self):
        engine = self.engine
        seat = engine.current_seat
        agent = self.agents[seat]
        t0 = self.kernel.now
        window = self.kernel.window_for(engine.phase)
        # kernel step: every seat's declared sena policy reacts to the window
        for mgr_seat, mgr in enumerate(self.procs):
            hand = engine.hands.get(mgr_seat)
            if not hand:
                continue
            for it in mgr.evaluate(engine, seat, t0, window, self.bus):
                if not it.truthful:
                    self.agents[mgr_seat].bluffs += 1
                self._event("sena", "hizo una seña para su compañero",
                            seat=mgr_seat, to_seat=partner_of(mgr_seat),
                            gesture=it.gesture)
        delivered = self.bus.pending_for(seat, t0)
        self.bus.deliver(delivered, t0)
        self.last_delivered = delivered
        for ev in delivered:
            self._event("sena_caught",
                        f"captó una seña de {self.agents[ev.from_seat].name}",
                        seat=seat, to_seat=ev.from_seat, gesture=ev.gesture)
        hand = list(engine.hands[seat])
        if agent.is_llm:
            self.stats["llm_turns"] += 1
            self.thinking_seat = seat
            self.touch()
            self._llm_turn(agent, hand)
            self.thinking_seat = None
        elif isinstance(agent, HumanSeat):
            self._human_turn(agent, hand)
            if self.stopped.is_set():
                return
        else:
            legal = engine.legal_actions(seat)
            try:
                action = agent.policy.act(engine, seat, legal)
                engine.apply(seat, action)
            except IllegalAction:
                action = _default_legal(engine, seat)
                engine.apply(seat, action)
        self.stats["turns"] += 1
        self.kernel.now = t0 + window
        self.touch()

    def _finish_hand(self, v_a0: int, v_b0: int):
        engine = self.engine
        self.reveal = {
            "hand": self.hands_played,
            "hands": {s: [str(c) for c in engine.hands[s]] for s in range(4)},
            "jugadas": [{"name": j.name, "winner": j.winner_team}
                        for j in engine.jugadas],
            "hand_winner": engine.hand_winner,
            "gain": {"a": engine.hand_gain_a, "b": engine.hand_gain_b},
            "thoughts": {a.seat: list(a.thoughts) for a in self.agents},
            "senas": [{"from": ev.from_seat, "to": ev.to_seat,
                       "gesture": ev.gesture, "truthful": ev.truthful_at_pub,
                       "delivered": ev.delivered_at is not None}
                      for ev in self.bus.events],
            "scores": {"a": engine.points_a, "b": engine.points_b,
                       "vacas_a": engine.vacas_a, "vacas_b": engine.vacas_b},
        }
        self.history.append({
            "hand": self.hands_played, "gain_a": engine.hand_gain_a,
            "gain_b": engine.hand_gain_b, "winner": engine.hand_winner,
            "jugadas": self.reveal["jugadas"],
            "hands": self.reveal["hands"],
        })
        if engine.hand_winner is not None:
            self._event("hand_end",
                        f"Fin de la mano {self.hands_played}: "
                        f"+{engine.hand_gain_a} A / +{engine.hand_gain_b} B · "
                        f"gana la mano el "
                        f"{'Equipo A' if engine.hand_winner == 0 else 'Equipo B'}")
        else:
            self._event("hand_end",
                        f"Fin de la mano {self.hands_played}: empate "
                        f"({engine.hand_gain_a}-{engine.hand_gain_b})")
        if engine.vacas_a > v_a0 or engine.vacas_b > v_b0:
            self._event("vaca",
                        f"¡VACA! A +{engine.vacas_a - v_a0} / "
                        f"B +{engine.vacas_b - v_b0} -> "
                        f"total {engine.vacas_a}-{engine.vacas_b}")
        for a in self.agents:
            a.thoughts.clear()
        self.touch()

    # ------------- web API surface -------------
    def seat_for_token(self, token: str | None) -> int | None:
        return self.tokens.get(token or "")

    def submit_human_action(self, seat: int, action: dict) -> tuple[bool, str]:
        agent = self.agents[seat]
        if not isinstance(agent, HumanSeat):
            return False, "seat is not human"
        if self.pending_human is None or self.pending_human.get("seat") != seat:
            return False, "not this seat's turn"
        if not isinstance(action.get("action"), str) or not action.get("action"):
            return False, "missing 'action'"
        agent.inbox.put(action)
        return True, ""

    def make_sena(self, seat: int, gesture: str) -> tuple[bool, str]:
        if self.match_status != "running" or self.engine.phase == Phase.DONE:
            return False, "no hay mano en juego ahora mismo"
        hand = self.engine.hands.get(seat)
        if not hand:
            return False, "no tienes cartas ahora mismo"
        ok = self._publish_sena(seat, gesture, hand)
        return ok, "" if ok else "seña desconocida"

    def say(self, seat: int, text) -> tuple[bool, str]:
        agent = self.agents[seat]
        original = " ".join(str(text).split()[:20])[:120]
        clean = redact_card_talk(original)
        if clean != original:
            agent.redactions += 1
            self._event("chat_redacted",
                        f"{agent.name}: (mensaje con cartas, censurado)",
                        seat=seat)
        if clean.strip():
            self.ch.say_public(seat, agent.name, clean)
            self._event("chat", f"{agent.name}: \"{clean}\"", seat=seat)
        self.touch()
        return True, ""

    # ------------- snapshot (per-viewer, leak-free) -------------
    def snapshot(self, token: str | None = None) -> dict:
        engine = self.engine
        seat = self.seat_for_token(token)
        lance = LANCE_NAMES[engine.lance_index] \
            if engine.phase in (Phase.ENVITE, Phase.DECLARE) else None
        seats = []
        for s, a in enumerate(self.agents):
            self.procs[s]
            seats.append({
                "seat": s, "name": a.name, "team": TEAM_OF[s],
                "model": ("humano" if isinstance(a, HumanSeat) else a.model),
                "is_human": isinstance(a, HumanSeat),
                "is_llm": a.is_llm,
                "thinking": self.thinking_seat == s,
                "folded": s in engine.envite.folded,
                "declared": engine.declared.get(s),
                "senas_sent": self.procs[s].published,
                "bluffs": a.bluffs,
            })
        envite = engine.envite
        holder = None
        if envite.holder is not None:
            holder = {"seat": envite.holder, "team": TEAM_OF[envite.holder]}
        snap = {
            "version": self.version,
            "status": self.match_status,
            "error": self.error,
            "phase": engine.phase.name,
            "lance": lance,
            "mano": engine.mano,
            "turn": engine.current_seat,
            "mus_round": engine.mus_rounds,
            "thinking_seat": self.thinking_seat,
            "seats": seats,
            "scores": {"points_a": engine.points_a,
                       "points_b": engine.points_b,
                       "vacas_a": engine.vacas_a,
                       "vacas_b": engine.vacas_b,
                       "hand_gain_a": engine.hand_gain_a,
                       "hand_gain_b": engine.hand_gain_b,
                       "hands_played": self.hands_played,
                       "hands_total": self.hands},
            "envite": {"current": envite.current, "previous": envite.previous,
                       "holder": holder,
                       "folded": sorted(engine.envite.folded),
                       "locked": envite.locked},
            "ordago": ({"caller": engine.ordago_caller,
                        "context": engine.ordago_context}
                       if engine.phase == Phase.ORDAGO_RESPONSE else None),
            "you": None,
            "reveal": self.reveal,
            "history": self.history[-20:],
            "config": {"seats": self.specs, "hands": self.hands,
                       "seed": self.seed},
            "senas_vocab": {g: m for g, (m, _src) in SENAS.items()},
            "stats": dict(self.stats,
                          senas_published=sum(m.published for m in self.procs),
                          senas_caught=sum(1 for ev in self.bus.events
                                           if ev.delivered_at is not None),
                          bluffs=sum(a.bluffs for a in self.agents)),
        }
        feed = []
        for ev in self.events[-300:]:
            if ev["kind"] in ("sena", "sena_caught"):
                authorized = (seat is not None
                              and seat in (ev["seat"], ev["to_seat"]))
                if not authorized:
                    ev = {**ev, "gesture": None}
            feed.append(ev)
        snap["feed"] = feed
        if seat is not None:
            a = self.agents[seat]
            pending = self.pending_human if (self.pending_human
                                             and self.pending_human["seat"] == seat) else None
            snap["you"] = {
                "seat": seat, "name": a.name, "team": TEAM_OF[seat],
                "hand": [str(c) for c in engine.hands.get(seat, [])]
                if engine.hands.get(seat) else [],
                "legal": pending["legal"] if pending else [],
                "error": pending["error"] if pending else None,
                "caught": ([{"gesture": ev.gesture,
                             "meaning": SENAS[ev.gesture][0],
                             "from_seat": ev.from_seat}
                            for ev in self.last_delivered] if pending else []),
                "my_senas": [{"gesture": g, "truthful": t}
                             for g, t in a.senas_log[-12:]],
            }
        return snap


class LiveTable:
    """Owns the current LiveGame; supports restarting the match on demand."""

    def __init__(self, specs: list[str], hands: int = 12, seed: int = 0):
        self.specs = list(specs)
        self.hands = hands
        self.seed = seed
        self.epoch = 0
        self.game: LiveGame | None = None
        self._lock = threading.Lock()

    def start_new(self, hands: int | None = None,
                  seed: int | None = None) -> LiveGame:
        with self._lock:
            if self.game is not None:
                self.game.stop()
            self.epoch += 1
            if hands is not None and hands > 0:
                self.hands = hands
            if seed is not None:
                self.seed = seed
            self.game = LiveGame(self.specs, hands=self.hands, seed=self.seed)
            self.game.epoch = self.epoch
            self.game.start()
            return self.game

    def current(self) -> LiveGame:
        with self._lock:
            return self.game


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return {}
    if length <= 0 or length > 1 << 20:
        return {}
    try:
        data = json.loads(handler.rfile.read(length).decode("utf8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


class LiveHTTP(BaseHTTPRequestHandler):
    """Routes: GET / (UI), /events (SSE), /snapshot; POST /api/action,
    /api/sena, /api/chat, /api/new."""

    def log_message(self, *a):  # silence request noise
        pass

    def _send(self, code: int, body: bytes, ctype: str,
              cache: str = "no-store", compress: bool = False):
        headers = [("Content-Type", ctype),
                   ("Content-Length", str(len(body))),
                   ("Cache-Control", cache)]
        if compress and len(body) > 1024 and \
                "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, 6)
            headers = [("Content-Type", ctype),
                       ("Content-Length", str(len(body))),
                       ("Cache-Control", cache),
                       ("Content-Encoding", "gzip"),
                       ("Vary", "Accept-Encoding")]
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _serve_card(self, name: str) -> bool:
        """Serve an optimized Spanish-deck SVG from assets/cards/."""
        if not CARD_FILE_RE.match(name) or os.sep in name or name.startswith("."):
            return False
        path = os.path.join(CARDS_DIR, name)
        if not os.path.isfile(path):
            return False
        with open(path, "rb") as fh:
            body = fh.read()
        self._send(200, body, "image/svg+xml; charset=utf-8",
                   cache="public, max-age=604800", compress=True)
        return True

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf8"),
                   "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        token = (parse_qs(parsed.query).get("token") or [None])[0]
        if parsed.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode("utf8"), "text/html; charset=utf-8")
        elif parsed.path.startswith("/cards/"):
            name = os.path.basename(parsed.path[len("/cards/"):])
            if not self._serve_card(name):
                self._send(404, b"not found", "text/plain")
        elif parsed.path == "/events":
            self._sse(token)
        elif parsed.path == "/snapshot":
            try:
                self._json(_table.current().snapshot(token))
            except Exception as e:  # noqa: BLE001 -- never 500 the table
                self._json({"error": f"snapshot failed: {e}"}, 500)
        elif parsed.path == "/api/results":
            self._json(aggregate_results(RESULTS_DIR))
        else:
            self._send(404, b"not found", "text/plain")

    def _sse(self, token: str | None):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        marker = None
        last_beat = time.monotonic()
        try:
            while True:
                g = _table.current()
                marker_now = (g.epoch, g.version)
                if marker_now != marker:
                    try:
                        payload = json.dumps(g.snapshot(token), ensure_ascii=False)
                    except Exception:  # noqa: BLE001 -- skip bad frame, retry
                        time.sleep(0.3)
                        continue
                    self.wfile.write(f"data: {payload}\n\n".encode("utf8"))
                    self.wfile.flush()
                    marker = marker_now
                    last_beat = time.monotonic()
                elif time.monotonic() - last_beat > 15:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_beat = time.monotonic()
                time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        body = _json_body(self)
        g = _table.current()
        seat = g.seat_for_token(body.get("token"))
        if path == "/api/action":
            if seat is None:
                self._json({"ok": False,
                            "error": "token inválido (sin asiento)"}, 403)
                return
            ok, err = g.submit_human_action(seat, body)
            self._json({"ok": True} if ok else {"ok": False, "error": err},
                       200 if ok else 409)
        elif path == "/api/sena":
            if seat is None:
                self._json({"ok": False,
                            "error": "token inválido (sin asiento)"}, 403)
                return
            ok, err = g.make_sena(seat, str(body.get("gesture", "")))
            self._json({"ok": True} if ok else {"ok": False, "error": err},
                       200 if ok else 400)
        elif path == "/api/chat":
            if seat is None:
                self._json({"ok": False,
                            "error": "token inválido (sin asiento)"}, 403)
                return
            ok, err = g.say(seat, body.get("text", ""))
            self._json({"ok": ok, "error": err})
        elif path == "/api/new":
            if seat is None:
                self._json({"ok": False,
                            "error": "solo los asientos humanos pueden "
                                     "reiniciar la partida"}, 403)
                return
            hands = body.get("hands")
            seed = body.get("seed")
            g2 = _table.start_new(
                hands=hands if isinstance(hands, int) else None,
                seed=seed if isinstance(seed, int) else None)
            self._json({"ok": True, "epoch": g2.epoch})
        else:
            self._send(404, b"not found", "text/plain")


_table: LiveTable | None = None  # set by main(); handlers read the live table


def main():
    global _table
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--seats",
                    default="human,glm5.3-flash,deepseek-v4-flash,heuristic",
                    help="4 specs (comma-separated): 'human', an LLM model "
                         "spec (provider:model), or heuristic/random. "
                         "Seats 0+2 are team A, 1+3 team B.")
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--results-dir", default=None,
                    help="directory scanned for bench results "
                         "(summary.json / batch outputs)")
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    if args.results_dir is not None:
        global RESULTS_DIR
        RESULTS_DIR = args.results_dir

    specs = [s.strip() for s in args.seats.split(",")]
    if len(specs) != 4 or any(not s for s in specs):
        ap.error("--seats requires exactly four non-empty comma-separated specs")

    _table = LiveTable(specs, hands=args.hands, seed=args.seed)
    _table.start_new()

    print(f"mus en vivo — http://localhost:{args.port}/", flush=True)
    for a in _table.game.human_agents:
        print(f"  asiento {a.seat} ({a.name}, equipo {TEAM_OF[a.seat]}): "
              f"http://localhost:{args.port}/?token={a.token}", flush=True)
    print(f"  resultados del bench: GET /api/results (dir: {RESULTS_DIR})",
          flush=True)
    print("  (sin token = espectador: ve gestos genéricos, nunca las señas)",
          flush=True)
    server = ThreadingHTTPServer((args.host, args.port), LiveHTTP)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _table.game.stop()


if __name__ == "__main__":
    main()
