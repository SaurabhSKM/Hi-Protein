"""Tests for the food-demand layer and the forward climate projection.

Two things these tests are really guarding:

1. **The 'observed' horizon must be a no-op.** Adding projections cannot silently move
   the numbers the engine already published, so the default path is pinned against a
   request that does not mention climate at all.

2. **The food/feed split must be exhaustive and bounded.** Tonnes eaten plus tonnes fed
   has to equal tonnes grown, or the headline "this parcel feeds N people" is inventing
   mass.
"""
import numpy as np
import pytest
from app.main import app
from app.schemas import SimulateRotationRequest
from app.services import carbon, climate, demand, orchestrator, weather
from fastapi.testclient import TestClient

BASE = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _req(**kw):
    base = dict(
        department_code="28", area_ha=45.0, soil_type="deep_loam",
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        candidate_pulse_year2="green_lentil", n_simulations=400, random_seed=7,
    )
    base.update(kw)
    return SimulateRotationRequest(**base)


# --------------------------------------------------------------------------- #
# Demand arithmetic
# --------------------------------------------------------------------------- #
def test_recommended_intake_is_derived_not_stored():
    """2 servings a week x 52 weeks x 60 g dry = 6.24 kg a year."""
    assert demand.recommended_intake_kg_per_capita() == pytest.approx(6.24, abs=1e-9)


def test_recommended_intake_is_about_three_times_current():
    n = demand.national()
    ratio = (
        n["recommended_intake_kg_per_capita_year"] / n["current_intake_kg_per_capita_year"]
    )
    assert 2.5 < ratio < 3.5


def test_national_self_sufficiency_matches_the_official_one_third_statement():
    """The France Strategie evaluation puts the human-consumption tier at about a third.

    Our figure is derived from a different pair of anchors - population times intake
    against DGPE legumes secs production - so landing in the same region is a real
    cross-check rather than a restatement.
    """
    n = demand.national()
    assert 30.0 <= n["self_sufficiency_current_pct"] <= 55.0
    # And at the recommended intake it must be far worse, not better.
    assert n["self_sufficiency_at_recommended_pct"] < n["self_sufficiency_current_pct"]


def test_food_tier_area_fell_between_2020_and_2022():
    """Pinned because it is the premise of the whole re-pointing: the human-food tier
    is the part of the national target that went backwards."""
    n = demand.national()
    assert n["area_trend"]["change_pct"] < -20.0


def test_food_market_share_ranks_crops_sensibly():
    """Lentil is essentially a food crop; fava bean essentially is not."""
    assert demand.food_market_share("green_lentil") > 0.9
    assert demand.food_market_share("chickpea") > 0.85
    assert demand.food_market_share("fava_bean") < 0.3
    assert demand.food_market_share("green_lentil") > demand.food_market_share("field_pea")
    assert demand.food_market_share("not_a_crop") == 0.0


def test_people_fed_is_lower_at_the_recommended_intake():
    t = 100.0
    assert demand.people_fed(t) > demand.people_fed(t, at_recommended=True)


def test_catering_scales_with_population_not_invented_per_region():
    nat = demand.catering()
    reg = demand.catering(6.15)
    # Tolerance covers the reported rounding to whole tonnes, not a modelling choice.
    assert reg["all_collective_catering_t"] == pytest.approx(
        nat["all_collective_catering_t"] * 6.15 / 68.5, abs=1.0
    )


def test_region_balance_coverage_is_consistent_with_its_inputs():
    b = demand.balance("FRJ2", 6000.0)
    assert b is not None
    assert b["coverage_of_current_demand_pct"] == pytest.approx(
        100.0 * 6000.0 / b["current_demand_t"], abs=0.05
    )
    assert b["deficit_vs_current_t"] == pytest.approx(
        max(b["current_demand_t"] - 6000.0, 0.0), abs=1.0
    )
    assert demand.balance("NOT_A_REGION", 1.0) is None


# --------------------------------------------------------------------------- #
# Climate projection
# --------------------------------------------------------------------------- #
def test_observed_horizon_applies_no_shift_at_all():
    assert climate.delta_c("observed") == pytest.approx(0.0, abs=1e-12)


