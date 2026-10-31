"""Three-year rotational margin engine.

Methodological choices that separate this from a spreadsheet:

1. BOTH rotations are simulated, under the SAME sampled weather and the same
   standardised residual shocks (common random numbers). The blueprint's original
   formulation compared a stochastic pulse rotation against a single deterministic
   baseline number, which credits the pulse with all of the baseline's good luck.
   What a farmer actually decides on is the DISTRIBUTION OF THE DIFFERENCE, and that
   is only estimable when both arms share the draws.

2. Only year 2 changes. Year 1 is identical in both arms, and year 3 keeps the same
   crop, differing only by the nitrogen credit and break-crop yield response the
   legume leaves behind. Changing two years at once, as the blueprint example did
   (barley to lentil AND rapeseed to wheat), confounds the pulse effect with a
   separate crop switch.

3. Price is drawn negatively correlated with the yield shock, because a bad season
   lifts the price and partly hedges the loss.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import crop, load_ref, pac
from . import ml, nitrogen, prices, quality
from .agronomy import suitability_multiplier

# How much of the legume break-crop yield response the following crop can capture.
# Cereals gain from both the nitrogen and the take-all / grass-weed break; rapeseed
# gains from the nitrogen but shares some soil-borne pathogens, so it captures less.
BREAK_CROP_CAPTURE = {
    "cereal": 1.0, "oilseed": 0.45, "pulse": 0.0, "forage_legume": 0.2,
    # Nothing is harvested on fallow, so a nitrogen credit to it has no cash value.
    "fallow": 0.0,
}


def _pac_coupled_aid(pulse: str, has_livestock: bool) -> tuple[float, str, bool]:
    """Coupled protein aid for this crop, EUR/ha, plus the scheme name."""
    schemes = pac()["coupled_aid"]
    name = crop(pulse).get("pac_coupled_scheme", "legumineuses_a_graines")
    scheme = schemes.get(name, schemes["legumineuses_a_graines"])
    if name == "legumineuses_fourrageres" and not has_livestock:
        scheme = schemes["legumineuses_a_graines"]
        name = "legumineuses_a_graines"
    amount = float(scheme["eur_ha"])
    # The forage-legume route pays more but requires the crop to be harvested as
    # forage, and it cannot be combined with the grain-legume aid on the same hectares.
    if name == "legumineuses_fourrageres" and has_livestock:
        amount = float(scheme.get("eur_ha_with_livestock_contract", amount))
    return amount, name, bool(scheme.get("unit_amount_is_provisional", True))


def _eco_scheme_uplift(baseline_rotation: list[str], pulse: str) -> float:
    """Marginal eco-scheme gain, attributed only when the legume is what crosses the
    diversification threshold. Paid on all eligible hectares, so only the marginal
    uplift belongs to this decision."""
    es = pac()["eco_scheme"]
    families = {crop(c).get("eco_scheme_family") for c in baseline_rotation if c in load_ref("crops")}
    already_diverse = len(families - {None}) >= 3 or "legume" in families
    if already_diverse:
        return 0.0
    return float(es["diversification_points"]["uplift_eur_ha_if_crosses_threshold"])


def _crop_margin(
    rng: np.random.Generator,
    crop_key: str,
    dept: str,
    soil: str,
    season: pd.DataFrame,
    z: np.ndarray,
    *,
    suitability: float = 1.0,
    irrigated: bool = False,
) -> dict:
    """Margin for a straightforward sold-as-one-grade crop, EUR/ha."""
    irr, _ = ml.irrigation_factor(crop_key, irrigated)
    y, q = ml.sample_yields(
        rng, crop_key, dept, soil, season, suitability=suitability * irr, common_shock=z
    )
    p = prices.price_draw(rng, crop_key, len(season), yield_z=z)
    c = prices.cost_draw(rng, crop_key, len(season))
    return {"yield": y, "price": p, "cost": c, "margin": y * p - c, "quantiles": q}


def simulate(
    *,
    dept: str,
    soil: str,
    baseline_rotation: list[str],
    pulse: str,
    seasons: list[pd.DataFrame],
    rng: np.random.Generator,
    has_livestock: bool = False,
    has_cover_crop: bool = True,
    irrigated: bool = False,
    preceding_crop: str | None = None,
    contract: dict | None = None,
    has_optical_sorting_access: bool = True,
    year3_override: str | None = None,
) -> dict:
    """Run the paired three-year simulation. Returns per-hectare arrays and summaries."""
    s1, s2, s3 = seasons
    n = len(s1)

    # One standardised residual shock per YEAR, reused across every crop in that year
    # and across both arms. This is the common-random-numbers trick: it removes the
    # noise that is common to both rotations from the difference.
    z1, z2, z3 = (rng.standard_normal(n) for _ in range(3))

    b1, b2, b3 = baseline_rotation
    y3_crop = year3_override or b3

    # Two separate multipliers on expected yield: the agronomic quality of the
    # preceding crop, and the parcel's water regime versus the mixed irrigated /
    # rain-fed yield that Agreste publishes.
    suit_prec = suitability_multiplier(pulse, preceding_crop or b1)
    irr_factor, irr_note = ml.irrigation_factor(pulse, irrigated)
    suit = suit_prec * irr_factor

    # ---------------- year 1: identical in both arms ------------------------
    m1 = _crop_margin(rng, b1, dept, soil, s1, z1, irrigated=irrigated)

    # ---------------- year 2: the decision ---------------------------------
    base_y2 = _crop_margin(rng, b2, dept, soil, s2, z2, irrigated=irrigated)

    py, pq = ml.sample_yields(
        rng, pulse, dept, soil, s2, suitability=suit, common_shock=z2
    )
    hr = s2["harvest_rain_mm"].to_numpy(dtype=float)
    qinfo = quality.human_grade_probability(
        pulse,
        harvest_rain_mm=float(np.median(hr)),
        may_days_above_20c=float(np.median(s2["may_days_above_20c"])),
        drought_stress_index=float(np.median(s2["drought_stress_index"])),
        jun_heat_days_30c=float(np.median(s2["jun_heat_days_30c"])),
        has_optical_sorting_access=has_optical_sorting_access,
    )
    # Per-draw grading probability, so a wet sampled season really does downgrade.
    p_per_draw = quality.human_grade_probability_vec(
        pulse,
        harvest_rain_mm=hr,
        may_days_above_20c=s2["may_days_above_20c"].to_numpy(dtype=float),
        drought_stress_index=s2["drought_stress_index"].to_numpy(dtype=float),
        jun_heat_days_30c=s2["jun_heat_days_30c"].to_numpy(dtype=float),
        has_optical_sorting_access=has_optical_sorting_access,
    )
    cat = quality.catastrophic_prob_vec(hr)
    frac = quality.sample_human_fraction(rng, p_per_draw, cat)

    if contract and contract.get("contract_price_eur_t"):
        # A forward contract fixes the human-grade price and guarantees the floor, so
        # the farmer's remaining exposure is quantity and grading, not price.
        price_human = np.full(n, float(contract["contract_price_eur_t"]))
        floor = contract.get("fallback_feed_price_eur_t")
        price_feed = (
            np.full(n, float(floor))
            if (contract.get("floor_guaranteed") and floor)
            else prices.price_draw(rng, pulse, n, yield_z=z2, feed=True)
        )
    else:
        price_human = prices.price_draw(rng, pulse, n, yield_z=z2)
        price_feed = prices.price_draw(rng, pulse, n, yield_z=z2, feed=True)

    if has_livestock:
        # A mixed farm does not sell the downgraded fraction at the feed spot price:
        # it feeds it, replacing purchased soybean meal and cereal.
        on_farm = prices.feed_substitution_value(rng, pulse, n)
        price_feed = np.maximum(price_feed, on_farm)

    aid, aid_scheme, aid_provisional = _pac_coupled_aid(pulse, has_livestock)
    eco = _eco_scheme_uplift(baseline_rotation, pulse)
    pulse_cost = prices.cost_draw(rng, pulse, n)
    pulse_revenue = py * (frac * price_human + (1.0 - frac) * price_feed)
    m2_pulse = pulse_revenue - pulse_cost + aid + eco

    # ---------------- year 3: carry-over effects ---------------------------
    base_y3 = _crop_margin(rng, y3_crop, dept, soil, s3, z3, irrigated=irrigated)

    recharge = s3.get("recharge_rain_mm")
    autumn_rain = float(np.median(recharge)) if recharge is not None else 230.0
    credit = nitrogen.residue_n_credit(
        pulse, py, soil, autumn_winter_rain_mm=autumn_rain, has_cover_crop=has_cover_crop
    )
    n_saved_kg = nitrogen.capped_n_saving_kg(credit, y3_crop)
    n_price = nitrogen.n_price_draw(rng, n)
    n_saving_eur = n_saved_kg * n_price

    drought_limited = bool(np.median(s3["drought_stress_index"]) > 1.0) and not irrigated
    capture = BREAK_CROP_CAPTURE.get(crop(y3_crop).get("family", "cereal"), 0.5)
    boost_t = nitrogen.following_yield_boost(pulse, py, drought_limited=drought_limited) * capture
    boost_eur = boost_t * base_y3["price"]

    m3_pulse = base_y3["margin"] + boost_eur + n_saving_eur

    total_base = m1["margin"] + base_y2["margin"] + base_y3["margin"]
    total_pulse = m1["margin"] + m2_pulse + m3_pulse
    delta = total_pulse - total_base

    return {
        "n": n,
        "baseline_total": total_base,
        "pulse_total": total_pulse,
        "delta": delta,
        "year1_margin": m1["margin"],
        "baseline_y2_margin": base_y2["margin"],
        "pulse_y2_margin": m2_pulse,
        "baseline_y3_margin": base_y3["margin"],
        "pulse_y3_margin": m3_pulse,
        "pulse_yield": py,
        "pulse_quantiles": pq,
        "human_fraction": frac,
        "prob_human_grade": p_per_draw,
        "quality_info": qinfo,
        "pulse_revenue": pulse_revenue,
        "pulse_cost": pulse_cost,
        "price_human": price_human,
        "price_feed": price_feed,
        "pac_aid": aid,
        "pac_scheme": aid_scheme,
        "pac_provisional": aid_provisional,
        "eco_uplift": eco,
        "n_saved_kg": n_saved_kg,
        "n_saving_eur": n_saving_eur,
        "wheat_boost_t": boost_t,
        "wheat_boost_eur": boost_eur,
        "suitability": suit,
        "suitability_preceding": suit_prec,
        "irrigation_factor": irr_factor,
        "irrigation_note": irr_note,
        "year3_crop": y3_crop,
        "baseline_y3_yield": base_y3["yield"],
        "on_farm_feed_eur": np.where(
            has_livestock, py * (1.0 - frac) * price_feed, np.zeros(n)
        ),
    }


def summarise(sim: dict) -> dict:
    """Collapse the simulation into the numbers the API reports."""
    d, b, p = sim["delta"], sim["baseline_total"], sim["pulse_total"]
    q = lambda a, x: float(np.quantile(a, x))  # noqa: E731
    tail = d[d <= np.quantile(d, 0.05)]
    return {
        "baseline_median": q(b, 0.5), "baseline_q15": q(b, 0.15), "baseline_q85": q(b, 0.85),
        "pulse_median": q(p, 0.5), "pulse_q15": q(p, 0.15), "pulse_q85": q(p, 0.85),
        "delta_median": q(d, 0.5), "delta_q15": q(d, 0.15), "delta_q85": q(d, 0.85),
        "prob_beats_baseline": float(np.mean(d > 0.0)),
        "cvar_5pct": float(tail.mean()) if len(tail) else q(d, 0.05),
        "prob_delta_below_minus_100": float(np.mean(d < -100.0)),
        "worst_case": float(np.min(d)),
    }


def breakeven_human_fraction(sim: dict) -> float | None:
    """Minimum human-grade share at which the pulse rotation matches the baseline.

    Answers the question an advisor is actually asked: how much of my harvest has to
    make food grade before this is worth doing?
    """
    py, ph, pf = sim["pulse_yield"], sim["price_human"], sim["price_feed"]
    other = (
        sim["pulse_y2_margin"] - sim["pulse_revenue"]
    )  # aid + eco - cost, independent of grading
    shortfall = np.median(
        sim["baseline_y2_margin"] - other - (sim["pulse_y3_margin"] - sim["baseline_y3_margin"])
    )
    spread = np.median(py * (ph - pf))
    base_feed = np.median(py * pf)
    if spread <= 1e-6:
        return None
    f = (shortfall - base_feed) / spread
    return float(np.clip(f, 0.0, 1.0)) if np.isfinite(f) else None


def cumulative_fan(sim: dict) -> list[dict]:
    """Cumulative margin by year for both arms, for the confidence fan chart."""
    out = []
    cum_b = np.zeros(sim["n"])
    cum_p = np.zeros(sim["n"])
    steps = [
        ("Year 1", sim["year1_margin"], sim["year1_margin"]),
        ("Year 2", sim["baseline_y2_margin"], sim["pulse_y2_margin"]),
        ("Year 3", sim["baseline_y3_margin"], sim["pulse_y3_margin"]),
    ]
    for label, mb, mp in steps:
        cum_b = cum_b + mb
        cum_p = cum_p + mp
        out.append({
            "year": label,
            "baseline_median": round(float(np.median(cum_b)), 1),
            "baseline_q15": round(float(np.quantile(cum_b, 0.15)), 1),
            "baseline_q85": round(float(np.quantile(cum_b, 0.85)), 1),
            "pulse_median": round(float(np.median(cum_p)), 1),
            "pulse_q15": round(float(np.quantile(cum_p, 0.15)), 1),
            "pulse_q85": round(float(np.quantile(cum_p, 0.85)), 1),
        })
    return out
