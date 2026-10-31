"""Offtake contract matching and scoring.

Scores a buyer on what actually determines the farmer's outcome: the contracted
price for THIS crop, how binding the floor is, whether the quality grid is reachable
given this parcel's predicted grading, haulage distance, and access to optical
sorting. A high headline price behind an unreachable insect-damage tolerance is worth
less than a lower price with a loose grid, and the ranking says so.

Scoring is normalised against the best offer in the candidate set and driven by
expected revenue, not by a hand-weighted sum of proxies. Quality fit enters once,
through the share of the harvest that gets paid the food price; an earlier version
also added it as a separate term, which ranked a 346 EUR/t cooperative above a
905 EUR/t packer that paid 70 percent more per hectare.
"""
from __future__ import annotations

import math

import numpy as np

from ..config import buyers_ref, crop, departments

# How much of the food-grade fraction actually clears the grid, by fit class.
_FIT_YIELD = {"comfortable": 1.0, "tight": 0.88, "at_risk": 0.65}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def optical_sorting_access(
    dept_code: str, point: tuple[float, float] | None
) -> tuple[bool, float | None]:
    ref = buyers_ref()
    units = ref["optical_sorting_units"]
    max_km = float(ref["infrastructure_gaps"]["max_distance_km"])
    origin = point
    if origin is None:
        d = departments().get(dept_code)
        origin = tuple(d["centroid"]) if d else None
    if origin is None or not units:
        return True, None
    nearest = min(haversine_km(origin, tuple(u["location"])) for u in units)
    return nearest <= max_km, round(nearest, 1)


def _quality_fit(max_damage_pct: float, prob_human_grade: float) -> str:
    """How comfortably this parcel's predicted grading clears the buyer's grid."""
    needed = {2.0: 0.62, 3.0: 0.50, 4.0: 0.40}.get(float(max_damage_pct), 0.45)
    if prob_human_grade >= needed + 0.12:
        return "comfortable"
    if prob_human_grade >= needed:
        return "tight"
    return "at_risk"


