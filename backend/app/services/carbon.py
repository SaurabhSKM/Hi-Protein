"""Scope 3 substitution accounting.

Two corrections that decide whether the carbon claim survives scrutiny:

1. The functional unit is kg of CRUDE PROTEIN, not kg of product. Imported soybean
   meal is 46 percent protein; field pea is 22 percent. Comparing them per kg of
   product flatters the pulse by a factor of two and is the single most common way
   plant-protein carbon claims get rejected on review.

2. Land-use change is reported BOTH ways. Amortised LUC is most of the footprint of
   South American soy meal, and whether a buyer's inventory includes it changes the
   answer by a factor of four. Quoting only the flattering convention is the second
   most common way these claims get rejected.
"""
from __future__ import annotations

import numpy as np

from ..clients import agribalyse
from ..config import carbon_ref, crop


def substitution_saving(
    pulse: str,
    pulse_yield_t_ha: float,
    area_ha: float,
    *,
    convention: str = "with_luc",
) -> dict:
    ref = carbon_ref()
    prot = ref["protein_content_pct_as_fed"]
    fb = ref["fallback_kg_co2e_per_kg_product"]

    fp = agribalyse.farm_gate_footprint(pulse)
    pulse_kg_co2e_per_kg = (
        fp["kg_co2e_per_kg"] if convention == "with_luc" else fp["kg_co2e_per_kg_excl_luc"]
    )

    soy_key = (
        "soybean_meal_brazil_imported" if convention == "with_luc"
        else "soybean_meal_brazil_no_luc"
    )
    soy_kg_co2e_per_kg = float(fb[soy_key])
    soy_protein = float(prot["soybean_meal_brazil_imported"]) / 100.0
    pulse_protein = float(prot.get(pulse, crop(pulse).get("protein_pct_dm", 22.0))) / 100.0

    pulse_t = max(pulse_yield_t_ha, 0.0) * area_ha
    protein_t = pulse_t * pulse_protein
    soy_meal_displaced_t = protein_t / soy_protein if soy_protein > 0 else 0.0

    co2e_soy_t = soy_meal_displaced_t * soy_kg_co2e_per_kg
    co2e_pulse_t = pulse_t * pulse_kg_co2e_per_kg
    saving_t = co2e_soy_t - co2e_pulse_t

    per_kg_protein = (
        (soy_kg_co2e_per_kg / soy_protein) - (pulse_kg_co2e_per_kg / pulse_protein)
        if pulse_protein > 0 else 0.0
    )
    return {
        "pulse_tonnes": pulse_t,
        "protein_tonnes": protein_t,
        "soy_meal_displaced_tonnes": soy_meal_displaced_t,
        "co2e_saved_tonnes": saving_t,
        "co2e_saved_per_kg_protein": per_kg_protein,
        "pulse_kg_co2e_per_kg": pulse_kg_co2e_per_kg,
        "soy_kg_co2e_per_kg": soy_kg_co2e_per_kg,
        "convention": convention,
        "footprint_provenance": fp,
    }


def imported_food_pulse_saving_per_kg(pulse: str) -> dict:
    """Transport-only CO2e saving per kg of FOOD-GRADE pulse, vs the same pulse imported.

    The graded fraction and the downgraded fraction have different counterfactuals, and
    conflating them is how a plant-protein carbon claim gets rejected. A lot that fails
    retail specification goes to feed and displaces imported soybean meal - that is the
    `substitution_saving` path above. A lot that passes displaces an imported pulse on a
    French plate, because France grows under half the dry pulses it eats.

    Only the transport differential is claimed. A Canadian and a French lentil are both
    rain-fed legumes whose production footprints open data cannot reliably separate, so
    asserting a production advantage would be inventing one. Transport is the term that
    genuinely depends on origin.
    """
    ref = carbon_ref()
    spec = ref["imported_food_pulse"]
    t = ref["transport"]
    o = spec["origins"].get(pulse)
    if not o:
        return {
            "kg_co2e_saved_per_kg": 0.0,
            "origin": None,
            "note": f"No import origin on record for {pulse}; no food-tier transport saving claimed.",
        }

    inland_factor = float(
        t["rail_kg_co2e_per_t_km"] if o.get("inland_mode") == "rail"
        else t["domestic_truck_kg_co2e_per_t_km"]
    )
    imported_per_t = (
        float(o["sea_km"]) * float(t["sea_kg_co2e_per_t_km"])
        + float(o["inland_km"]) * inland_factor
    )
    domestic_per_t = float(t["french_farm_to_processor_km"]) * float(
        t["domestic_truck_kg_co2e_per_t_km"]
    )
    return {
        "kg_co2e_saved_per_kg": max((imported_per_t - domestic_per_t) / 1000.0, 0.0),
        "imported_transport_kg_co2e_per_t": round(imported_per_t, 1),
        "domestic_transport_kg_co2e_per_t": round(domestic_per_t, 1),
        "origin": o["origin"],
        "note": spec["caveat"],
    }


