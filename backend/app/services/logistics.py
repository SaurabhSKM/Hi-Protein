"""Farm-gate-to-optical-sorter haulage economics.

The reason this module exists as its own layer: before it, the only consequence of
having no optical sorter in range was a flat 0.12 multiplicative cut on P_human and
the loss of an optical-sorted premium. That makes distance a quality story. It is
really a COST story, and a continuous one - which is why a parcel can be
agronomically ideal, pass food specification, and still lose money.

Two rules keep the cost honest:

1. Only the INCREMENTAL haul is charged. A farm already hauls cereals to its local
   collection silo and that cost sits inside the RICA operating cost the finance
   engine uses for both arms. Charging farm-to-sorter in full would double-count the
   first 25 km AND would charge the pulse arm for a haul the baseline cereal arm also
   makes, which would manufacture a penalty out of an accounting error.

2. Only the FOOD fraction is charged. The downgraded fraction needs no sorting; it
   goes to a local compounder or a neighbouring breeder inside the ordinary
   collection radius. So a bad grading year is cheaper to haul, not dearer - which is
   the correct sign and matters because it partly offsets the grading loss.

And one cost that is deliberately NOT charged to the farmer: the station's toll
cleaning-and-sorting fee. Whether it lands on the farmer or inside the buyer's margin
depends on the contract, and the contract prices this engine uses are quoted delivered
to the buyer, so charging it again here would double-count it. It is kept in the
reference data because it is the REVENUE line that pays for a new unit, and that is
where `unit_economics` uses it.
"""
from __future__ import annotations

import math

import numpy as np

from ..config import buyers_ref, load_ref


def ref() -> dict:
    return load_ref("logistics")


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle km between two (lon, lat) points."""
    lon1, lat1, lon2, lat2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def road_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance inflated by the road detour factor."""
    return haversine_km(a, b) * float(ref()["haulage"]["road_detour_factor"])


def existing_units() -> list[dict]:
    """The optical sorting units already in the ground."""
    return list(buyers_ref()["optical_sorting_units"])


def nearest_unit(
    point: tuple[float, float], units: list[dict] | None = None
) -> tuple[dict | None, float]:
    """Nearest sorting unit to a point and its ROAD distance in km."""
    pool = existing_units() if units is None else units
    if not point or not pool:
        return None, float("inf")
    best, best_km = None, float("inf")
    for u in pool:
        loc = u.get("location")
        if not loc:
            continue
        d = road_km(point, (float(loc[0]), float(loc[1])))
        if d < best_km:
            best, best_km = u, d
    return best, best_km


def access(point: tuple[float, float], units: list[dict] | None = None) -> dict:
    """Sorting access for one point: nearest unit, road km, and the binary flag."""
    unit, km = nearest_unit(point, units)
    max_km = float(ref()["sorting"]["max_distance_km"])
    return {
        "nearest_unit_name": (unit or {}).get("name"),
        "nearest_unit_dept": (unit or {}).get("dept"),
        "road_km": None if math.isinf(km) else round(km, 1),
        "within_range": bool(km <= max_km),
        "max_distance_km": max_km,
    }


def incremental_km(sorter_road_km: float | None) -> float:
    """Road km beyond the ordinary collection radius. Zero if inside it or unknown."""
    if sorter_road_km is None or not np.isfinite(sorter_road_km):
        return 0.0
    radius = float(ref()["haulage"]["local_collection_radius_km"])
    return max(0.0, float(sorter_road_km) - radius)


def food_haulage_eur_per_tonne(sorter_road_km: float | None) -> float:
    """Incremental haulage cost on one tonne of FOOD-grade harvest, EUR/t."""
    h = ref()["haulage"]
    return incremental_km(sorter_road_km) * float(h["eur_per_tonne_km"])


def sorting_fee_eur_per_tonne() -> float:
    """Toll cleaning and optical sorting fee on food-grade tonnage, EUR/t.

    Not charged to the farmer by this engine - see the module docstring. This is the
    station's revenue per tonne, used to work out whether a new unit pays for itself.
    """
    return float(ref()["sorting"]["cleaning_and_sorting_fee_eur_t"])


