"""IGN API Carto - Registre Parcellaire Graphique (RPG) v2.

Endpoint verified live: GET https://apicarto.ign.fr/api/rpg/v2?geom=<GeoJSON>&annee=YYYY
Feature properties returned: id_parcel, surf_parc, code_cultu, code_group,
culture_d1, culture_d2. Campaign years 2015-2023 respond; 2010 returns HTTP 400.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import requests

from ..config import EXTERNAL_TIMEOUT_S, OFFLINE
from ..services.rpg_codes import SUPPORTED_YEARS, crop_for, is_fallow, label_for
from . import cache

BASE_URL = "https://apicarto.ign.fr/api/rpg/v2"

# Overall wall-clock budget for one parcel lookup, across all campaigns. Chosen to sit
# well inside the 60-second gateway timeout in front of this app with room for the
# simulation that follows. Whatever has arrived when it expires is returned.
PARCEL_BUDGET_S = float(os.getenv("HIPROTEIN_PARCEL_BUDGET_S", "12.0"))
AVAILABLE_YEARS = list(SUPPORTED_YEARS)
UA = {"User-Agent": "hiprotein-hackathon/1.0"}


def _fetch_year(lon: float, lat: float, year: int) -> dict | None:
    payload = {"lon": round(lon, 6), "lat": round(lat, 6), "annee": year}
    hit = cache.get("rpg", payload)
    if hit is not None:
        hit["_mode"] = "cached"
        return hit
    if OFFLINE:
        return None
    geom = json.dumps({"type": "Point", "coordinates": [lon, lat]})
    try:
        r = requests.get(
            BASE_URL, params={"geom": geom, "annee": year},
            timeout=EXTERNAL_TIMEOUT_S, headers=UA,
        )
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    data["_mode"] = "live_api"
    return cache.put("rpg", payload, data)


def _fetch_years_concurrently(
    lon: float, lat: float, years: list[int]
) -> dict[int, dict | None]:
    """Fetch every campaign in parallel, returning whatever arrives inside the budget.

    Cache hits are resolved first and without a thread, so the warm path - which is the
    demo path - stays synchronous and allocation-free.
    """
    out: dict[int, dict | None] = {}
    pending: list[int] = []
    for y in years:
        hit = cache.get("rpg", {"lon": round(lon, 6), "lat": round(lat, 6), "annee": y})
        if hit is not None:
            hit["_mode"] = "cached"
            out[y] = hit
        else:
            pending.append(y)

    if not pending or OFFLINE:
        return out

    deadline = time.monotonic() + PARCEL_BUDGET_S
    with ThreadPoolExecutor(max_workers=min(len(pending), 9)) as pool:
        futures = {pool.submit(_fetch_year, lon, lat, y): y for y in pending}
        for fut in as_completed(futures, timeout=max(PARCEL_BUDGET_S, 0.1)):
            try:
                out[futures[fut]] = fut.result(timeout=max(deadline - time.monotonic(), 0.1))
            except Exception:  # noqa: BLE001, S110 - a missing campaign is not an error
                out[futures[fut]] = None
            if time.monotonic() > deadline:
                # Stop collecting. Outstanding futures are abandoned rather than
                # waited on; a partial history beats a gateway timeout.
                break
    return out


def parcel_history(lon: float, lat: float, years: list[int] | None = None) -> dict:
    """Walk back through RPG campaigns at a point to reconstruct the crop history.

    Fetched CONCURRENTLY, with an overall wall-clock budget. The original loop was
    serial: nine campaigns at a six-second per-request timeout is a 54-second worst
    case, and the farmer tab now fires this on page load rather than only on a map
    click. Behind the workshop's nginx - which gives up at 60 seconds - a cold cache on
    poor wifi turns that into a 504 on the first screen the jury sees, with no clue
    that the cause is one slow upstream.

    Concurrent, the worst case is one request timeout plus overhead. The budget below
    is a second backstop: whatever has arrived when it expires is what gets returned,
    because a partial crop history still produces a usable answer (the engine falls
    back to the declared rotation) whereas a timeout produces none.
    """
    years = years or AVAILABLE_YEARS
    history: list[dict] = []
    geometry = None
    surface = None
    modes: set[str] = set()

    results = _fetch_years_concurrently(lon, lat, years)
    for y in years:
        data = results.get(y)
        if not data:
            continue
        modes.add(data.get("_mode", "live_api"))
        feats = data.get("features") or []
        if not feats:
            continue
        props = feats[0].get("properties", {}) or {}
        if geometry is None:
            geometry = feats[0].get("geometry")
            surface = props.get("surf_parc")
        history.append({
            "year": y,
            "id_parcel": props.get("id_parcel"),
            "surf_parc_ha": props.get("surf_parc"),
            "code_cultu": props.get("code_cultu"),
            "code_group": props.get("code_group"),
            "crop_label": label_for(props.get("code_cultu")),
            "mapped_crop": crop_for(props.get("code_cultu"), props.get("code_group")),
            "is_fallow": is_fallow(props.get("code_cultu")),
        })

    history.sort(key=lambda h: h["year"])
    mode = "cached" if modes == {"cached"} else ("live_api" if modes else "assumption")
    return {
        "found": bool(history),
        "geometry": geometry,
        "surface_ha": surface,
        "history": history,
        "mode": mode,
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def inferred_rotation(history: list[dict]) -> list[str]:
    """Internal crop keys, oldest first, skipping campaigns we cannot map."""
    return [h["mapped_crop"] for h in history if h.get("mapped_crop")]
