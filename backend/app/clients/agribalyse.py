"""ADEME Agribalyse client (hosted on data.ademe.fr, DataFair API).

Uses the PER-STAGE dataset, not the synthesis table. The synthesis value for
"Lentille, seche" is 0.581 kg CO2e/kg, but 0.244 of that is retail transport and
0.129 is packaging; the AGRICULTURE stage is only 0.141. A farm-gate rotation
comparison must use the agriculture stage, or it overstates the pulse footprint by a
factor of four and makes the whole carbon claim indefensible.
"""
from __future__ import annotations

from datetime import UTC, datetime

import requests

from ..config import EXTERNAL_TIMEOUT_S, OFFLINE, carbon_ref
from . import cache

BASE = "https://data.ademe.fr/data-fair/api/v1/datasets/agribalyse-31-detail-par-etape/lines"
UA = {"User-Agent": "hiprotein-hackathon/1.0"}

AG = "Changement_climatique_-_Agriculture"
LUC_AG = "Changement_climatique_-_émissions_liées_au_changement_d'affectation_des_sols_-_Agriculture"
NAME = "Nom_du_Produit_en_Français"

# The Agribalyse product that best represents the harvested, dried crop.
CROP_TO_PRODUCT = {
    "green_lentil": "Lentille, sèche",
    "field_pea": "Pois cassé, sec",
    "winter_pea": "Pois cassé, sec",
    "chickpea": "Pois chiche, sec",
    "fava_bean": "Fève, sèche",
    "sunflower": "Tournesol, graine",
}
# Not in Agribalyse: it is a consumer-food database, so unprocessed feed and
# commodity grains (soybean, soybean meal, wheat grain, rapeseed) have no entry and
# fall back to the local reference table.
NOT_IN_AGRIBALYSE = {"soybean", "soft_wheat", "spring_barley", "rapeseed"}

# Agribalyse assigns pea and chickpea the same pulse proxy (0.400 kg CO2e/kg at the
# agriculture stage, including 0.173 of land-use change). A land-use-change burden on
# a European grain legume is implausible and indicates the proxy blends imported
# product, so the per-crop discrimination here is weaker than the figures suggest.
DATA_QUALITY_NOTES = {
    "field_pea": "Agribalyse uses one shared pulse proxy for pea and chickpea, including an implausible land-use-change component.",
    "winter_pea": "Agribalyse uses one shared pulse proxy for pea and chickpea, including an implausible land-use-change component.",
    "chickpea": "Agribalyse uses one shared pulse proxy for pea and chickpea, including an implausible land-use-change component.",
}


def _lookup(product: str) -> dict | None:
    payload = {"product": product}
    hit = cache.get("agribalyse", payload)
    if hit is not None:
        hit["_mode"] = "cached"
        return hit
    if OFFLINE:
        return None
    try:
        # Exact phrase match on the product name only. Passing a free-text `q`
        # alongside this lets relevance ranking return a different product
        # entirely, which silently gave pea and chickpea the same footprint.
        r = requests.get(
            BASE,
            params={"qs": f'{NAME}:"{product}"', "size": 1},
            timeout=EXTERNAL_TIMEOUT_S,
            headers=UA,
        )
        if r.status_code != 200:
            return None
        body = r.json()
        results = body.get("results") or []
    except (requests.RequestException, ValueError):
        return None
    if not results or (body.get("total") or 0) < 1:
        return None
    row = results[0]
    if (row.get(NAME) or "").strip().lower() != product.lower():
        return None
    rec = {
        "product": row.get(NAME),
        "kg_co2e_per_kg_agriculture": row.get(AG),
        "kg_co2e_per_kg_luc_agriculture": row.get(LUC_AG),
        "dqr": row.get("DQR"),
        "code_agb": row.get("Code_AGB"),
        "_mode": "live_api",
    }
    return cache.put("agribalyse", payload, rec)


def farm_gate_footprint(crop_key: str) -> dict:
    """kg CO2e per kg of harvested crop at the farm gate, with provenance."""
    product = CROP_TO_PRODUCT.get(crop_key)
    rec = _lookup(product) if product else None
    if rec and rec.get("kg_co2e_per_kg_agriculture") is not None:
        total = float(rec["kg_co2e_per_kg_agriculture"])
        luc = float(rec.get("kg_co2e_per_kg_luc_agriculture") or 0.0)
        return {
            "kg_co2e_per_kg": total,
            "kg_co2e_per_kg_excl_luc": max(total - luc, 0.0),
            "product": rec.get("product"),
            "dqr": rec.get("dqr"),
            "mode": rec.get("_mode", "cached"),
            "source": "ADEME Agribalyse v3.1, agriculture stage only",
            "data_quality_note": DATA_QUALITY_NOTES.get(crop_key),
            "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    fb = carbon_ref()["fallback_kg_co2e_per_kg_product"]
    val = float(fb.get(crop_key, 0.7))
    return {
        "kg_co2e_per_kg": val,
        "kg_co2e_per_kg_excl_luc": val,
        "product": product,
        "dqr": None,
        "mode": "assumption",
        "source": (
            "Local reference table: not present in Agribalyse (consumer-food database)"
            if crop_key in NOT_IN_AGRIBALYSE
            else "Local fallback table (Agribalyse unreachable)"
        ),
        "data_quality_note": DATA_QUALITY_NOTES.get(crop_key),
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def warm_cache() -> dict[str, str]:
    """Pre-fetch every product we might need, so the demo never waits on the network."""
    out = {}
    for crop_key in CROP_TO_PRODUCT:
        out[crop_key] = farm_gate_footprint(crop_key)["mode"]
    return out
