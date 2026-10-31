"""IGN API Carto - Registre Parcellaire Graphique (RPG) v2.

Endpoint verified live: GET https://apicarto.ign.fr/api/rpg/v2?geom=<GeoJSON>&annee=YYYY
Feature properties returned: id_parcel, surf_parc, code_cultu, code_group,
culture_d1, culture_d2. Campaign years 2015-2023 respond; 2010 returns HTTP 400.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import requests

from ..config import EXTERNAL_TIMEOUT_S, OFFLINE
from ..services.rpg_codes import SUPPORTED_YEARS, crop_for, is_fallow, label_for
from . import cache

BASE_URL = "https://apicarto.ign.fr/api/rpg/v2"
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


def parcel_history(lon: float, lat: float, years: list[int] | None = None) -> dict:
    """Walk back through RPG campaigns at a point to reconstruct the crop history."""
    years = years or AVAILABLE_YEARS
    history: list[dict] = []
    geometry = None
    surface = None
    modes: set[str] = set()

    for y in years:
        data = _fetch_year(lon, lat, y)
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
