"""Best-effort persistence of live-game traces to DynamoDB.

Every finished (or abandoned) live match is serialized -- seat specs, seed,
vacas, the event feed, per-decision model IO -- gzipped and written as one
binary attribute. Failures are logged and swallowed: the table must keep
dealing even when DynamoDB is unreachable.

Table layout (created out of band):
    pk  S   session id
    sk  S   unix timestamp of the save
    tte N   unix TTL (expiry, MUS_TRACE_TTL_DAYS)
    gz  B   gzip(json trace)

Config: MUS_TRACE_TABLE (default "mus-traces", empty disables),
MUS_TRACE_TTL_DAYS (default 120). Credentials come from the instance role.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import time

log = logging.getLogger("mus.trace")

TABLE = os.environ.get("MUS_TRACE_TABLE", "mus-traces")
TTL_DAYS = int(os.environ.get("MUS_TRACE_TTL_DAYS", "120"))
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") \
    or "eu-west-1"

try:  # optional dependency: offline machines keep working without it
    import boto3  # type: ignore
    # region must be explicit: an EC2 box has no default region in its env,
    # and boto3.client() raises NoRegionError instead of using the metadata
    _client = boto3.client("dynamodb", region_name=REGION)
except Exception:  # noqa: BLE001 -- no boto3 / no region / no creds
    _client = None


def enabled() -> bool:
    return bool(TABLE) and _client is not None


def save_trace(sid: str | None, record: dict) -> bool:
    """Put one trace item. Returns True when it actually landed."""
    if not sid or not enabled():
        return False
    now = int(time.time())
    try:
        blob = gzip.compress(
            json.dumps(record, ensure_ascii=False, default=str).encode("utf8"))
        _client.put_item(TableName=TABLE, Item={
            "pk": {"S": sid},
            "sk": {"S": str(now)},
            "tte": {"N": str(now + TTL_DAYS * 86400)},
            "gz": {"B": blob},
        })
        return True
    except Exception as e:  # noqa: BLE001 -- never break the table over this
        log.warning("trace save failed for %s: %s", sid, e)
        return False


def build_record(game) -> dict:
    """Serialize a LiveGame (or anything shaped like one) into a trace dict."""
    engine = getattr(game, "engine", None)
    return {
        "sid": getattr(game, "sid", None),
        "specs": getattr(game, "specs", None),
        "seed": getattr(game, "seed", None),
        "vaca_limit": getattr(game, "vaca_limit", 0),
        "status": getattr(game, "match_status", None),
        "error": getattr(game, "error", None),
        "vacas_a": getattr(engine, "vacas_a", None),
        "vacas_b": getattr(engine, "vacas_b", None),
        "hands_played": getattr(game, "hands_played", 0),
        "stats": getattr(game, "stats", {}),
        "events": (getattr(game, "events", None) or [])[-400:],
        "io": (getattr(game, "io_log", None) or [])[-400:],
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
