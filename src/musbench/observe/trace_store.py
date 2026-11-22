"""Best-effort persistence of live-game traces.

Every finished (or abandoned) live match is serialized — seat specs, seed,
vacas, hand history, the event feed, accepted actions, per-decision model IO —
and written to:

1. **Local disk** (always, unless ``MUS_TRACE_DIR`` is empty): one gzip JSON
   file per save under ``MUS_TRACE_DIR`` (default ``traces/`` next to cwd, or
   ``/var/lib/mus/traces`` when that directory is writable).
2. **DynamoDB** when ``MUS_TRACE_TABLE`` is set and boto3/creds work.

Failures are logged and swallowed: the table must keep dealing even when
storage is unreachable. A game without a session id gets one minted at save
time so anonymous / local plays are still kept.

DynamoDB layout (created out of band)::

    pk  S   session id
    sk  N   unix timestamp of the save
    tte N   unix TTL (expiry, MUS_TRACE_TTL_DAYS)
    gz  B   gzip(json trace)

Config: ``MUS_TRACE_DIR`` (default ``traces``, empty disables disk),
``MUS_TRACE_TABLE`` (default ``mus-traces``, empty disables DynamoDB),
``MUS_TRACE_TTL_DAYS`` (default 120). DynamoDB credentials come from the
instance role.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import secrets
import time
from pathlib import Path

log = logging.getLogger("mus.trace")

TABLE = os.environ.get("MUS_TRACE_TABLE", "mus-traces")
TTL_DAYS = int(os.environ.get("MUS_TRACE_TTL_DAYS", "120"))
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") \
    or "eu-west-1"


def _default_trace_dir() -> str:
    env = os.environ.get("MUS_TRACE_DIR")
    if env is not None:
        return env  # empty string = disable
    for candidate in ("/var/lib/mus/traces", "traces"):
        path = Path(candidate)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_probe"
            probe.write_text("ok", encoding="utf8")
            probe.unlink(missing_ok=True)
            return str(path)
        except OSError:
            continue
    fallback = Path("/tmp/mus-traces")
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    return str(fallback)


try:  # optional dependency: offline machines keep working without it
    import boto3  # type: ignore
    # region must be explicit: an EC2 box has no default region in its env,
    # and boto3.client() raises NoRegionError instead of using the metadata
    _client = boto3.client("dynamodb", region_name=REGION)
except Exception:  # noqa: BLE001 -- no boto3 / no region / no creds
    _client = None


def trace_dir() -> str:
    """Resolved on each call so tests can override ``MUS_TRACE_DIR``."""
    return _default_trace_dir()


# Back-compat alias for callers/docs that read the module attribute.
TRACE_DIR = trace_dir()


def enabled() -> bool:
    """True when at least one sink is available."""
    return bool(trace_dir()) or (bool(TABLE) and _client is not None)


def dynamo_enabled() -> bool:
    return bool(TABLE) and _client is not None


def ensure_sid(game) -> str:
    """Mint a durable id if the game never got a public session cookie."""
    sid = getattr(game, "sid", None)
    if sid:
        return sid
    sid = f"local-{secrets.token_urlsafe(10)}"
    try:
        game.sid = sid
    except Exception:  # noqa: BLE001
        pass
    return sid


def save_trace(sid: str | None, record: dict) -> bool:
    """Persist one trace. Returns True when at least one sink accepted it."""
    if not sid:
        sid = record.get("sid") or f"anon-{int(time.time())}"
        record = dict(record)
        record["sid"] = sid
    now = int(time.time())
    record = dict(record)
    record.setdefault("sid", sid)
    record.setdefault("saved_at", now)
    try:
        blob = gzip.compress(
            json.dumps(record, ensure_ascii=False, default=str).encode("utf8"))
    except Exception as e:  # noqa: BLE001
        log.warning("trace serialize failed for %s: %s", sid, e)
        return False

    disk = trace_dir()
    ok_disk = _save_disk(sid, now, blob, record, disk)
    ok_ddb = _save_dynamo(sid, now, blob)
    if not (ok_disk or ok_ddb):
        log.warning("trace save missed every sink for %s "
                    "(dir=%r table=%r boto=%s)",
                    sid, disk, TABLE, _client is not None)
    return ok_disk or ok_ddb


def _save_disk(sid: str, now: int, blob: bytes, record: dict,
               disk: str | None = None) -> bool:
    if disk is None:
        disk = trace_dir()
    if not disk:
        return False
    try:
        root = Path(disk)
        root.mkdir(parents=True, exist_ok=True)
        # One file per save; sid sanitized for the filesystem.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:80]
        path = root / f"{safe}-{now}.json.gz"
        path.write_bytes(blob)
        # Tiny sidecar index for grepping without gunzip.
        idx = root / "index.jsonl"
        with idx.open("a", encoding="utf8") as fh:
            fh.write(json.dumps({
                "sid": sid,
                "ts": now,
                "file": path.name,
                "status": record.get("status"),
                "nick": record.get("nick"),
                "hands_played": record.get("hands_played"),
                "vacas_a": record.get("vacas_a"),
                "vacas_b": record.get("vacas_b"),
                "specs": record.get("specs"),
            }, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception as e:  # noqa: BLE001 -- never break the table over this
        log.warning("trace disk save failed for %s: %s", sid, e)
        return False


def _save_dynamo(sid: str, now: int, blob: bytes) -> bool:
    if not dynamo_enabled():
        return False
    try:
        _client.put_item(TableName=TABLE, Item={
            "pk": {"S": sid},
            "sk": {"N": str(now)},
            "tte": {"N": str(now + TTL_DAYS * 86400)},
            "gz": {"B": blob},
        })
        return True
    except Exception as e:  # noqa: BLE001 -- never break the table over this
        log.warning("trace dynamo save failed for %s: %s", sid, e)
        return False


def build_record(game) -> dict:
    """Serialize a LiveGame (or anything shaped like one) into a trace dict."""
    engine = getattr(game, "engine", None)
    agents = getattr(game, "agents", None) or []
    seats = []
    for a in agents:
        seats.append({
            "seat": getattr(a, "seat", None),
            "name": getattr(a, "name", None),
            "model": getattr(a, "model", None),
            "provider": getattr(a, "provider", None),
            "is_llm": bool(getattr(a, "is_llm", False)),
            "is_human": type(a).__name__ == "HumanSeat",
            "api_errors": getattr(a, "api_errors", 0),
            "fallbacks": getattr(a, "fallbacks", 0),
            "rejections": getattr(a, "rejections", 0),
        })
    return {
        "sid": getattr(game, "sid", None),
        "nick": getattr(game, "player_nick", None),
        "specs": getattr(game, "specs", None),
        "lineup": getattr(game, "lineup", None),
        "seed": getattr(game, "seed", None),
        "vaca_limit": getattr(game, "vaca_limit", 0),
        "status": getattr(game, "match_status", None),
        "error": getattr(game, "error", None),
        "vacas_a": getattr(engine, "vacas_a", None),
        "vacas_b": getattr(engine, "vacas_b", None),
        "points_a": getattr(engine, "points_a", None),
        "points_b": getattr(engine, "points_b", None),
        "hands_played": getattr(game, "hands_played", 0),
        "stats": getattr(game, "stats", {}),
        "seats": seats,
        "history": getattr(game, "history", None) or [],
        "play": (getattr(game, "play_log", None) or [])[-800:],
        "events": (getattr(game, "events", None) or [])[-600:],
        "io": (getattr(game, "io_log", None) or [])[-400:],
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def persist_game(game) -> bool:
    """Idempotent save for a LiveGame. Safe to call from run() and teardown."""
    if getattr(game, "_trace_saved", False):
        return True
    sid = ensure_sid(game)
    ok = save_trace(sid, build_record(game))
    if ok:
        try:
            game._trace_saved = True
        except Exception:  # noqa: BLE001
            pass
    return ok
