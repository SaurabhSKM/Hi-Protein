"""Legume nitrogen carry-over credit, with physics-informed guardrails.

A flat "30 to 50 kg N/ha" assumption is where naive rotation calculators lose
credibility. The credit actually scales with the biomass the legume produced,
is limited by how fast the soil mineralises residue, and is partly lost to
over-winter drainage. Bounds follow the structure of INRAE's STICS soil-crop model
and the AzoFert advice method so the engine cannot predict an absurd saving in an
extreme year.
"""
from __future__ import annotations

import numpy as np

from ..config import crop, nitrogen_ref, soils


def residue_n_credit(
    legume: str,
    yield_t_ha: np.ndarray | float,
    soil_type: str,
    *,
    autumn_winter_rain_mm: float = 230.0,
    has_cover_crop: bool = True,
) -> np.ndarray:
    """Mineralisable nitrogen left for the following crop, kg N/ha."""
    ref = nitrogen_ref()
    spec = crop(legume)
    rc = spec.get("residue_n_credit_kg_ha")
    if not rc:
        return np.zeros_like(np.asarray(yield_t_ha, dtype=float))

    y = np.asarray(yield_t_ha, dtype=float)
    ref_yield = max(float(spec["yield_t_ha_ref"]), 0.1)
    # Damped, not linear: a double-yield crop does not leave double the available N.
    exponent = float(ref["credit_model"]["yield_ratio_damping_exponent"])
    ratio = np.clip(y / ref_yield, 0.0, 2.0) ** exponent

    base = float(rc["typical"])
    miner = float(ref["soil_mineralisation_factor"].get(soil_type, 0.9))

    lf = ref["leaching_loss_fraction"]
    ru = float(soils()[soil_type]["reserve_utile_mm"])
    excess = max(0.0, autumn_winter_rain_mm - 200.0) / 100.0
    loss = lf["base"] + excess * lf["per_100mm_autumn_rain_above_200mm"]
    # Light soils drain faster, so the same rainfall leaches more.
    loss *= float(np.clip(lf["reserve_utile_reference_mm"] / max(ru, 40.0), 0.7, 1.8))
    if has_cover_crop:
        loss *= 1.0 - lf["cover_crop_mitigation"]
    loss = float(np.clip(loss, 0.0, lf["max"]))

    credit = base * ratio * miner * (1.0 - loss)
    b = ref["credit_model"]["absolute_bounds_kg_ha"]
    return np.clip(credit, b["min"], b["max"])


def capped_n_saving_kg(
    credit_kg: np.ndarray | float, following_crop: str = "soft_wheat"
) -> np.ndarray:
    """Cap the saving at a defensible share of the following crop's N budget."""
    ref = nitrogen_ref()
    dose = float(crop(following_crop).get("n_fertiliser_kg_ha", 180.0))
    cap = dose * float(ref["wheat_n_dose_reduction"]["max_fraction_of_wheat_dose"])
    return np.minimum(np.asarray(credit_kg, dtype=float), cap)


def following_yield_boost(
    legume: str,
    legume_yield_t_ha: np.ndarray | float,
    *,
    drought_limited: bool = False,
) -> np.ndarray:
    """Yield gain of the following winter wheat, t/ha.

    Only part of this is nitrogen; the rest is the break-crop effect on take-all and
    grass weeds. Lentil and chickpea leave little biomass, hence a much smaller gain
    than the +0.5 to +0.8 t/ha often quoted for pea and fava bean.
    """
    ref = nitrogen_ref()["following_wheat_yield_response"]
    mean = float(ref["by_legume"].get(legume, ref["mean_t_ha"]))
    y = np.asarray(legume_yield_t_ha, dtype=float)
    ref_yield = max(float(crop(legume)["yield_t_ha_ref"]), 0.1)
    # A failed legume leaves little residue, so it cannot deliver the full gain.
    scale = np.clip(y / ref_yield, 0.25, 1.25) ** 0.5
    boost = mean * scale
    if drought_limited:
        boost *= 0.75
    return np.clip(boost, ref["min_t_ha"], ref["max_t_ha"])


def n_price_draw(rng: np.random.Generator, n: int) -> np.ndarray:
    """Nitrogen fertiliser price, EUR per kg N. Gas-linked and highly volatile."""
    p = nitrogen_ref()["n_fertiliser_price_eur_per_kg_n"]
    draw = rng.lognormal(
        mean=np.log(p["mean"]) - 0.5 * (p["sd"] / p["mean"]) ** 2,
        sigma=p["sd"] / p["mean"],
        size=n,
    )
    return np.clip(draw, p["min"], p["max"])