def test_every_other_horizon_warms_monotonically():
    order = ["observed", "present", "tracc_2030", "tracc_2050", "tracc_2100"]
    shifts = [climate.delta_c(h) for h in order]
    assert shifts == sorted(shifts)
    assert shifts[-1] > shifts[0] + 2.0


def test_bootstrap_window_is_measurably_cooler_than_the_recent_decade():
    """Not an assumption: the sampled climate really has already passed."""
    assert 0.05 < climate.fit()["window_catchup_c"] < 1.0


def test_unknown_horizon_raises():
    with pytest.raises(KeyError):
        climate.delta_c("rcp_8_5_2300")


def test_thermal_variables_are_projected_and_harvest_rain_is_not():
    """The substantive result: what warming threatens is insect pressure, not wet
    harvests. Harvest rain has effectively no temperature response in the observed
    record, so the engine must refuse to give it a trend rather than extrapolate noise.
    """
    s = climate.fit()["sensitivity"]
    assert s["may_days_above_20c"]["applied"] is True
    assert s["may_days_above_20c"]["per_degree_c"] > 2.0
    assert s["jun_heat_days_30c"]["applied"] is True
    assert s["harvest_rain_mm"]["applied"] is False
    assert s["harvest_rain_mm"]["per_degree_c"] == 0.0
    assert abs(s["harvest_rain_mm"]["r"]) < climate.fit()["min_abs_correlation_to_project"]


def test_shift_moves_heat_days_up_and_leaves_harvest_rain_alone():
    rng = lambda: np.random.default_rng(11)  # noqa: E731
    obs = weather.sample_seasons("28", 1500, rng(), climate_horizon="observed")
    hot = weather.sample_seasons("28", 1500, rng(), climate_horizon="tracc_2050")
    assert hot["may_days_above_20c"].mean() > obs["may_days_above_20c"].mean() + 2.0
    assert hot["jun_heat_days_30c"].mean() > obs["jun_heat_days_30c"].mean()
    assert hot["harvest_rain_mm"].mean() == pytest.approx(
        obs["harvest_rain_mm"].mean(), rel=1e-9
    )
    # Warming dries the flowering window through evapotranspiration.
    assert (
        hot["flowering_water_balance_mm"].mean() < obs["flowering_water_balance_mm"].mean()
    )


def test_shifted_season_stays_internally_consistent():
    """A water balance must still equal its own rain minus its own ETP after the shift,
    or the projected season is no longer the kind of object the model was trained on."""
    s = weather.sample_seasons(
        "28", 500, np.random.default_rng(5), climate_horizon="tracc_2100"
    )
    np.testing.assert_allclose(
        s["flowering_water_balance_mm"].to_numpy(),
        (s["flowering_rain_mm"] - s["flowering_etp_mm"]).to_numpy(),
        rtol=1e-9,
    )
    np.testing.assert_allclose(
        s["drought_stress_index"].to_numpy(),
        (-s["flowering_water_balance_mm"] / s["reserve_utile_mm"].clip(lower=40.0)).to_numpy(),
        rtol=1e-9,
    )


def test_day_counts_stay_inside_their_calendar_month():
    s = weather.sample_seasons(
        "32", 800, np.random.default_rng(2), climate_horizon="tracc_2100"
    )
    assert s["may_days_above_20c"].max() <= 31.0
    assert s["jun_heat_days_30c"].max() <= 30.0
    assert s["apr_frost_days"].min() >= 0.0
    for c in ("harvest_rain_mm", "flowering_rain_mm", "flowering_etp_mm"):
        assert s[c].min() >= 0.0


# --------------------------------------------------------------------------- #
# The food outcome block
# --------------------------------------------------------------------------- #
def test_observed_horizon_reproduces_the_unprojected_response_exactly():
    """The backward-compatibility guarantee. A request that never mentions climate and
    one that asks for 'observed' must agree to the last decimal."""
    a = orchestrator.run(_req())
    b = orchestrator.run(_req(climate_horizon="observed"))
    assert (
        a.financial_3yr_comparison_per_ha.risk.median_delta_eur_ha
        == b.financial_3yr_comparison_per_ha.risk.median_delta_eur_ha
    )
    assert a.ml_predictions_year2.yield_median_t_ha == b.ml_predictions_year2.yield_median_t_ha
    assert a.food_outcome.food_grade_tonnes_median == b.food_outcome.food_grade_tonnes_median