def food_tier_impact(
    pulse: str,
    food_grade_tonnes: float,
    *,
    food_grade_tonnes_q15: float | None = None,
    food_grade_tonnes_q85: float | None = None,
) -> dict:
    """What the human-food fraction of this harvest does to French food imports.

    The headline here is deliberately a TONNAGE, not a carbon figure. How many tonnes
    of imported pulse this parcel takes off French plates is close to certain once the
    graded tonnage is known; the carbon attached to it is a transport differential and
    is small. Reporting the tonnage first, and the carbon second with its method
    stated, is the order that survives scrutiny.
    """
    per_kg = imported_food_pulse_saving_per_kg(pulse)
    t = max(float(food_grade_tonnes), 0.0)
    co2e = t * 1000.0 * per_kg["kg_co2e_saved_per_kg"] / 1000.0
    out = {
        "imported_pulse_displaced_tonnes": round(t, 2),
        "transport_co2e_saved_tonnes": round(co2e, 3),
        "transport_co2e_saved_kg_per_kg": round(per_kg["kg_co2e_saved_per_kg"], 4),
        "import_origin_displaced": per_kg["origin"],
        "method": carbon_ref()["imported_food_pulse"]["method"],
        "caveat": per_kg["note"],
    }
    if food_grade_tonnes_q15 is not None:
        out["imported_pulse_displaced_tonnes_q15"] = round(max(food_grade_tonnes_q15, 0.0), 2)
    if food_grade_tonnes_q85 is not None:
        out["imported_pulse_displaced_tonnes_q85"] = round(max(food_grade_tonnes_q85, 0.0), 2)
    return out


def nitrogen_saving_co2e(n_saved_kg_ha: float, area_ha: float) -> float:
    """CO2e avoided by not applying the nitrogen the legume replaced, tonnes.

    The factor covers both ammonia-synthesis emissions and field N2O, which is why it
    is far above the energy content of the fertiliser alone.
    """
    f = float(carbon_ref()["fallback_kg_co2e_per_kg_product"]["synthetic_n_fertiliser_kg_co2e_per_kg_n"])
    return max(n_saved_kg_ha, 0.0) * area_ha * f / 1000.0


def impact(
    pulse: str,
    pulse_yield_t_ha: float,
    n_saved_kg_ha: float,
    area_ha: float,
    *,
    convention: str = "with_luc",
) -> dict:
    """Full environmental block at a single yield point, under both LUC conventions.

    Kept for the intensity metrics that do not need the Monte Carlo distribution
    (per-kg-protein footprints, provenance). The headline tonnage is better read from
    `impact_distribution`, which propagates the engine's own yield uncertainty instead
    of collapsing it to one number before the carbon claim is even made.
    """
    primary = substitution_saving(pulse, pulse_yield_t_ha, area_ha, convention=convention)
    other_conv = "without_luc" if convention == "with_luc" else "with_luc"
    other = substitution_saving(pulse, pulse_yield_t_ha, area_ha, convention=other_conv)

    n_co2e = nitrogen_saving_co2e(n_saved_kg_ha, area_ha)
    luc = carbon_ref()["land_use_change"]
    return {
        "co2e_saved_tons_total": round(primary["co2e_saved_tonnes"] + n_co2e, 2),
        "co2e_saved_tons_other_convention": round(other["co2e_saved_tonnes"] + n_co2e, 2),
        "co2e_saved_per_kg_protein": round(primary["co2e_saved_per_kg_protein"], 3),
        "co2e_from_n_avoided_tons": round(n_co2e, 2),
        "synthetic_n_reduced_kg_total": round(max(n_saved_kg_ha, 0.0) * area_ha, 1),
        "soy_meal_displaced_tonnes": round(primary["soy_meal_displaced_tonnes"], 2),
        "protein_tonnes": round(primary["protein_tonnes"], 2),
        "convention": convention,
        "pulse_kg_co2e_per_kg": primary["pulse_kg_co2e_per_kg"],
        "soy_kg_co2e_per_kg": primary["soy_kg_co2e_per_kg"],
        "footprint_provenance": primary["footprint_provenance"],
        "luc_note": luc["note"],
    }


