"""Application configuration and reference-data loading."""
from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
REFDATA_DIR = APP_DIR / "refdata"
PROJECT_ROOT = APP_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
ML_ARTIFACT_DIR = PROJECT_ROOT / "ml" / "artifacts"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Offline mode forces every external client to serve from the local cache only.
# Set HIPROTEIN_OFFLINE=1 before a live demo on untrusted conference wifi.
OFFLINE = os.getenv("HIPROTEIN_OFFLINE", "0") == "1"

# Monte Carlo trajectory count. Overridable per request within a safe band.
DEFAULT_N_SIMULATIONS = int(os.getenv("HIPROTEIN_N_SIM", "2000"))
MAX_N_SIMULATIONS = 20000

EXTERNAL_TIMEOUT_S = float(os.getenv("HIPROTEIN_HTTP_TIMEOUT", "6.0"))

API_PREFIX = "/api/v1"

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "HIPROTEIN_CORS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
    ).split(",")
    if o.strip()
]


@cache
def load_ref(name: str) -> dict[str, Any]:
    """Load and memoise a reference-data JSON file by stem name."""
    path = REFDATA_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Reference data file missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def crops() -> dict[str, Any]:
    return {k: v for k, v in load_ref("crops").items() if not k.startswith("_")}


def crop(name: str) -> dict[str, Any]:
    table = crops()
    if name not in table:
        raise KeyError(f"Unknown crop '{name}'. Known: {sorted(table)}")
    return table[name]


def soils() -> dict[str, Any]:
    return {k: v for k, v in load_ref("soils").items() if not k.startswith("_")}


def departments() -> dict[str, Any]:
    return {k: v for k, v in load_ref("departments").items() if not k.startswith("_")}


def pulse_crops() -> list[str]:
    return [k for k, v in crops().items() if v.get("family") == "pulse"]


def pac() -> dict[str, Any]:
    return load_ref("pac_2023_2027")


def rules() -> dict[str, Any]:
    return load_ref("rotation_rules")


def nitrogen_ref() -> dict[str, Any]:
    return load_ref("nitrogen")


def carbon_ref() -> dict[str, Any]:
    return load_ref("carbon")


def buyers_ref() -> dict[str, Any]:
    return load_ref("buyers")