def test_food_and_feed_account_for_the_whole_harvest_draw_by_draw():
    """No mass is invented or lost by the food/feed split.

    Tested on the arrays rather than on the reported medians, because medians do not
    add: the median food tonnage plus the median feed tonnage is not the median
    harvest. The identity that actually has to hold is per draw.
    """
    y = np.array([0.0, 1.2, 1.45, 2.0, 3.3])
    frac = np.array([0.0, 0.25, 0.6, 0.95, 1.0])
    harvest, food, feed = demand.split_food_feed("green_lentil", y, frac, 45.0)
    np.testing.assert_allclose(food + feed, harvest, rtol=1e-12)
    np.testing.assert_allclose(harvest, y * 45.0, rtol=1e-12)
    assert (food >= 0).all() and (feed >= 0).all()
    assert (food <= harvest + 1e-12).all()


def test_reported_food_tonnage_never_exceeds_the_harvest():
    r = orchestrator.run(_req())
    f = r.food_outcome
    assert f.harvest_tonnes_median > 0
    assert f.food_grade_tonnes_q85 <= f.harvest_tonnes_median * 1.6, (
        "an upper food quantile far above the median harvest would mean the split is "
        "not being applied to the same draws as the yield"
    )
    assert f.food_grade_tonnes_median <= f.harvest_tonnes_median + 1e-9
    assert f.feed_fallback_tonnes_median <= f.harvest_tonnes_median + 1e-9


def test_food_tonnage_quantiles_are_ordered():
    f = orchestrator.run(_req()).food_outcome
    assert f.food_grade_tonnes_q15 <= f.food_grade_tonnes_median <= f.food_grade_tonnes_q85


def test_food_tonnage_is_bounded_by_both_multipliers():
    """Two independent ceilings apply, and both must bind: the lot grading fraction and
    the crop's structural food-market share."""
    r = orchestrator.run(_req(candidate_pulse_year2="fava_bean"))
    f = r.food_outcome
    grown = r.ml_predictions_year2.yield_median_t_ha * r.area_ha
    assert f.food_market_share < 0.3
    assert f.food_grade_tonnes_median <= grown * f.food_market_share + 1e-6


def test_lentil_feeds_far_more_people_per_hectare_than_fava_bean():
    """Even though fava out-yields lentil threefold, almost none of it is human food.
    This is the comparison the old feed-sovereignty framing could not express."""
    lentil = orchestrator.run(_req(candidate_pulse_year2="green_lentil")).food_outcome
    fava = orchestrator.run(_req(candidate_pulse_year2="fava_bean")).food_outcome
    assert (
        lentil.people_fed_at_recommended_intake > fava.people_fed_at_recommended_intake
    )


def test_grading_premium_and_value_at_risk_are_positive_for_a_food_pulse():
    f = orchestrator.run(_req(candidate_pulse_year2="green_lentil")).food_outcome
    assert f.food_grade_price_premium_eur_t > 200.0
    assert f.value_at_risk_from_grading_eur_ha > 0.0


def test_losing_sorting_access_cuts_the_food_that_reaches_people():
    """The infrastructure gap has to show up in tonnes of food, not just in euros.

    Department 86 has no optical sorting within 80 km; department 28 does. Same crop,
    same soil, same seed.
    """
    with_sort = orchestrator.run(_req(department_code="28")).food_outcome
    without = orchestrator.run(_req(department_code="86")).food_outcome
    assert without.prob_human_grade < with_sort.prob_human_grade


def test_warming_degrades_the_food_fraction_of_a_bruchid_sensitive_crop():
    now = orchestrator.run(_req(candidate_pulse_year2="green_lentil")).food_outcome
    later = orchestrator.run(
        _req(candidate_pulse_year2="green_lentil", climate_horizon="tracc_2100")
    ).food_outcome
    assert later.prob_human_grade < now.prob_human_grade
    assert later.food_grade_tonnes_median < now.food_grade_tonnes_median


