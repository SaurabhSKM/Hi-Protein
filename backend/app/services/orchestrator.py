"""Assembles the full simulate-rotation response from the individual engines."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np

from ..config import DEFAULT_N_SIMULATIONS, crop, crops, departments, load_ref
from ..schemas import (
    AgronomicValidation,
    BreederFallback,
    ClimateContext,
    EnvironmentalImpact,
    Financial3Yr,
    FoodOutcome,
    GainBreakdown,
    MLPredictions,
    OfftakeContract,
    Provenance,
    RiskMetrics,
    RiskPreference,
    SimulateRotationRequest,
    SimulateRotationResponse,
    SorterAccess,
    SovereigntyContribution,
)
from . import (
    agronomy,
    breeders,
    carbon,
    climate,
    demand,
    finance,
    logistics,
    ml,
    offtake,
    quality,
    robustness,
    rotations,
    weather,
)
from . import risk as riskmod

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

    # Haulage distance is measured from the clicked parcel when there is one, and from
    # the department centroid otherwise. Both are reported, because a parcel at the far
    # edge of a department can be stranded while the department centroid is not.
    point = (req.lon, req.lat) if (req.lon is not None and req.lat is not None) else None
    acc = logistics.access(point or tuple(departments()[dept]["centroid"]))
    has_sorting, sort_km = acc["within_range"], acc["road_km"]
    contract = (
        offtake.buyer_by_id(req.selected_buyer_id, pulse) if req.selected_buyer_id else None
    )

    horizon = req.climate_horizon or "observed"
    seasons = [
        weather.sample_seasons(dept, n_sim, rng, climate_horizon=horizon) for _ in range(3)
    ]
    sim_kwargs = dict(
        dept=dept, soil=soil, baseline_rotation=req.baseline_rotation, pulse=pulse,
        seasons=seasons, has_livestock=req.has_livestock_ugb_5,
        has_cover_crop=req.has_cover_crop, irrigated=req.irrigated,
        preceding_crop=req.baseline_rotation[0], contract=contract,
        has_optical_sorting_access=has_sorting, sorter_road_km=sort_km,
    )
    # Snapshotted so the fallback-contract variant can be run on the IDENTICAL draws
    # further down. Re-seeding from req.random_seed would not do it: the weather
    # bootstrap above has already consumed part of this generator's stream.
    rng_state = rng.bit_generator.state
    sim = finance.simulate(rng=rng, **sim_kwargs)
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
        sorter_haulage_cost_eur=round(float(np.median(sim["haulage_eur"])), 1),
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
        robustness=robustness.assess(sim, sort_km),
    )

    # Applying a risk preference, not just reporting risk. The contract search runs
    # without an assumed price floor, which is the conservative reading: the farmer
    # keeps full feed-market exposure on the downgraded fraction.
    risk_pref = RiskPreference(
        method=(
            "Stochastic efficiency with respect to a function (SERF), negative "
            "exponential utility, relative risk aversion on the Anderson-Dillon scale "
            "anchored on this parcel's own three-year margin. Hardaker et al. (2004), "
            "doi:10.1111/j.1467-8489.2004.00239.x."
        ),
        wealth_anchor_eur_ha=round(riskmod.wealth_anchor(sim), 1),
        risk_sharing=riskmod.risk_sharing_diagnostic(sim),
        serf_curve=riskmod.serf_curve(sim),
        tolerance_threshold=riskmod.risk_tolerance_threshold(sim),
        minimum_viable_contract=riskmod.minimum_viable_contract(sim, rra=2.0),
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
        risk_preference=risk_pref,
        precrop_literature_sensitivity=finance.precrop_literature_sensitivity(sim),
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

    # ------------------------------------------------------------------ #
    # What of this harvest people in France actually eat.
    #
    # The block the brief turns on. Two multiplications separate "tonnes grown" from
    # "tonnes eaten": the lot-level grading fraction the quality model already samples
    # per draw, and the crop's structural human-food market share. Both are reported,
    # because a reader who sees only the product cannot tell a well-graded fava bean
    # (little food demand) from a well-graded lentil (almost all food).
    # ------------------------------------------------------------------ #
    food_share = demand.food_market_share(pulse)
    harvest_t_draws, food_t_draws, feed_t_draws = demand.split_food_feed(
        pulse, sim["pulse_yield"], sim["human_fraction"], req.area_ha
    )
    food_t_med = float(np.quantile(food_t_draws, 0.50))
    food_t_q15 = float(np.quantile(food_t_draws, 0.15))
    food_t_q85 = float(np.quantile(food_t_draws, 0.85))

    protein_pct = float(crop(pulse).get("protein_pct_dm", 22.0)) / 100.0
    premium = float(np.median(sim["price_human"] - sim["price_feed"]))
    # Revenue per hectare that GRADING risk puts in play, as distinct from price or
    # yield risk. This is the quantity the whole quality model exists to estimate.
    grading_var = y50 * premium * (1.0 - float(np.mean(ph)))

    food_env = carbon.food_tier_impact(
        pulse, food_t_med, food_grade_tonnes_q15=food_t_q15, food_grade_tonnes_q85=food_t_q85
    )

    food = FoodOutcome(
        harvest_tonnes_median=round(float(np.quantile(harvest_t_draws, 0.50)), 2),
        food_grade_tonnes_median=round(food_t_med, 2),
        food_grade_tonnes_q15=round(food_t_q15, 2),
        food_grade_tonnes_q85=round(food_t_q85, 2),
        food_market_share=round(food_share, 3),
        human_grade_fraction_median=round(frac_med, 3),
        prob_human_grade=round(float(np.mean(ph)), 3),
        food_grade_protein_tonnes_median=round(food_t_med * protein_pct, 2),
        people_fed_at_current_intake=round(demand.people_fed(food_t_med), 0),
        people_fed_at_recommended_intake=round(
            demand.people_fed(food_t_med, at_recommended=True), 0
        ),
        feed_fallback_tonnes_median=round(float(np.quantile(feed_t_draws, 0.50)), 2),
        food_grade_price_premium_eur_t=round(premium, 1),
        value_at_risk_from_grading_eur_ha=round(grading_var, 1),
        imported_pulse_displaced_tonnes=food_env["imported_pulse_displaced_tonnes"],
        import_origin_displaced=food_env["import_origin_displaced"],
        transport_co2e_saved_tonnes=food_env["transport_co2e_saved_tonnes"],
        crop_food_note=demand.crop_food_note(pulse),
        provenance=Provenance(
            source=(
                "Grading fraction from the engine's own hazard model, sampled per Monte "
                "Carlo draw; human-food market share from refdata/food_demand.json, "
                "consistent with published French market balances; people-fed conversion "
                "from INSEE population and the PNNS twice-weekly pulse recommendation."
            ),
            mode="model_output",
            retrieved_at=_NOW(),
            caveat=(
                "The grading probability has no observational labels anywhere in French "
                "open data, so it is a documented hazard model rather than a trained "
                "classifier - and it is the term this block is most sensitive to. "
                "Per-lot grading records from a cooperative silo would replace it with a "
                "measurement. People-fed is reported at both today's intake and the "
                "recommended intake, which differ by a factor of three."
            ),
        ),
    )

    clim = ClimateContext(
        **climate.horizon_detail(horizon),
        provenance=Provenance(
            source=(
                "Delta-change projection. Observed department-seasons are resampled as "
                "usual, then shifted by each variable's sensitivity to temperature as "
                "MEASURED in this project's own Meteo-France panel, times the warming "
                "increment of the TRACC reference trajectory for France."
            ),
            mode="model_output" if horizon != "observed" else "cached",
            retrieved_at=_NOW(),
            caveat=climate.spec()["_meta"]["caveat"],
        ),
    )

    d = departments().get(dept)
    nat = demand.national()
    psn = demand.ref()["self_sufficiency_targets"]["psn_area_target"]
    # The two target statements are kept apart on purpose. `national_target_pct` is
    # this dashboard's own metric - grain pulses as a share of ARABLE land - and was
    # being read as the official one. The PSN target is 8 percent of SAU, which
    # includes permanent grassland, over a baseline that is 53 percent forage legumes.
    # Reporting both with their denominators named is the only way neither gets
    # mistaken for the other.
    tgt_basis = (
        "Grain pulses as a share of ARABLE land in this department. This dashboard's "
        "own metric, not the PSN target."
    )
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
            target_basis=tgt_basis,
            target_denominator="arable_ha",
            official_psn_target=psn,
            food_tier_self_sufficiency_pct=nat["self_sufficiency_current_pct"],
        )
    else:
        sov = SovereigntyContribution(
            department_code=dept, department_name="Unknown", current_pulse_share_pct=0.0,
            share_after_this_parcel_pct=0.0, parcel_share_of_dept_gap_pct=0.0,
            national_target_pct=8.0,
            target_basis=tgt_basis,
            target_denominator="arable_ha",
            official_psn_target=psn,
            food_tier_self_sufficiency_pct=nat["self_sufficiency_current_pct"],
        )

    assumptions = [
        # Leads on the food outcome because that is the question being answered: of
        # what this parcel grows, how much reaches a French plate, and what the
        # difference between the two prices is worth.
        f"Of the harvest, {100 * food_share:.0f}% of the crop has a human-food outlet at "
        f"all and {frac_med:.0%} of a lot is expected to clear retail specification, so "
        f"about {food_t_med:.1f} t of this parcel is food for people - the annual pulse "
        f"intake of {demand.people_fed(food_t_med, at_recommended=True):,.0f} people at the "
        f"twice-weekly level public nutrition advice recommends. The rest goes to feed. "
        f"The food-versus-feed price gap is {premium:.0f} EUR/t, which is why the grading "
        f"probability is the most consequential number in this response.",
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

    # The year-2 BASELINE crop is what the pulse displaces, and its margin is the
    # largest single term in the reported difference. Two things about it were silent
    # before: which crop it is, and whether the engine has real yield data for it.
    # `ml.baseline_caveat` was only ever applied to the pulse, so a baseline crop
    # resting on a hand-written national constant looked exactly as solid as one with
    # its own Agreste series.
    y2_crop = req.baseline_rotation[1]
    _, y2_src = ml.baseline_yield(y2_crop, dept, soil)
    assumptions.append(
        f"The pulse is compared against {crops()[y2_crop]['label_fr']} in year 2. That "
        f"forgone margin is the largest single term in the difference below, so the "
        f"comparison is only as good as the crop it is made against."
    )
    if y2_src == "crop_reference_table":
        assumptions.insert(
            0,
            f"WEAK COMPARATOR. {crops()[y2_crop]['label_fr']} has no Agreste yield "
            f"history in this project, so the year-2 margin it is being compared "
            f"against comes from a hand-written national reference value with no "
            f"departmental signal - the same number in every department on this soil. "
            f"Since that forgone margin is the biggest term in the result, prefer a "
            f"year-2 crop with its own local series "
            f"({rotations.displaced_crop(dept)} is the best-evidenced choice here).",
        )
    elif (rot_caveat := rotations.caveat(dept)) and y2_crop == rotations.displaced_crop(dept):
        assumptions.append(rot_caveat)
    if horizon != "observed":
        assumptions.insert(
            1,
            f"Climate horizon '{horizon}' ({clim.label_en}): every sampled season is "
            f"shifted by {clim.total_shift_applied_c:+.2f} C, of which "
            f"{clim.window_catchup_applied_c:+.2f} C is a measured correction for the "
            "bootstrap window sitting below the last decade and the rest is projected "
            "warming. Yield and grading relationships were calibrated on the observed "
            "record and are extrapolated here, so treat this as a screening projection.",
        )
    if not has_sorting:
        assumptions.append(
            f"No optical sorting unit within {sort_km:.0f} km. The achievable human-grade "
            "share is capped accordingly, and sorting premiums are not available - so "
            "this is a direct, fundable cap on how much of the crop can feed people."
        )
    if validation.severity == "blocked":
        assumptions.insert(
            0,
            "AGRONOMICALLY BLOCKED. The financial figures below are shown for comparison "
            "only and must not be acted on until the blocking condition is resolved.",
        )

    # ------------------------------------------------------------------ #
    # Infrastructure access, as a cost rather than a flag.
    # ------------------------------------------------------------------ #
    haul_med = float(np.median(sim["haulage_eur"]))
    inc_km = logistics.incremental_km(sort_km)
    sorter = SorterAccess(
        nearest_unit_name=acc["nearest_unit_name"],
        nearest_unit_dept=acc["nearest_unit_dept"],
        road_km=acc["road_km"],
        within_range=acc["within_range"],
        max_distance_km=acc["max_distance_km"],
        incremental_km_charged=round(inc_km, 1),
        haulage_eur_per_tonne_food=round(float(sim["haulage_eur_per_t_food"]), 2),
        haulage_cost_eur_ha_median=round(haul_med, 1),
        haulage_cost_eur_whole_parcel=round(haul_med * req.area_ha, 0),
        # "Stranded" is a conditional, not a description of this result: the pulse
        # loses money here AND the only reason is the haul. If it would lose money with
        # a sorter next door, the limit is agronomy or market, and capital cannot fix it.
        is_stranded=bool(s["delta_median"] < 0 <= s["delta_median"] + haul_med),
        stranded_note=(
            f"Stranded potential: this parcel loses {abs(s['delta_median']):.0f} EUR/ha "
            f"against cereals, and {haul_med:.0f} EUR/ha of that is haulage to a sorter "
            f"{acc['road_km']:.0f} km away. A nearer unit turns this parcel positive."
            if bool(s["delta_median"] < 0 <= s["delta_median"] + haul_med)
            else (
                f"Haulage to the nearest optical sorter costs "
                f"{haul_med:.0f} EUR/ha here, which is not what decides this parcel."
            )
        ),
        measured_from="clicked_parcel" if point else "department_centroid",
        provenance=Provenance(
            source=(
                "Optical sorting unit locations from refdata/buyers.json; haulage rate "
                "and road detour factor from refdata/logistics.json. Distance is "
                "great-circle inflated by a 1.32 detour factor, not routed."
            ),
            mode="reference_table",
            retrieved_at=_NOW(),
            caveat=(
                "Only the haul BEYOND the ordinary 25 km collection radius is charged, "
                "because the first 25 km is already inside the RICA operating cost both "
                "rotations carry. A routed distance matrix would replace the detour factor."
            ),
        ),
    )

    # ------------------------------------------------------------------ #
    # The fallback contract, priced on both sides of the trade.
    # ------------------------------------------------------------------ #
    downgraded_t = float(
        np.median(sim["pulse_yield"] * (1.0 - sim["human_fraction"]))
    ) * req.area_ha
    bm = breeders.match(
        pulse=pulse, dept_code=dept, point=point, downgraded_lot_t=downgraded_t
    )
    floor = breeders.fallback_floor_eur_t(pulse, bm["available"])
    # Identical draws, the only difference being the contract. The generator is rewound
    # to the state it had before the main run, so the before/after pair is a controlled
    # comparison: any difference between the two numbers is the contract and nothing
    # else. `sim` itself IS the "without" arm, so only one extra simulation is needed.
    sim_without = sim if floor else None
    sim_with = None
    if floor:
        rng_rewound = np.random.default_rng()
        rng_rewound.bit_generator.state = rng_state
        sim_with = finance.simulate(
            rng=rng_rewound, fallback_feed_floor_eur_t=floor, **sim_kwargs
        )
    fallback = BreederFallback(
        **{
            k: v
            for k, v in breeders.summarise_for_api(
                pulse=pulse, dept_code=dept, point=point,
                downgraded_lot_t=downgraded_t,
                sim_without=sim_without, sim_with=sim_with,
                crop_label=crop(pulse)["label_fr"],
            ).items()
            if k in BreederFallback.model_fields
        },
        provenance=Provenance(
            source=(
                "Livestock holding directory in refdata/breeders.json: real IGN commune "
                "locations, holding count scaled by each department's measured non-COP "
                "cadastral share, individual holdings illustrative. Substitution ratios "
                "and reference feed prices from refdata/feed_substitution.json."
            ),
            mode="reference_table",
            retrieved_at=_NOW(),
            caveat=(
                "The holdings are not a real register, so the names and herd sizes are "
                "illustrative; the distances and the substitution economics are not. The "
                "surplus split between farmer and breeder is a stated negotiating "
                "assumption, and both sides of it are reported."
            ),
        ),
    )
    if fallback.available and fallback.cvar_improvement_eur_ha:
        assumptions.append(
            f"A fallback contract with a livestock holding inside "
            f"{fallback.search_radius_km:.0f} km lifts the one-in-seven bad year by "
            f"{fallback.cvar_improvement_eur_ha:+.0f} EUR/ha. It is a FLOOR on the "
            "downgraded fraction, not a replacement for the food market, and it is not "
            "applied to the headline figures above unless you select it."
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
        sorter_access=sorter,
        breeder_fallback=fallback,
        food_outcome=food,
        climate_context=clim,
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
