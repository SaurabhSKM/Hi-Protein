"""Assembles the full simulate-rotation response from the individual engines."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np

from ..config import DEFAULT_N_SIMULATIONS, crop, crops, departments, load_ref
from ..schemas import (
    AgronomicValidation,
    EnvironmentalImpact,
    Financial3Yr,
    GainBreakdown,
    MLPredictions,
    OfftakeContract,
    Provenance,
    RiskMetrics,
    SimulateRotationRequest,
    SimulateRotationResponse,
    SovereigntyContribution,
)
from . import agronomy, carbon, finance, ml, offtake, quality, weather

_NOW = lambda: datetime.now(UTC).isoformat(timespec="seconds")  # noqa: E731


def national_target() -> dict:
    return load_ref("departments")["_meta"]["national_target"]


def _region_code(dept: str) -> str | None:
    d = departments().get(dept)
    return d.get("region_code") if d else None


def _default_soil(dept: str) -> str:
    d = departments().get(dept)
    return d.get("dominant_soil", "clay_loam") if d else "clay_loam"


def _history(req: SimulateRotationRequest) -> list[str]:
    """Campaigns preceding the YEAR 2 decision, oldest first, most recent last.

    The three crops in `baseline_rotation` are future years, not past ones. The pulse
    goes into year 2, so the crop immediately before it is the year-1 crop, i.e.
    baseline_rotation[0] - never baseline_rotation[-1], which happens a year AFTER the
    decision. Any RPG history supplied sits before year 1.
    """
    past = [c for c in (req.crop_history or []) if c in crops()]
    if not past:
        # With no parcel history, assume the declared rotation ran once before.
        past = list(req.baseline_rotation)
    return past + [req.baseline_rotation[0]]


def run(req: SimulateRotationRequest) -> SimulateRotationResponse:
    t0 = time.perf_counter()
    dept = req.department_code
    soil = req.soil_type or _default_soil(dept)
    pulse = req.candidate_pulse_year2
    if pulse not in crops():
        raise KeyError(f"Unknown crop '{pulse}'")
    n_sim = int(req.n_simulations or DEFAULT_N_SIMULATIONS)
    rng = np.random.default_rng(req.random_seed if req.random_seed is not None else 20260131)

    history = _history(req)
    validation: AgronomicValidation = agronomy.validate(
        pulse,
        history=history,
        baseline_rotation=req.baseline_rotation,
        soil_type=soil,
        soil_ph=req.soil_ph,
        irrigated=req.irrigated,
    )

    has_sorting, sort_km = offtake.optical_sorting_access(dept, None)
    contract = (
        offtake.buyer_by_id(req.selected_buyer_id, pulse) if req.selected_buyer_id else None
    )

    seasons = [weather.sample_seasons(dept, n_sim, rng) for _ in range(3)]
    sim = finance.simulate(
        dept=dept, soil=soil, baseline_rotation=req.baseline_rotation, pulse=pulse,
        seasons=seasons, rng=rng, has_livestock=req.has_livestock_ugb_5,
        has_cover_crop=req.has_cover_crop, irrigated=req.irrigated,
        preceding_crop=req.baseline_rotation[0], contract=contract,
        has_optical_sorting_access=has_sorting,
    )
    s = finance.summarise(sim)

    q = sim["pulse_quantiles"]
    y15, y50, y85 = (
        float(np.median(q["q15"])), float(np.median(q["q50"])), float(np.median(q["q85"]))
    )
    ph = sim["prob_human_grade"]
    frac_med = float(np.median(sim["human_fraction"]))

    baseline_warning = ml.baseline_caveat(pulse, q["baseline_source"])

    imp = ml.bundle()
    drivers = []
    if imp:
        top = sorted(imp["feature_importance"].items(), key=lambda kv: -kv[1])[:6]
        drivers = [{"feature": k, "gain_share": round(float(v), 4)} for k, v in top]

    ml_block = MLPredictions(
        yield_q15_t_ha=round(y15, 3),
        yield_median_t_ha=round(y50, 3),
        yield_q85_t_ha=round(y85, 3),
        prob_human_grade=round(float(np.mean(ph)), 3),
        prob_human_grade_q15=round(float(np.quantile(ph, 0.15)), 3),
        prob_human_grade_q85=round(float(np.quantile(ph, 0.85)), 3),
        human_grade_fraction_median=round(frac_med, 3),
        expected_protein_pct=round(
            quality.expected_protein_pct(pulse, y50 / max(q["baseline"], 0.01)), 1
        ),
        top_drivers=drivers,
        model_version=ml.model_version(),
        provenance=Provenance(
            source=(
                "Quantile XGBoost on Agreste SAA departmental yields (2010-2024) with "
                "Meteo-France phenological windows and lagged department-level legume "
                "rotation pressure (also from Agreste area series), conformalised on a "
                "held-out forward calibration block. Grading probability is a "
                "documented agronomic hazard model, not a trained classifier."
            ),
            mode="model_output" if ml.is_trained() else "assumption",
            retrieved_at=_NOW(),
            caveat=(
                f"Yield baseline from {q['baseline_source']}."
                + (f" {baseline_warning}" if baseline_warning else "")
                + " Training labels are department MEAN yields, so parcel intervals are"
                " widened. The grading probability has no observational labels anywhere"
                " in French open data."
            ),
        ),
    )

    br = GainBreakdown(
        pac_coupled_aid_eur=round(float(sim["pac_aid"]), 1),
        eco_scheme_uplift_eur=round(float(sim["eco_uplift"]), 1),
        nitrogen_saved_year3_eur=round(float(np.median(sim["n_saving_eur"])), 1),
        wheat_yield_boost_year3_eur=round(float(np.median(sim["wheat_boost_eur"])), 1),
        pulse_gross_revenue_eur=round(float(np.median(sim["pulse_revenue"])), 1),
        pulse_operational_cost_eur=round(float(np.median(sim["pulse_cost"])), 1),
        forgone_baseline_year2_margin_eur=round(float(np.median(sim["baseline_y2_margin"])), 1),
        on_farm_feed_substitution_eur=round(float(np.median(sim["on_farm_feed_eur"])), 1),
    )

    risk = RiskMetrics(
        prob_pulse_beats_baseline=round(s["prob_beats_baseline"], 4),
        median_delta_eur_ha=round(s["delta_median"], 1),
        delta_q15_eur_ha=round(s["delta_q15"], 1),
        delta_q85_eur_ha=round(s["delta_q85"], 1),
        cvar_5pct_delta_eur_ha=round(s["cvar_5pct"], 1),
        prob_delta_below_minus_100_eur_ha=round(s["prob_delta_below_minus_100"], 4),
        breakeven_human_grade_fraction=(
            round(v, 3) if (v := finance.breakeven_human_fraction(sim)) is not None else None
        ),
        worst_case_delta_eur_ha=round(s["worst_case"], 1),
    )

    fin = Financial3Yr(
        baseline_3yr_net_margin_eur=round(s["baseline_median"], 1),
        pulse_rotation_median_eur=round(s["pulse_median"], 1),
        pulse_rotation_worst_case_q15_eur=round(s["pulse_q15"], 1),
        baseline_3yr_q15_eur=round(s["baseline_q15"], 1),
        baseline_3yr_q85_eur=round(s["baseline_q85"], 1),
        pulse_rotation_q85_eur=round(s["pulse_q85"], 1),
        breakdown_year2_year3_gains=br,
        risk=risk,
        cumulative_margin_fan=finance.cumulative_fan(sim),
        n_simulations=n_sim,
        provenance=Provenance(
            source=(
                "Paired Monte Carlo over bootstrapped Meteo-France seasons. Both "
                "rotations share the same weather draws and residual shocks, so the "
                "reported figure is the distribution of the DIFFERENCE."
            ),
            mode="model_output",
            retrieved_at=_NOW(),
            caveat=(
                "Operational charges only: land, labour and machinery depreciation are "
                "excluded, so these are gross margins and not farm profit. PAC unit "
                "amounts are provisional and set annually."
            ),
        ),
    )

    env_raw = carbon.impact(
        pulse, y50, float(np.median(sim["n_saved_kg"])), req.area_ha,
        convention=req.carbon_convention,
    )
    # Carbon saved across the WHOLE Monte Carlo sample, not the single yield point
    # above. A bad year that halves the harvest also roughly halves the soy meal it
    # displaces, so the headline tonnage now carries the same q15/q85 band the
    # financial risk metrics do, computed from the identical yield and nitrogen-
    # credit draws finance.py already produced for this request.
    env_dist = carbon.impact_distribution(
        pulse, sim["pulse_yield"], sim["n_saved_kg"], req.area_ha,
        convention=req.carbon_convention,
    )

    # Ties the Costs/Prices/Subsidies layer to the Carbon/LCA layer explicitly: what
    # does this rotation's CO2e reduction cost (or earn) the farmer, in EUR per
    # tonne. The financial delta already carries PAC coupled aid, RICA-consistent
    # operating costs and the correlated market price draws; dividing it by the
    # median tons avoided turns two separately-reported numbers into the one a
    # policymaker or buyer actually asks for.
    delta_total_eur = s["delta_median"] * req.area_ha
    co2e_median = env_dist["co2e_saved_tons_median"]
    abatement_cost = (
        round(-delta_total_eur / co2e_median, 1) if co2e_median > 1e-6 else None
    )

    env = EnvironmentalImpact(
        co2e_saved_tons_total=env_dist["co2e_saved_tons_median"],
        co2e_saved_tons_q15=env_dist["co2e_saved_tons_q15"],
        co2e_saved_tons_q85=env_dist["co2e_saved_tons_q85"],
        co2e_saved_per_kg_protein=env_raw["co2e_saved_per_kg_protein"],
        synthetic_n_reduced_kg_total=env_raw["synthetic_n_reduced_kg_total"],
        co2e_from_n_avoided_tons=env_raw["co2e_from_n_avoided_tons"],
        convention=req.carbon_convention,
        co2e_saved_tons_other_convention=env_dist["co2e_saved_tons_other_convention_median"],
        carbon_abatement_cost_eur_per_tonne=abatement_cost,
        source=env_raw["footprint_provenance"]["source"],
        provenance=Provenance(
            source=env_raw["footprint_provenance"]["source"],
            mode=env_raw["footprint_provenance"]["mode"],
            retrieved_at=env_raw["footprint_provenance"]["retrieved_at"],
            caveat=(
                "Reported per kg of crude protein as well as per tonne, because soybean "
                "meal is twice as protein-dense as a pulse. The headline tonnage and its "
                "q15/q85 band are computed from the same Monte Carlo yield draws as the "
                "financial risk metrics, not from a single point yield. "
                + env_raw["luc_note"]
            ),
        ),
    )

    matches = offtake.match(
        pulse=pulse, dept_code=dept, region_code=_region_code(dept), point=None,
        yield_t_ha=y50, yield_q15_t_ha=y15, prob_human_grade=float(np.mean(ph)),
        human_fraction_median=frac_med, area_ha=req.area_ha,
    )
    contracts = [OfftakeContract(**m) for m in matches]

    d = departments().get(dept)
    if d:
        cur = 100.0 * d["pulse_ha"] / max(d["arable_ha"], 1)
        after = 100.0 * (d["pulse_ha"] + req.area_ha) / max(d["arable_ha"], 1)
        tgt = float(national_target()["target_pulse_share_pct"])
        gap_ha = max(d["arable_ha"] * tgt / 100.0 - d["pulse_ha"], 1.0)
        sov = SovereigntyContribution(
            department_code=dept, department_name=d["name"],
            current_pulse_share_pct=round(cur, 3),
            share_after_this_parcel_pct=round(after, 3),
            parcel_share_of_dept_gap_pct=round(100.0 * req.area_ha / gap_ha, 4),
            national_target_pct=tgt,
        )
    else:
        sov = SovereigntyContribution(
            department_code=dept, department_name="Unknown", current_pulse_share_pct=0.0,
            share_after_this_parcel_pct=0.0, parcel_share_of_dept_gap_pct=0.0,
            national_target_pct=8.0,
        )

    assumptions = [
        f"Only year 2 changes. Year 3 stays {crops()[sim['year3_crop']]['label_fr']} in both "
        "rotations and differs only by the nitrogen credit and break-crop response.",
        f"Pulse yield expectation carries a preceding-crop suitability of "
        f"{sim['suitability_preceding']:.2f} and a water-regime factor of "
        f"{sim['irrigation_factor']:.2f} ({sim['irrigation_note']}).",
        f"PAC coupled aid of {sim['pac_aid']:.0f} EUR/ha under the "
        f"'{sim['pac_scheme']}' scheme. Unit amounts are provisional and fixed annually "
        "once declared area is known.",
        "Margins are operational gross margins. Land, labour and machinery depreciation "
        "are excluded, as is any change in workload or equipment the switch requires.",
        sim["quality_info"]["note"],
    ]
    if baseline_warning:
        assumptions.insert(0, baseline_warning)
    if not has_sorting:
        assumptions.append(
            f"No optical sorting unit within {sort_km:.0f} km. The achievable human-grade "
            "share is capped accordingly, and sorting premiums are not available."
        )
    if validation.severity == "blocked":
        assumptions.insert(
            0,
            "AGRONOMICALLY BLOCKED. The financial figures below are shown for comparison "
            "only and must not be acted on until the blocking condition is resolved.",
        )

    whole = {
        k: round(v * req.area_ha, 1)
        for k, v in {
            "baseline_3yr_net_margin_eur": s["baseline_median"],
            "pulse_rotation_median_eur": s["pulse_median"],
            "delta_median_eur": s["delta_median"],
            "delta_q15_eur": s["delta_q15"],
            "delta_q85_eur": s["delta_q85"],
            "cvar_5pct_eur": s["cvar_5pct"],
        }.items()
    }

    return SimulateRotationResponse(
        crop_recommended=pulse,
        crop_label_fr=crop(pulse)["label_fr"],
        area_ha=req.area_ha,
        agronomic_validation=validation,
        ml_predictions_year2=ml_block,
        financial_3yr_comparison_per_ha=fin,
        financial_3yr_whole_parcel_eur=whole,
        environmental_impact=env,
        matched_offtake_contracts=contracts,
        sovereignty=sov,
        alternatives=[],
        assumptions=assumptions,
        compute_ms=round(1000 * (time.perf_counter() - t0), 1),
    )


def rank_candidates(req: SimulateRotationRequest) -> list[dict]:
    """Score every eligible pulse for this parcel, cheaply, and rank them.

    This is the question a farmer actually starts from: not "is lentil good" but
    "which pulse, if any, fits my field". Running the full engine per candidate with a
    shared seed keeps the comparison apples-to-apples.
    """
    from ..config import pulse_crops

    out = []
    for cand in pulse_crops():
        sub = req.model_copy(
            update={
                "candidate_pulse_year2": cand,
                "n_simulations": min(int(req.n_simulations or DEFAULT_N_SIMULATIONS), 1200),
                "random_seed": req.random_seed if req.random_seed is not None else 20260131,
            }
        )
        try:
            r = run(sub)
        except (KeyError, ValueError, RuntimeError):
            continue
        risk = r.financial_3yr_comparison_per_ha.risk
        out.append({
            "crop": cand,
            "label_fr": r.crop_label_fr,
            "agronomic_severity": r.agronomic_validation.severity,
            "is_valid": r.agronomic_validation.is_valid,
            "blocking_reasons": r.agronomic_validation.blocking_reasons,
            "yield_median_t_ha": r.ml_predictions_year2.yield_median_t_ha,
            "yield_q15_t_ha": r.ml_predictions_year2.yield_q15_t_ha,
            "prob_human_grade": r.ml_predictions_year2.prob_human_grade,
            "median_delta_eur_ha": risk.median_delta_eur_ha,
            "delta_q15_eur_ha": risk.delta_q15_eur_ha,
            "prob_beats_baseline": risk.prob_pulse_beats_baseline,
            "cvar_5pct_eur_ha": risk.cvar_5pct_delta_eur_ha,
            "co2e_saved_tons_total": r.environmental_impact.co2e_saved_tons_total,
            "best_buyer": (
                r.matched_offtake_contracts[0].buyer_name
                if r.matched_offtake_contracts else None
            ),
            "best_contract_price_eur_t": (
                r.matched_offtake_contracts[0].contract_price_eur_t
                if r.matched_offtake_contracts else None
            ),
        })
    # Blocked candidates sink to the bottom whatever their margin looks like.
    out.sort(key=lambda r: (r["agronomic_severity"] == "blocked", -r["median_delta_eur_ha"]))
    return out