def _soy_substitution_vec(
    pulse: str, pulse_yield_t_ha: np.ndarray, area_ha: float, convention: str
) -> np.ndarray:
    """co2e saved from soy-meal substitution alone, one value per yield draw."""
    ref = carbon_ref()
    prot = ref["protein_content_pct_as_fed"]
    fb = ref["fallback_kg_co2e_per_kg_product"]

    fp = agribalyse.farm_gate_footprint(pulse)
    pulse_kg_co2e = fp["kg_co2e_per_kg"] if convention == "with_luc" else fp["kg_co2e_per_kg_excl_luc"]
    soy_key = (
        "soybean_meal_brazil_imported" if convention == "with_luc"
        else "soybean_meal_brazil_no_luc"
    )
    soy_kg_co2e = float(fb[soy_key])
    soy_protein = float(prot["soybean_meal_brazil_imported"]) / 100.0
    pulse_protein = float(prot.get(pulse, crop(pulse).get("protein_pct_dm", 22.0))) / 100.0

    pulse_t = np.clip(np.asarray(pulse_yield_t_ha, dtype=float), 0.0, None) * area_ha
    protein_t = pulse_t * pulse_protein
    soy_meal_t = protein_t / soy_protein if soy_protein > 0 else np.zeros_like(pulse_t)
    return soy_meal_t * soy_kg_co2e - pulse_t * pulse_kg_co2e


def impact_distribution(
    pulse: str,
    pulse_yield_t_ha: np.ndarray,
    n_saved_kg_ha: np.ndarray,
    area_ha: float,
    *,
    convention: str = "with_luc",
) -> dict:
    """Carbon saving across the WHOLE Monte Carlo sample, not one point yield.

    `impact()` takes a single yield value, which has always meant the median of the
    yield model's prediction. That throws away exactly the uncertainty the quantile
    model exists to quantify: a bad year that halves the pulse harvest also roughly
    halves the soy meal it displaces, so the carbon claim should carry a confidence
    interval the same way the financial one already does. This recomputes the Scope 3
    substitution and the nitrogen credit over every sampled draw and returns
    quantiles, using the same yield and nitrogen-credit arrays the financial engine
    already produced for this request - no new simulation, just the carbon accounting
    applied to the distribution instead of its median.
    """
    y = np.clip(np.asarray(pulse_yield_t_ha, dtype=float), 0.0, None)
    n_kg = np.clip(np.asarray(n_saved_kg_ha, dtype=float), 0.0, None)

    primary = _soy_substitution_vec(pulse, y, area_ha, convention)
    other_conv = "without_luc" if convention == "with_luc" else "with_luc"
    other = _soy_substitution_vec(pulse, y, area_ha, other_conv)

    n_factor = float(
        carbon_ref()["fallback_kg_co2e_per_kg_product"]["synthetic_n_fertiliser_kg_co2e_per_kg_n"]
    )
    n_co2e = n_kg * area_ha * n_factor / 1000.0

    total = primary + n_co2e
    total_other = other + n_co2e

    def q(a: np.ndarray, p: float) -> float:
        return round(float(np.quantile(a, p)), 2)

    return {
        "co2e_saved_tons_q15": q(total, 0.15),
        "co2e_saved_tons_median": q(total, 0.50),
        "co2e_saved_tons_q85": q(total, 0.85),
        "co2e_saved_tons_other_convention_median": q(total_other, 0.50),
    }
