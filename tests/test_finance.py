"""The methodological claims of the engine, pinned as tests."""
import numpy as np
import pytest
from app.services import finance as F
from app.services import weather


def _seasons(dept="28", n=800, seed=5):
    rng = np.random.default_rng(seed)
    return [weather.sample_seasons(dept, n, rng) for _ in range(3)], rng


def _sim(**kw):
    seasons, rng = _seasons(dept=kw.pop("dept", "28"), n=kw.pop("n", 800))
    defaults = dict(
        dept="28", soil="deep_loam",
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        pulse="field_pea", seasons=seasons, rng=rng, preceding_crop="soft_wheat",
    )
    defaults.update(kw)
    return F.simulate(**defaults)


def test_year1_is_identical_in_both_arms():
    """Only year 2 changes, so year 1 must cancel exactly out of the difference."""
    sim = _sim()
    fan = F.cumulative_fan(sim)
    assert fan[0]["baseline_median"] == pytest.approx(fan[0]["pulse_median"])
    assert fan[0]["baseline_q15"] == pytest.approx(fan[0]["pulse_q15"])


def test_delta_equals_difference_of_arms():
    sim = _sim()
    assert np.allclose(sim["delta"], sim["pulse_total"] - sim["baseline_total"])


def test_common_random_numbers_reduce_delta_variance():
    """The point of shared draws: the difference must be far less noisy than either arm.

    Independent draws would make sd(delta) about sqrt(2) times the arm sd. Sharing the
    weather and the residual shocks cancels most of that common noise.
    """
    sim = _sim(n=3000)
    sd_delta = float(np.std(sim["delta"]))
    sd_arm = float(np.std(sim["baseline_total"]))
    assert sd_delta < sd_arm


def test_guaranteed_floor_raises_the_downside():
    """A contract floor must improve the bad-year outcome, not the median alone."""
    contract = {
        "contract_price_eur_t": 372.0, "fallback_feed_price_eur_t": 255.0,
        "floor_guaranteed": True,
    }
    free = F.summarise(_sim(n=2500))
    held = F.summarise(_sim(n=2500, contract=contract))
    assert held["delta_q15"] > free["delta_q15"]


def test_livestock_raises_value_of_a_downgraded_harvest():
    plain = F.summarise(_sim(n=2000, pulse="fava_bean"))
    mixed = F.summarise(_sim(n=2000, pulse="fava_bean", has_livestock=True))
    assert mixed["delta_median"] > plain["delta_median"]


def test_irrigation_correction_lowers_rainfed_soy():
    """Agreste blends irrigated and rain-fed area; a rain-fed parcel must score lower."""
    rainfed = _sim(dept="32", soil="clay_loam", pulse="soybean",
                   baseline_rotation=["durum_wheat", "sunflower", "soft_wheat"],
                   preceding_crop="durum_wheat", n=1500)
    irr = _sim(dept="32", soil="clay_loam", pulse="soybean",
               baseline_rotation=["durum_wheat", "sunflower", "soft_wheat"],
               preceding_crop="durum_wheat", irrigated=True, n=1500)
    assert np.median(rainfed["pulse_yield"]) < np.median(irr["pulse_yield"])
    assert rainfed["irrigation_factor"] < 1.0 < irr["irrigation_factor"]


def test_summary_quantiles_are_ordered():
    s = F.summarise(_sim(n=2000))
    assert s["delta_q15"] <= s["delta_median"] <= s["delta_q85"]
    assert s["baseline_q15"] <= s["baseline_median"] <= s["baseline_q85"]
    assert s["cvar_5pct"] <= s["delta_q15"]
    assert 0.0 <= s["prob_beats_baseline"] <= 1.0


def test_break_crop_capture_is_lower_for_oilseed_year3():
    cereal = _sim(n=1200, year3_override="soft_wheat")
    oilseed = _sim(n=1200, year3_override="rapeseed")
    assert np.median(cereal["wheat_boost_t"]) > np.median(oilseed["wheat_boost_t"])


def test_pac_aid_scheme_selection():
    grain = _sim(n=400, pulse="field_pea")
    assert grain["pac_scheme"] == "legumineuses_a_graines"
    assert grain["pac_aid"] == pytest.approx(122.0)
    soy = _sim(n=400, pulse="soybean")
    assert soy["pac_scheme"] == "soja"
    assert soy["pac_aid"] < grain["pac_aid"]  # soy has its own lower unit amount