def test_food_tier_carbon_is_transport_only_and_small():
    """A deliberately modest claim. The food-tier counterfactual is an imported pulse,
    and only the transport differential is defensible from open data - so the headline
    for this tier is the displaced TONNAGE, not the carbon."""
    per_kg = carbon.imported_food_pulse_saving_per_kg("green_lentil")
    assert 0.0 < per_kg["kg_co2e_saved_per_kg"] < 0.244, (
        "must stay below the Agribalyse retail-transport figure it is cross-checked against"
    )
    assert "Canada" in per_kg["origin"]
    assert carbon.imported_food_pulse_saving_per_kg("soft_wheat")["kg_co2e_saved_per_kg"] == 0.0


def test_sovereignty_block_now_discloses_its_own_denominator():
    """The fix for the field that was being read as the official PSN target."""
    sov = orchestrator.run(_req()).sovereignty
    assert sov.target_denominator == "arable_ha"
    assert "not the PSN target" in sov.target_basis
    psn = sov.official_psn_target
    assert psn["target_share_of_sau_pct"] == 8.0
    assert psn["observed_2020_to_2022_pct"] < 0, "the official target was missed"
    assert "SAU" in psn["denominator_warning"]
    assert sov.food_tier_self_sufficiency_pct is not None


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
def test_food_demand_endpoint_balances_supply_against_population(client):
    r = client.get(f"{BASE}/food-demand?n_simulations=250")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["regions"], "no region produced a balance"
    for reg in d["regions"]:
        assert reg["recommended_demand_t"] > reg["current_demand_t"]
        assert reg["suppliable_food_grade_t"] >= 0.0
        if reg["current_demand_t"]:
            assert reg["coverage_of_current_demand_pct"] == pytest.approx(
                100.0 * reg["suppliable_food_grade_t"] / reg["current_demand_t"], rel=1e-3
            )
    assert d["national"]["self_sufficiency_current_pct"] < 100.0
    assert d["provenance"]["mode"] == "model_output"


def test_food_demand_exposes_the_margin_versus_food_divergence(client):
    """The policy finding: optimising a department for margin and optimising it for
    food do not pick the same crop, and the difference is measurable."""
    d = client.get(f"{BASE}/food-demand?n_simulations=250").json()
    diverged = [
        dd
        for reg in d["regions"]
        for dd in reg["departments"]
        if dd["best_margin_pulse"] != dd["best_food_pulse"]
    ]
    assert diverged, "expected at least one department where the two objectives differ"
    for dd in diverged:
        assert dd["food_t_if_food_optimised"] >= dd["food_t_if_margin_optimised"]
        assert dd["best_food_margin_eur_ha"] <= dd["best_margin_eur_ha"]


def test_climate_outlook_rows_are_ordered_and_report_their_drivers(client):
    r = client.get(f"{BASE}/climate-outlook?department_code=28&crop=green_lentil&n_simulations=300")
    assert r.status_code == 200, r.text
    d = r.json()
    shifts = [x["total_shift_applied_c"] for x in d["rows"]]
    assert shifts == sorted(shifts)
    assert d["rows"][0]["horizon"] == "observed"
    may = [x["may_days_above_20c"] for x in d["rows"]]
    assert may == sorted(may), "insect pressure must rise monotonically with warming"
    rain = {x["harvest_rain_mm"] for x in d["rows"]}
    assert len(rain) == 1, "harvest rain has no fitted temperature response, so it must not move"
    assert d["window_catchup_c"] > 0
    assert "space-for-time" in d["method"]
    assert "INTERANNUAL" in d["caveat"]


def test_climate_outlook_rejects_an_unknown_crop(client):
    assert client.get(f"{BASE}/climate-outlook?crop=quinoa").status_code == 422


def test_simulate_rotation_rejects_an_unknown_horizon(client):
    r = client.post(
        f"{BASE}/simulate-rotation",
        json={
            "department_code": "28", "area_ha": 45.0, "soil_type": "deep_loam",
            "baseline_rotation": ["soft_wheat", "spring_barley", "rapeseed"],
            "candidate_pulse_year2": "field_pea", "climate_horizon": "rcp85",
        },
    )
    assert r.status_code == 422


def test_reference_endpoint_carries_the_food_and_climate_layers(client):
    d = client.get(f"{BASE}/reference").json()
    assert {"climate_horizons", "food_demand_national", "crop_food_market",
            "psn_area_target"} <= set(d)
    assert len(d["climate_horizons"]) >= 4
    assert d["psn_area_target"]["target_mha"] == 2.0
    assert "denominator_warning" in d["psn_area_target"]


