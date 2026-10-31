"""Human-food grading probability (the P_human term).

Deliberately a transparent, documented hazard model rather than a trained
classifier: no French open dataset records per-lot grading outcomes, so there is no
label to fit. Each penalty below is a named agronomic mechanism driven by a real
Meteo-France feature, and the API reports this block with provenance mode
"reference_table" so the UI never presents it as a measurement.
"""
from __future__ import annotations

import numpy as np

from ..config import crop, load_ref


def _spec() -> dict:
    return load_ref("quality")


def _penalty(name: str, value: float, crop_key: str) -> float:
    p = _spec()["penalties"][name]
    sens = float(p.get("crop_sensitivity", {}).get(crop_key, 1.0))
    if "threshold_mm" in p:
        over = max(0.0, value - p["threshold_mm"]) / 10.0
        raw = over * p["per_10mm_above"]
    elif "threshold_days" in p:
        over = max(0.0, value - p["threshold_days"])
        raw = over * p["per_day_above"]
    elif "threshold_index" in p:
        over = max(0.0, value - p["threshold_index"])
        raw = over * p["per_unit_above"]
    else:
        return 0.0
    return float(min(raw * sens, p["max"]))


def human_grade_probability(
    crop_key: str,
    *,
    harvest_rain_mm: float,
    may_days_above_20c: float,
    drought_stress_index: float,
    jun_heat_days_30c: float,
    has_optical_sorting_access: bool = True,
) -> dict:
    """Return P_human plus the itemised penalty breakdown that produced it."""
    spec = _spec()
    base = float(crop(crop_key).get("human_grade_base_prob", 0.6))
    if base <= 0.0:
        return {
            "prob": 0.0, "base": 0.0, "penalties": {},
            "note": f"{crop(crop_key)['label_fr']} has no human-food outlet in this model.",
        }

    items = {
        "harvest_staining": _penalty("harvest_staining", harvest_rain_mm, crop_key),
        "bruchid_damage": _penalty("bruchid_damage", may_days_above_20c, crop_key),
        "drought_splitting": _penalty("drought_splitting", drought_stress_index, crop_key),
        "heat_abortion_smallseed": _penalty("heat_abortion_smallseed", jun_heat_days_30c, crop_key),
    }
    sort_spec = spec["penalties"]["no_optical_sorting_access"]
    if not has_optical_sorting_access and crop_key in sort_spec["applies_to"]:
        items["no_optical_sorting_access"] = float(sort_spec["flat_penalty"])

    p = base
    for v in items.values():
        p *= 1.0 - v
    b = spec["bounds"]
    p = float(np.clip(p, b["min_prob"], b["max_prob"]))

    worst = max(items.items(), key=lambda kv: kv[1]) if items else (None, 0.0)
    note = f"Base human-grade probability for this crop is {base:.0%}."
    if worst[0] and worst[1] > 0.02:
        mech = spec["penalties"][worst[0]]["mechanism"]
        note += f" Largest deduction this season: {worst[0].replace('_', ' ')} ({worst[1]:.0%}). {mech}"
    else:
        note += " No weather driver crosses its damage threshold this season."

    return {"prob": p, "base": base, "penalties": items, "note": note}


def catastrophic_prob(harvest_rain_mm: float) -> float:
    c = _spec()["fraction_distribution"]["catastrophic_downgrade"]
    over = max(0.0, harvest_rain_mm - c["threshold_mm"]) / 10.0
    return float(
        min(c["base_prob"] + over * c["per_10mm_harvest_rain_above_threshold"], c["max_prob"])
    )


def sample_human_fraction(
    rng: np.random.Generator, p_human: np.ndarray, catastrophe_prob: float
) -> np.ndarray:
    """Sample the fraction of the harvest that clears human-food specification.

    Beta-distributed around P_human rather than a single coin flip per harvest: part
    of a lot really can be sorted into a passing fraction. A separate catastrophic
    event zeroes the whole lot.
    """
    kappa = float(_spec()["fraction_distribution"]["kappa"])
    p = np.clip(p_human, 1e-3, 1 - 1e-3)
    frac = rng.beta(p * kappa, (1.0 - p) * kappa)
    wiped = rng.random(frac.shape) < catastrophe_prob
    return np.where(wiped, 0.0, frac)


def expected_protein_pct(crop_key: str, yield_ratio: float) -> float:
    """Protein concentration falls as yield rises (the dilution effect)."""
    base = float(crop(crop_key).get("protein_pct_dm", 22.0))
    slope = float(_spec()["protein_response"]["pct_per_unit_yield_ratio"])
    return float(np.clip(base + slope * (yield_ratio - 1.0), 12.0, 45.0))


# --------------------------------------------------------------------------- #
# Vectorised path, used by the Monte Carlo engine.
# --------------------------------------------------------------------------- #
def _penalty_vec(name: str, value: np.ndarray, crop_key: str) -> np.ndarray:
    p = _spec()["penalties"][name]
    sens = float(p.get("crop_sensitivity", {}).get(crop_key, 1.0))
    v = np.asarray(value, dtype=float)
    if "threshold_mm" in p:
        raw = np.maximum(0.0, v - p["threshold_mm"]) / 10.0 * p["per_10mm_above"]
    elif "threshold_days" in p:
        raw = np.maximum(0.0, v - p["threshold_days"]) * p["per_day_above"]
    elif "threshold_index" in p:
        raw = np.maximum(0.0, v - p["threshold_index"]) * p["per_unit_above"]
    else:
        return np.zeros_like(v)
    return np.minimum(raw * sens, p["max"])


def human_grade_probability_vec(
    crop_key: str,
    *,
    harvest_rain_mm: np.ndarray,
    may_days_above_20c: np.ndarray,
    drought_stress_index: np.ndarray,
    jun_heat_days_30c: np.ndarray,
    has_optical_sorting_access: bool = True,
) -> np.ndarray:
    """P_human for a whole batch of sampled seasons at once."""
    spec = _spec()
    base = float(crop(crop_key).get("human_grade_base_prob", 0.6))
    n = len(np.asarray(harvest_rain_mm))
    if base <= 0.0:
        return np.zeros(n)
    p = np.full(n, base, dtype=float)
    p *= 1.0 - _penalty_vec("harvest_staining", harvest_rain_mm, crop_key)
    p *= 1.0 - _penalty_vec("bruchid_damage", may_days_above_20c, crop_key)
    p *= 1.0 - _penalty_vec("drought_splitting", drought_stress_index, crop_key)
    p *= 1.0 - _penalty_vec("heat_abortion_smallseed", jun_heat_days_30c, crop_key)
    sort_spec = spec["penalties"]["no_optical_sorting_access"]
    if not has_optical_sorting_access and crop_key in sort_spec["applies_to"]:
        p *= 1.0 - float(sort_spec["flat_penalty"])
    b = spec["bounds"]
    return np.clip(p, b["min_prob"], b["max_prob"])


def catastrophic_prob_vec(harvest_rain_mm: np.ndarray) -> np.ndarray:
    c = _spec()["fraction_distribution"]["catastrophic_downgrade"]
    over = np.maximum(0.0, np.asarray(harvest_rain_mm, dtype=float) - c["threshold_mm"]) / 10.0
    return np.minimum(
        c["base_prob"] + over * c["per_10mm_harvest_rain_above_threshold"], c["max_prob"]
    )
