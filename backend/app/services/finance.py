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
from . import logistics, ml, nitrogen, prices, quality
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
    sorter_road_km: float | None = None,
    fallback_feed_floor_eur_t: float | None = None,
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

    if fallback_feed_floor_eur_t:
        # A signed contract with a neighbouring livestock holding does the same job for
        # a farm with no animals of its own, which is most farms with a lot of cereal
        # land. It is a FLOOR, not a replacement: if the open feed market happens to pay
        # better in a given draw, the farmer sells there instead.
        price_feed = np.maximum(price_feed, float(fallback_feed_floor_eur_t))

    aid, aid_scheme, aid_provisional = _pac_coupled_aid(pulse, has_livestock)
    eco = _eco_scheme_uplift(baseline_rotation, pulse)
    pulse_cost = prices.cost_draw(rng, pulse, n)
    pulse_revenue = py * (frac * price_human + (1.0 - frac) * price_feed)
    # Incremental haulage to the nearest optical sorter, charged on food tonnes only.
    # This is what makes distance to infrastructure a financial quantity instead of a
    # label, and therefore what lets a parcel be agronomically ideal and still lose
    # money. The baseline cereal arm hauls to its local silo inside the collection
    # radius already priced into its RICA cost, so nothing is charged there.
    haul = logistics.haulage_cost_eur_ha(py, frac, sorter_road_km)
    m2_pulse = pulse_revenue - pulse_cost - haul + aid + eco

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
        "haulage_eur": haul,
        "sorter_road_km": sorter_road_km,
        "haulage_eur_per_t_food": logistics.food_haulage_eur_per_tonne(sorter_road_km),
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
        # Needed to reprice the break-crop response under alternative pre-crop
        # assumptions without re-simulating; see `precrop_literature_sensitivity`.
        "year3_price": base_y3["price"],
        "year3_capture": capture,
        "n_price": n_price,
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
    # aid + eco - cost: the part of the year-2 margin that does not move with grading.
    # Haulage is added back because it DOES move with grading (it is charged per food
    # tonne), so it belongs in the spread below, not in the fixed term. Leaving it in
    # here would understate the break-even fraction on a distant parcel, which is
    # precisely the case where the answer matters.
    other = sim["pulse_y2_margin"] - sim["pulse_revenue"] + sim["haulage_eur"]
    shortfall = np.median(
        sim["baseline_y2_margin"] - other - (sim["pulse_y3_margin"] - sim["baseline_y3_margin"])
    )
    haul_per_t = float(sim["haulage_eur_per_t_food"])
    spread = np.median(py * (ph - pf - haul_per_t))
    base_feed = np.median(py * pf)
    if spread <= 1e-6:
        return None
    f = (shortfall - base_feed) / spread
    return float(np.clip(f, 0.0, 1.0)) if np.isfinite(f) else None


# Published European pre-crop benefit ranges, from the one systematic review of the
# question: Preissel, Reckling, Schlaefke and Zander (2015), "Magnitude and farm-
# economic value of grain legume pre-crop benefits in Europe: A review", Field Crops
# Research 175:64-79, doi:10.1016/j.fcr.2015.01.012 (29 European experiments on
# following-cereal yield, 19 gross-margin studies).
#
# Two different nitrogen figures in that review answer two different questions, and
# only one of them applies here. 60 kg N/ha is the average reduction compatible with
# "maintenance of acceptable yields"; 23-31 kg N/ha is the reduction compatible with
# "maximising yield potential". This engine assumes a farmer who wants the following
# wheat's full yield, so 23-31 is the applicable band.
PREISSEL_2015 = {
    "doi": "10.1016/j.fcr.2015.01.012",
    "n_reduction_kg_ha_yield_maximising": (23.0, 31.0),
    "n_reduction_kg_ha_acceptable_yields": 60.0,
    "following_cereal_yield_gain_t_ha": (0.5, 1.6),
}


def precrop_literature_sensitivity(sim: dict) -> dict:
    """How much the verdict depends on sitting at the conservative edge of the review.

    The engine's realised nitrogen credit (roughly 5-17 kg N/ha) is BELOW Preissel et
    al.'s yield-maximising band of 23-31, and its following-crop yield response (0.28
    to 0.55 t/ha by legume) sits at or below the bottom of their measured 0.5-1.6 t/ha
    range. That conservatism is defensible - it means no positive result here is
    manufactured by generous pre-crop crediting - but it is not free, because the same
    conservatism pushes marginal cases negative.

    Rather than retune the parameters towards a nicer answer, this reprices the two
    pre-crop terms on the draws already taken and reports what the delta WOULD be at
    the published European bounds. Any gap is a statement about the literature's
    spread, not a correction to apply.
    """
    base_delta = float(np.median(sim["delta"]))
    n_now = float(np.median(sim["n_saved_kg"]))
    n_price = float(np.median(sim["n_price"]))
    y3_price = float(np.median(sim["year3_price"]))
    capture = float(sim["year3_capture"])

    # `wheat_boost_t` is already POST-capture, so it must be grossed back up before
    # being compared against a review figure measured on a following cereal. Comparing
    # the post-capture value directly would double-apply the capture factor and roughly
    # triple the apparent sensitivity.
    boost_now_post = float(np.median(sim["wheat_boost_t"]))
    boost_now_cereal_equiv = boost_now_post / capture if capture > 0 else 0.0

    def repriced(n_kg: float, boost_t_cereal: float) -> float:
        d_n = (n_kg - n_now) * n_price
        # The review range is a following-CEREAL gain; the capture factor converts it
        # to whatever actually follows in year 3 (1.0 for a cereal, 0.45 for an oilseed).
        d_boost = (boost_t_cereal - boost_now_cereal_equiv) * capture * y3_price
        return base_delta + d_n + d_boost

    lo_n, hi_n = PREISSEL_2015["n_reduction_kg_ha_yield_maximising"]
    lo_y, hi_y = PREISSEL_2015["following_cereal_yield_gain_t_ha"]
    mid_n, mid_y = (lo_n + hi_n) / 2.0, (lo_y + hi_y) / 2.0

    scenarios = {
        "engine_as_built": round(base_delta, 1),
        "review_lower_bound": round(repriced(lo_n, lo_y), 1),
        "review_midpoint": round(repriced(mid_n, mid_y), 1),
        "review_upper_bound": round(repriced(hi_n, hi_y), 1),
    }
    return {
        "source": PREISSEL_2015["doi"],
        "engine_n_credit_kg_ha": round(n_now, 1),
        "review_n_band_kg_ha": [lo_n, hi_n],
        "engine_following_crop_gain_t_ha_cereal_equivalent": round(boost_now_cereal_equiv, 3),
        "engine_following_crop_gain_t_ha_as_applied": round(boost_now_post, 3),
        "year3_capture_factor": round(capture, 3),
        "review_following_crop_band_t_ha": [lo_y, hi_y],
        "engine_sits_below_review_on_both": bool(
            n_now < lo_n and boost_now_cereal_equiv < lo_y
        ),
        "median_delta_eur_ha": scenarios,
        "verdict_changes_at_review_midpoint": bool(
            (base_delta <= 0.0) != (scenarios["review_midpoint"] <= 0.0)
        ),
        "interpretation": (
            "The engine credits pre-crop benefits below the published European range. "
            "That protects every positive result from the charge of optimistic "
            "assumptions, and it means marginal negative results should be read as "
            "the conservative end of a real spread, not as a settled verdict."
        ),
    }


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