def test_seed_makes_results_reproducible():
    a = F.summarise(_sim(n=700))
    b = F.summarise(_sim(n=700))
    assert a["delta_median"] == pytest.approx(b["delta_median"])


def test_converting_fallow_beats_displacing_an_established_crop():
    """Idle land is the cheapest conversion target: nothing is displaced.

    A third of parcels in a live RPG 2023 Beauce sample are declared fallow or
    temporarily unexploited, so this is the common case, not the edge case.
    """
    crop_land = F.summarise(_sim(n=1500))
    idle_land = F.summarise(
        _sim(n=1500, baseline_rotation=["soft_wheat", "fallow", "rapeseed"])
    )
    assert idle_land["delta_median"] > crop_land["delta_median"] + 400
    assert idle_land["prob_beats_baseline"] > 0.9


def test_fallow_has_a_maintenance_cost_not_zero():
    """Idle land still costs money to keep compliant, so the forgone margin is negative."""
    sim = _sim(n=800, baseline_rotation=["soft_wheat", "fallow", "rapeseed"])
    assert float(np.median(sim["baseline_y2_margin"])) < 0.0
    assert float(np.median(sim["baseline_y2_margin"])) > -200.0


def test_nitrogen_credit_to_fallow_year3_has_no_cash_value():
    """Nothing is harvested on fallow, so a break-crop yield gain cannot be banked."""
    sim = _sim(n=600, year3_override="fallow")
    assert float(np.median(sim["wheat_boost_eur"])) == pytest.approx(0.0, abs=1e-6)


def test_carbon_impact_distribution_quantiles_are_ordered():
    """Carbon saved must carry the same q15/median/q85 ordering as the finance risk."""
    from app.services import carbon

    rng = np.random.default_rng(4)
    y = np.clip(rng.normal(2.2, 0.7, 2000), 0, None)
    n = np.clip(rng.normal(22, 7, 2000), 0, None)
    for conv in ("with_luc", "without_luc"):
        d = carbon.impact_distribution("field_pea", y, n, 40.0, convention=conv)
        assert d["co2e_saved_tons_q15"] <= d["co2e_saved_tons_median"]
        assert d["co2e_saved_tons_median"] <= d["co2e_saved_tons_q85"]


def test_carbon_distribution_median_matches_scalar_point_estimate():
    """The new per-draw accounting must agree with the old point-yield calculation."""
    from app.services import carbon

    rng = np.random.default_rng(5)
    y = np.clip(rng.normal(3.0, 0.5, 5000), 0, None)
    n = np.clip(rng.normal(25, 5, 5000), 0, None)
    dist = carbon.impact_distribution("fava_bean", y, n, 30.0, convention="with_luc")
    scalar = carbon.impact(
        "fava_bean", float(np.median(y)), float(np.median(n)), 30.0, convention="with_luc"
    )
    assert dist["co2e_saved_tons_median"] == pytest.approx(
        scalar["co2e_saved_tons_total"], rel=0.02
    )


def test_carbon_abatement_cost_sign_tracks_financial_outcome():
    """A profitable rotation must show a negative abatement cost; a costly one positive."""
    import sys

    sys.path.insert(0, "backend")
    from app.schemas import SimulateRotationRequest
    from app.services import orchestrator as O

    profitable = O.run(SimulateRotationRequest(
        department_code="32", area_ha=30.0, soil_type="clay_loam", irrigated=True,
        baseline_rotation=["durum_wheat", "sunflower", "soft_wheat"],
        candidate_pulse_year2="soybean", selected_buyer_id="BUY-EUR-01",
        n_simulations=1500, random_seed=7,
    ))
    costly = O.run(SimulateRotationRequest(
        department_code="28", area_ha=30.0, soil_type="deep_loam",
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        candidate_pulse_year2="green_lentil", n_simulations=1500, random_seed=7,
    ))
    e_profit = profitable.environmental_impact
    e_cost = costly.environmental_impact
    assert profitable.financial_3yr_comparison_per_ha.risk.median_delta_eur_ha > 0
    assert e_profit.carbon_abatement_cost_eur_per_tonne is not None
    assert e_profit.carbon_abatement_cost_eur_per_tonne < 0

    assert costly.financial_3yr_comparison_per_ha.risk.median_delta_eur_ha < 0
    assert e_cost.carbon_abatement_cost_eur_per_tonne is not None
    assert e_cost.carbon_abatement_cost_eur_per_tonne > 0