def match(
    *,
    pulse: str,
    dept_code: str,
    region_code: str | None,
    point: tuple[float, float] | None,
    yield_t_ha: float,
    yield_q15_t_ha: float,
    prob_human_grade: float,
    human_fraction_median: float,
    area_ha: float,
) -> list[dict]:
    ref = buyers_ref()
    has_sorting, sort_km = optical_sorting_access(dept_code, point)
    origin = point or (
        tuple(departments()[dept_code]["centroid"]) if dept_code in departments() else None
    )
    f_base = float(np.clip(human_fraction_median, 0.0, 1.0))

    rows: list[dict] = []
    for b in ref["buyers"]:
        if b.get("is_floor_reference"):
            feed = float(crop(pulse)["feed_price_eur_t"]["mean"])
            rows.append({
                "buyer_id": b["buyer_id"], "buyer_name": b["buyer_name"],
                "grade": "No contract - feed market only",
                "contract_price_eur_t": None, "fallback_feed_price_eur_t": round(feed, 1),
                "floor_guaranteed": False, "distance_km": None,
                "expected_revenue_eur_ha": round(yield_t_ha * feed, 1),
                "expected_revenue_q15_eur_ha": round(yield_q15_t_ha * feed, 1),
                "premiums_applied": {}, "quality_fit": "comfortable",
                "optical_sorting_access": has_sorting,
                "nearest_sorting_km": sort_km,
                "match_score": 0.0, "notes": b.get("notes"),
                "_is_floor": True,
            })
            continue

        terms = (b.get("crops") or {}).get(pulse)
        if not terms:
            continue

        dist = (
            haversine_km(origin, tuple(b["location"]))
            if (origin and b.get("location")) else None
        )

        premiums: dict[str, float] = {}
        for k, v in (b.get("premiums") or {}).items():
            if k == "optical_sorted_eur_t" and not has_sorting:
                continue  # cannot be earned without sorting access
            premiums[k] = float(v)
        price = float(terms["price_eur_t"]) + sum(premiums.values())
        floor = float(terms["floor_eur_t"])

        fit = _quality_fit(terms.get("max_insect_damage_pct", 3.0), prob_human_grade)
        # An unreachable grid does not cut the price, it cuts the share of the
        # harvest paid at that price. Quality therefore enters revenue, once.
        f_eff = f_base * _FIT_YIELD[fit]
        blended = f_eff * price + (1.0 - f_eff) * floor
        rev = yield_t_ha * blended
        # Downside case: low yield AND poor grading in the same season.
        rev_q15 = yield_q15_t_ha * (0.5 * f_eff * price + (1.0 - 0.5 * f_eff) * floor)

        rows.append({
            "buyer_id": b["buyer_id"], "buyer_name": b["buyer_name"],
            "grade": (
                "Human food contract, floor guaranteed" if b.get("floor_guaranteed")
                else "Human food contract, no floor"
            ),
            "contract_price_eur_t": round(price, 1),
            "fallback_feed_price_eur_t": round(floor, 1),
            "floor_guaranteed": bool(b.get("floor_guaranteed")),
            "distance_km": round(dist, 1) if dist is not None else None,
            "expected_revenue_eur_ha": round(rev, 1),
            "expected_revenue_q15_eur_ha": round(rev_q15, 1),
            "premiums_applied": premiums,
            "quality_fit": fit,
            "optical_sorting_access": has_sorting,
            "nearest_sorting_km": sort_km,
            "match_score": 0.0,
            "notes": b.get("notes"),
            "_region_ok": (
                region_code is None
                or not b.get("region_focus")
                or region_code in b["region_focus"]
            ),
            "_target_tons": terms.get("target_tons"),
            "_is_floor": False,
        })

    contracts = [r for r in rows if not r["_is_floor"]]
    if contracts:
        best = max(r["expected_revenue_eur_ha"] for r in contracts) or 1.0
        best_q15 = max(r["expected_revenue_q15_eur_ha"] for r in contracts) or 1.0
        for r in contracts:
            score = (
                0.55 * (r["expected_revenue_eur_ha"] / best)
                + 0.18 * (r["expected_revenue_q15_eur_ha"] / best_q15)
                + 0.12 * (1.0 if r["floor_guaranteed"] else 0.0)
                + 0.10 * (1.0 if r["distance_km"] is None
                          else max(0.0, 1.0 - r["distance_km"] / 450.0))
                + 0.05 * (1.0 if r["_region_ok"] else 0.3)
            )
            # A buyer whose annual target cannot absorb this parcel is a weaker match.
            t = r["_target_tons"]
            if t and yield_t_ha * area_ha > float(t):
                score *= 0.85
            r["match_score"] = round(score, 4)

    for r in rows:
        r.pop("_region_ok", None)
        r.pop("_target_tons", None)
        r.pop("_is_floor", None)

    rows.sort(key=lambda r: (-r["match_score"], -(r["expected_revenue_eur_ha"] or 0)))
    return rows


def buyer_by_id(buyer_id: str, pulse: str | None = None) -> dict | None:
    """Flatten a buyer plus the terms for one crop into the shape finance expects."""
    for b in buyers_ref()["buyers"]:
        if b["buyer_id"] != buyer_id:
            continue
        if b.get("is_floor_reference"):
            return None
        terms = (b.get("crops") or {}).get(pulse) if pulse else None
        if pulse and not terms:
            return None
        out = {k: v for k, v in b.items() if k != "crops"}
        if terms:
            out["contract_price_eur_t"] = float(terms["price_eur_t"]) + sum(
                float(v) for v in (b.get("premiums") or {}).values()
            )
            out["fallback_feed_price_eur_t"] = float(terms["floor_eur_t"])
            out["max_insect_damage_pct"] = terms.get("max_insect_damage_pct")
            out["min_protein_pct"] = terms.get("min_protein_pct")
            out["target_tons"] = terms.get("target_tons")
        return out
    return None
