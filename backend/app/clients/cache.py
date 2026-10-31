"""Disk-backed response cache so a live demo survives bad conference wifi."""
from __future__ import annotations

import contextlib
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..config import CACHE_DIR, OFFLINE

DEFAULT_TTL_S = 7 * 24 * 3600


def _key(namespace: str, payload: Any) -> Path:
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
    d = Path(CACHE_DIR) / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def get(namespace: str, payload: Any, ttl_s: int = DEFAULT_TTL_S) -> dict | None:
    p = _key(namespace, payload)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    # In offline mode a stale entry still beats no answer at all.
    if not OFFLINE and time.time() - rec.get("_cached_at", 0) > ttl_s:
        return None
    return rec


def put(namespace: str, payload: Any, value: dict) -> dict:
    rec = dict(value)
    rec["_cached_at"] = time.time()
    # A cache write failure must never fail the request it was serving.
    with contextlib.suppress(OSError):
        _key(namespace, payload).write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8"
        )
    return rec


def stats() -> dict:
    root = Path(CACHE_DIR)
    out: dict[str, int] = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        out[d.name] = len(list(d.glob("*.json")))
    return out