def haulage_cost_eur_ha(
    yield_t_ha: np.ndarray | float,
    food_fraction: np.ndarray | float,
    sorter_road_km: float | None,
) -> np.ndarray:
    """Incremental haulage to the sorter, per hectare, charged on food tonnes only.

    Returned as an array so it enters the Monte Carlo per draw: a bad grading year
    hauls less food tonnage and therefore pays less, which is the correct sign and
    partly offsets the grading loss rather than compounding it.
    """
    t_food = np.asarray(yield_t_ha, dtype=float) * np.asarray(food_fraction, dtype=float)
    return t_food * food_haulage_eur_per_tonne(sorter_road_km)


def max_viable_haul_km(pulse: str) -> dict:
    """How far this crop can economically travel to a sorter, from its own price spread.

    Falls straight out of the linear haulage model and is one of the more useful numbers
    the model produces, because it differs by an order of magnitude between crops that a
    single 80 km rule treats identically:

        max_km = collection_radius + (food_price - feed_price) / eur_per_tonne_km

    Field pea carries a food-versus-feed spread of about 78 EUR/t, so it stops paying
    for its own haul at roughly 200 km. Green lentil's spread is about 565 EUR/t and
    would pay to cross the country. That is why a single national distance threshold is
    the wrong instrument, and why the optimiser prices distance per crop instead.

    The figure is an upper bound on haulage alone. It does not mean the crop is
    profitable at that distance, only that the haul is not what kills it.
    """
    from ..config import crop as _crop

    spec = _crop(pulse)
    food = float(spec["price_eur_t"]["mean"])
    feed = float(spec.get("feed_price_eur_t", {}).get("mean", food))
    h = ref()["haulage"]
    radius = float(h["local_collection_radius_km"])
    rate = float(h["eur_per_tonne_km"])
    spread = max(food - feed, 0.0)
    return {
        "crop": pulse,
        "food_price_eur_t": food,
        "feed_price_eur_t": feed,
        "food_premium_eur_t": round(spread, 1),
        "max_viable_road_km": round(radius + spread / rate, 0),
        "collection_radius_km": radius,
        "note": (
            "Road distance at which the incremental haul consumes the entire food-grade "
            "premium. Beyond it there is no food-grade share at which sorting access is "
            "worth paying for. An upper bound on haulage, not a profitability threshold."
        ),
    }


def unit_economics(annual_tonnes: float) -> dict:
    """Levelised cost per tonne of a new 450k EUR unit at a given throughput.

    Reported so a planner can see whether the optimiser's recommended site actually
    carries enough tonnage to be worth building, rather than only seeing the hectares
    it unlocks.
    """
    u = ref()["new_unit"]
    capex = float(u["capex_eur"])
    opex = float(u["annual_opex_eur"])
    life = int(u["economic_life_yr"])
    r = float(u["discount_rate"])
    # Standard capital recovery factor.
    crf = (r * (1 + r) ** life) / ((1 + r) ** life - 1) if r > 0 else 1.0 / life
    annualised = capex * crf + opex
    t = max(float(annual_tonnes), 1.0)
    return {
        "capex_eur": capex,
        "annualised_cost_eur_yr": round(annualised, 0),
        "throughput_t_yr": round(float(annual_tonnes), 0),
        "capacity_t_yr": float(u["capacity_t_yr"]),
        "utilisation_pct": round(100.0 * float(annual_tonnes) / float(u["capacity_t_yr"]), 1),
        "levelised_cost_eur_t": round(annualised / t, 2),
        "covers_toll_fee": bool(annualised / t <= sorting_fee_eur_per_tonne()),
        "note": (
            "Levelised cost below the toll fee charged on food tonnage means the unit "
            "services its own capital at this throughput. Above it, the unit needs the "
            "grant to stand up."
        ),
    }