def test_dossier_tells_the_advisor_where_the_harvest_goes(client):
    """The printable document an advisor takes to a farm visit has to carry the food
    outcome, and has to name the feed counterfactual rather than implying the whole
    crop displaces imported soy meal."""
    r = client.post(
        f"{BASE}/dossier",
        json={
            "department_code": "28", "area_ha": 45.0, "soil_type": "deep_loam",
            "baseline_rotation": ["soft_wheat", "spring_barley", "rapeseed"],
            "candidate_pulse_year2": "green_lentil", "n_simulations": 300,
            "random_seed": 3,
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    titles = [s["title"] for s in d["sections"]]
    assert "Where this harvest goes" in titles
    assert "Climate assumed" in titles
    env = next(s for s in d["sections"] if s["title"].startswith("Environment"))
    assert "soybean meal" in env["body"]["counterfactual"]
    items = [c["item"] for c in d["agronomic_checklist"]]
    assert "Route to a human-food outlet confirmed" in items
    route = next(c for c in d["agronomic_checklist"] if c["item"].startswith("Route"))
    assert "people for a year" in route["detail"]


def test_food_outcome_is_present_and_provenanced_through_the_api(client):
    r = client.post(
        f"{BASE}/simulate-rotation",
        json={
            "department_code": "28", "area_ha": 45.0, "soil_type": "deep_loam",
            "baseline_rotation": ["soft_wheat", "spring_barley", "rapeseed"],
            "candidate_pulse_year2": "green_lentil", "n_simulations": 300,
            "random_seed": 3, "climate_horizon": "tracc_2050",
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    f = d["food_outcome"]
    assert f["provenance"]["mode"] == "model_output"
    assert f["people_fed_at_recommended_intake"] > 0
    assert d["climate_context"]["warming_level_c"] == 2.7
    assert d["climate_context"]["total_shift_applied_c"] > 1.0
    # The food framing must reach the assumptions a user actually reads.
    assert any("food for people" in a for a in d["assumptions"])
    assert any("Climate horizon" in a for a in d["assumptions"])


def test_food_optimal_pick_declares_whether_its_yield_is_local_or_borrowed(client):
    """Raised by a reader noticing "best for food" says chickpea in every department.

    The pick is arithmetically correct — chickpea is the only crop with both a high
    human-food market share and a decent yield, so it dominates a tonnes-per-hectare
    objective. But in 22 of 40 departments it rests on a yield baseline borrowed from
    other departments with the same soil, and this view did not say so while the farmer
    view warned about exactly that. The same weak number cannot be flagged in one place
    and presented as solid in another.
    """
    d = client.get(f"{BASE}/food-demand").json()
    rows = [x for r in d["regions"] for x in r["departments"]]
    assert rows

    for r in rows:
        assert "best_food_baseline_is_local" in r, r["department_code"]
        assert "best_food_baseline_source" in r
        # A borrowed baseline must carry the plain-language caveat the farmer tab uses.
        if not r["best_food_baseline_is_local"]:
            assert r["best_food_baseline_caveat"], r["department_code"]
            # Two distinct weaknesses, two distinct wordings: a baseline borrowed from
            # same-soil departments, or the national mean when even that is missing.
            cav = r["best_food_baseline_caveat"].lower()
            assert ("borrowed" in cav) or ("national mean" in cav), cav

    borrowed = [r for r in rows if not r["best_food_baseline_is_local"]]
    local = [r for r in rows if r["best_food_baseline_is_local"]]
    # Both kinds must occur, or the flag is decoration rather than information.
    assert borrowed, "expected some departments with no local history for the food pick"
    assert local, "expected some departments with their own history for the food pick"


def test_soil_adjusted_baselines_still_count_as_local():
    """`agreste_department_history_soil_adjusted` uses the department's OWN series.

    Comparing against the bare string treated those as borrowed, which would have
    mislabelled a genuinely local baseline as the weakest number in the row.
    """
    from app.services import ml

    assert ml.baseline_is_local("agreste_department_history")
    assert ml.baseline_is_local("agreste_department_history_soil_adjusted")
    assert not ml.baseline_is_local("agreste_same_soil_archetype")
    assert not ml.baseline_is_local("agreste_national_mean")
    assert not ml.baseline_is_local("crop_reference_table")
