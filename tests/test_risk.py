"""Risk-preference claims, pinned as tests.

The engine measured risk before this module existed; it could not apply a risk
attitude. These tests pin both the utility arithmetic and the one substantive finding
that came out of building it: the two rotations share most of their risk, so a
whole-rotation certainty equivalent is nearly blind to risk aversion.
"""
import numpy as np
import pytest
from app.services import finance as F
from app.services import risk as R
from app.services import weather


def _sim(dept="28", soil="deep_loam", pulse="field_pea", n=3000, seed=5, **kw):
    rng = np.random.default_rng(seed)
    seasons = [weather.sample_seasons(dept, n, rng) for _ in range(3)]
    base = kw.pop("baseline_rotation", ["soft_wheat", "spring_barley", "rapeseed"])
    return F.simulate(
        dept=dept, soil=soil, baseline_rotation=base, pulse=pulse,
        seasons=seasons, rng=rng, preceding_crop=base[0], **kw
    )


# ----------------------------------------------------------------- utility arithmetic

def test_ce_equals_mean_when_risk_neutral():
    x = np.array([100.0, 200.0, 300.0, 1000.0])
    assert R.certainty_equivalent(x, 0.0) == pytest.approx(x.mean())


def test_ce_below_mean_for_a_risky_prospect():
    """A risk-averse decision maker values a gamble below its expected value."""
    x = np.random.default_rng(1).normal(1000.0, 300.0, 20000)
    assert R.certainty_equivalent(x, 1.0 / 3000.0) < x.mean()


def test_ce_is_monotone_decreasing_in_risk_aversion():
    x = np.random.default_rng(2).normal(1500.0, 400.0, 20000)
    ces = [R.certainty_equivalent(x, a) for a in (0.0, 1e-4, 5e-4, 1e-3, 2e-3)]
    assert all(b <= a + 1e-9 for a, b in zip(ces, ces[1:], strict=False))


def test_ce_does_not_overflow_on_realistic_euro_magnitudes():
    """Pins the mean-shift in `certainty_equivalent`.

    exp(-a*x) on raw three-year margins in the thousands overflows float64 and returns
    -inf, which would have made every risk-averse comparison silently meaningless.
    """
    x = np.random.default_rng(3).normal(3000.0, 600.0, 5000)
    ce = R.certainty_equivalent(x, 4.0 / 3000.0)
    assert np.isfinite(ce)
    assert x.min() < ce < x.mean()


def test_ce_matches_closed_form_for_a_normal_prospect():
    """Under CARA with normal outcomes, CE = mu - a*sigma^2/2 exactly."""
    mu, sd, a = 2000.0, 350.0, 1.0 / 2500.0
    x = np.random.default_rng(4).normal(mu, sd, 400000)
    assert R.certainty_equivalent(x, a) == pytest.approx(mu - a * sd**2 / 2.0, rel=0.02)


def test_wealth_anchor_survives_a_fallow_baseline():
    """A fallow baseline has no revenue and a real maintenance cost, so its margin can
    be negative and cannot anchor a relative risk aversion coefficient."""
    sim = _sim(baseline_rotation=["fallow", "fallow", "soft_wheat"])
    assert R.wealth_anchor(sim) >= R.MIN_WEALTH_ANCHOR_EUR_HA


# ----------------------------------------------------------------- the finding

def test_the_two_rotations_share_most_of_their_risk():
    """Year 1 is identical and year 3 nearly so, so the arms are strongly correlated.

    This is why the orthodox SERF comparison is mean-driven here, and why the risk
    layer prices the DIFFERENCE instead.
    """
    diag = R.risk_sharing_diagnostic(_sim(n=6000))
    assert diag["arm_correlation"] > 0.75
    assert diag["share_of_delta_variance_explained_by_arm_asymmetry"] < 0.25


def test_arm_level_advantage_is_nearly_flat_in_risk_aversion():
    """The measured consequence: across the whole Anderson-Dillon range the arm-level
    advantage moves by far less than the switching premium does."""
    curve = R.serf_curve(_sim(n=6000))
    arm_spread = abs(curve[-1]["ce_advantage_eur_ha"] - curve[0]["ce_advantage_eur_ha"])
    delta_spread = abs(curve[-1]["ce_delta_eur_ha"] - curve[0]["ce_delta_eur_ha"])
    assert arm_spread < delta_spread


def test_switching_premium_is_zero_at_risk_neutrality_and_rises():
    curve = R.serf_curve(_sim())
    assert curve[0]["switching_risk_premium_eur_ha"] == pytest.approx(0.0, abs=0.05)
    prem = [r["switching_risk_premium_eur_ha"] for r in curve]
    assert all(b >= a - 1e-6 for a, b in zip(prem, prem[1:], strict=False))


def test_threshold_reports_never_when_the_switch_fails_on_expected_value():
    """Pea displacing barley on Beauce deep loam loses on the mean, which the European
    literature also finds for grain legumes against a productive cereal (Reckling et
    al. 2016, doi:10.1016/j.eja.2015.11.005). No risk tolerance rescues that."""
    t = R.risk_tolerance_threshold(_sim())
    assert t["verdict"] == "never"
    assert t["advantage_risk_neutral_eur_ha"] < 0.0


def test_threshold_reports_always_when_converting_fallow():
    t = R.risk_tolerance_threshold(_sim(baseline_rotation=["fallow", "fallow", "soft_wheat"]))
    assert t["verdict"] == "always"


# ----------------------------------------------------------------- contract inversion

def test_zero_contracted_volume_reproduces_the_spot_arm():
    sim = _sim()
    assert np.allclose(R.pulse_total_under_contract(sim, 500.0, None, 0.0), sim["pulse_total"])


def test_contract_revenue_rises_with_price():
    sim = _sim()
    lo = R.pulse_total_under_contract(sim, 300.0, None, 1.0).mean()
    hi = R.pulse_total_under_contract(sim, 600.0, None, 1.0).mean()
    assert hi > lo


def test_minimum_viable_contract_clears_the_bar_it_solved_for():
    """At the returned price the risk-adjusted value of switching must be ~zero."""
    sim = _sim()
    mvc = R.minimum_viable_contract(sim, rra=2.0)
    w = R.wealth_anchor(sim)
    for row in mvc["terms"]:
        if not row.get("feasible") or row.get("note"):
            continue
        under = R.pulse_total_under_contract(
            sim, row["min_contract_price_eur_t"], None, row["volume_share"]
        )
        ce = R.certainty_equivalent(under - sim["baseline_total"], 2.0 / w)
        assert ce == pytest.approx(0.0, abs=1.0)


def test_less_contracted_volume_requires_a_higher_price():
    """Contracting a quarter of the harvest has to pay more per tonne than contracting
    all of it, because the uncontracted remainder keeps its full exposure."""
    mvc = R.minimum_viable_contract(_sim(), rra=2.0)
    priced = [r for r in mvc["terms"] if r.get("min_contract_price_eur_t") and not r.get("note")]
    prices = [r["min_contract_price_eur_t"] for r in sorted(priced, key=lambda r: r["volume_share"])]
    assert all(b <= a + 1e-6 for a, b in zip(prices, prices[1:], strict=False)), prices


def test_a_more_risk_averse_farmer_needs_a_better_price():
    """The contract terms must actually respond to the risk attitude. They would not
    under the arm-level comparison, which is why the inversion uses the difference."""
    mvc = R.minimum_viable_contract(_sim(n=6000), rra=2.0)
    s = mvc["price_sensitivity_full_volume_eur_t"]
    assert s["rra_0"] is not None and s["rra_4"] is not None
    assert s["rra_4"] > s["rra_0"]


def test_infeasible_terms_are_reported_as_none_not_clipped():
    """Fava bean on Cote-d'Or shallow limestone cannot be carried by a small contracted
    share at any price inside the search range. That must read as None."""
    mvc = R.minimum_viable_contract(_sim(dept="21", soil="shallow_limestone", pulse="fava_bean"),
                                    rra=2.0, volume_shares=(0.1, 1.0))
    assert mvc["terms"][0]["min_contract_price_eur_t"] is None
    assert mvc["terms"][0]["feasible"] is False


# ------------------------------------------------- pre-crop literature sensitivity

def test_precrop_sensitivity_does_not_double_apply_the_capture_factor():
    """`wheat_boost_t` is post-capture; the review band is a following-CEREAL gain.

    Grossing back up before comparing is the whole point. With rapeseed in year 3
    (capture 0.45) the cereal-equivalent gain must land near the configured by-legume
    value of 0.5 t/ha for field pea, not near the applied 0.22.
    """
    s = F.precrop_literature_sensitivity(_sim(n=4000))
    assert s["year3_capture_factor"] == pytest.approx(0.45, abs=0.01)
    assert 0.40 < s["engine_following_crop_gain_t_ha_cereal_equivalent"] < 0.60
    assert s["engine_following_crop_gain_t_ha_as_applied"] < (
        s["engine_following_crop_gain_t_ha_cereal_equivalent"]
    )


def test_precrop_sensitivity_is_monotone_across_the_review_range():
    d = F.precrop_literature_sensitivity(_sim(n=4000))["median_delta_eur_ha"]
    assert d["review_lower_bound"] <= d["review_midpoint"] <= d["review_upper_bound"]


def test_engine_is_at_or_below_the_review_lower_bound():
    """The defensive claim, enforced rather than asserted: no positive result in this
    engine comes from crediting pre-crop benefits above the published European range.
    Preissel et al. 2015 measured 0.5-1.6 t/ha on the following cereal."""
    s = F.precrop_literature_sensitivity(_sim(n=4000))
    lo = s["review_following_crop_band_t_ha"][0]
    assert s["engine_following_crop_gain_t_ha_cereal_equivalent"] <= lo + 1e-6


def test_conservatism_is_largest_where_yields_are_low():
    """The sharper finding: the credit scales with the legume's realised yield, so a
    low-yielding site gets a much smaller pre-crop credit than a high-yielding one.
    That is an engine assumption, not a reviewed result, and it bites hardest exactly
    where the pulse case is most marginal."""
    beauce = F.precrop_literature_sensitivity(_sim(dept="28", soil="deep_loam", n=4000))
    cotedor = F.precrop_literature_sensitivity(
        _sim(dept="21", soil="shallow_limestone", n=4000)
    )
    assert (
        cotedor["engine_following_crop_gain_t_ha_cereal_equivalent"]
        < beauce["engine_following_crop_gain_t_ha_cereal_equivalent"]
    )
    assert cotedor["engine_n_credit_kg_ha"] < beauce["engine_n_credit_kg_ha"]


# ------------------------------------------------- threshold conditioning

def test_threshold_reports_its_own_uncertainty():
    """A marginal case must not be quoted as a precise coefficient.

    The crossing point is where the switching premium equals the mean delta. The
    premium is well estimated; the mean delta on a marginal case is not, and the ratio
    amplifies that noise. The point estimate therefore ships with a bootstrap interval
    and a resolution flag.
    """
    t = R.risk_tolerance_threshold(
        _sim(dept="21", soil="shallow_limestone", pulse="winter_pea", n=2000)
    )
    assert "mean_delta_standard_error_eur_ha" in t
    assert "verdict_resolved" in t
    if t["verdict"] == "flips":
        assert t["rra_threshold_p10"] is not None
        assert t["rra_threshold_p10"] <= t["rra_threshold"] <= t["rra_threshold_p90"]


def test_unresolved_marginal_case_says_too_close_to_call():
    t = R.risk_tolerance_threshold(
        _sim(dept="21", soil="shallow_limestone", pulse="winter_pea", n=2000)
    )
    if not t["verdict_resolved"] and t["verdict"] == "flips":
        assert "too close to call" in t["interpretation"].lower()


def test_switching_premium_is_far_better_conditioned_than_the_threshold():
    """The constructive half of the finding: report the premium, not the crossing.

    Across seeds the premium moves a few percent while the threshold moves by a
    factor approaching two, so the premium is what a slide should carry.
    """
    prem, thr = [], []
    for seed in (1, 2, 3, 4, 5):
        sim = _sim(dept="21", soil="shallow_limestone", pulse="winter_pea",
                   n=2000, seed=seed)
        prem.append({r["rra"]: r for r in R.serf_curve(sim)}[2.0]
                    ["switching_risk_premium_eur_ha"])
        t = R.risk_tolerance_threshold(sim)
        if t["rra_threshold"] is not None:
            thr.append(t["rra_threshold"])
    rel_prem = float(np.std(prem) / np.mean(prem))
    assert rel_prem < 0.10, rel_prem
    if len(thr) >= 3:
        assert float(np.std(thr) / np.mean(thr)) > rel_prem


# --------------------------------------------------------------------------- #
# Verdict robustness: does the answer survive its own assumptions?
# --------------------------------------------------------------------------- #
def test_robustness_flags_a_marginal_verdict_as_fragile():
    """The feature exists because a point figure reads as a fact when it is not.

    The sensitivity audit found the grading pass rate can flip the SIGN of the answer
    on a marginal field. A tool that reports only the central number leaves the user to
    find that out by being contradicted.
    """
    import numpy as np
    from app.services import finance as F
    from app.services import robustness, weather

    def sim_for(dept, soil, pulse, km):
        rng = np.random.default_rng(7)
        seasons = [weather.sample_seasons(dept, 1000, rng) for _ in range(3)]
        return F.simulate(
            dept=dept, soil=soil,
            baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
            pulse=pulse, seasons=seasons, rng=rng, preceding_crop="soft_wheat",
            sorter_road_km=km,
        )

    # Beauce field pea loses money under every perturbation: the verdict holds.
    firm = robustness.assess(sim_for("28", "deep_loam", "field_pea", 22.0), 22.0)
    assert firm["verdict_is_robust"]
    assert firm["range_high_eur_ha"] < 0
    assert "Holds" in firm["verdict"]

    # Cote-d'Or winter pea sits near break-even: the verdict must be flagged fragile.
    marginal = robustness.assess(
        sim_for("21", "shallow_limestone", "winter_pea", 40.0), 40.0
    )
    assert not marginal["verdict_is_robust"]
    assert marginal["range_low_eur_ha"] < 0 < marginal["range_high_eur_ha"]
    assert "FRAGILE" in marginal["verdict"]
    assert "no observational labels" in marginal["verdict"]


def test_robustness_range_always_brackets_the_reported_figure():
    """A range that excludes the number it qualifies would be worse than none."""
    import numpy as np
    from app.services import finance as F
    from app.services import robustness, weather

    rng = np.random.default_rng(3)
    seasons = [weather.sample_seasons("86", 800, rng) for _ in range(3)]
    sim = F.simulate(
        dept="86", soil="shallow_limestone",
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        pulse="green_lentil", seasons=seasons, rng=rng,
        preceding_crop="soft_wheat", sorter_road_km=200.0,
    )
    r = robustness.assess(sim, 200.0)
    assert r["range_low_eur_ha"] <= r["central_eur_ha"] <= r["range_high_eur_ha"]
    # Both named assumptions must be reported, not just the one that happened to bind.
    assert set(r["grading_pass_rate_pm_0_15"]) >= {"low", "central", "high"}
    assert r["haulage_across_published_range"]["binding"] is True


def test_grading_band_is_monotone_in_the_pass_rate():
    """More of the harvest clearing food specification cannot pay less."""
    import numpy as np
    from app.services import finance as F
    from app.services import robustness, weather

    rng = np.random.default_rng(11)
    seasons = [weather.sample_seasons("28", 800, rng) for _ in range(3)]
    sim = F.simulate(
        dept="28", soil="deep_loam",
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        pulse="green_lentil", seasons=seasons, rng=rng, preceding_crop="soft_wheat",
    )
    g = robustness.grading_sensitivity(sim)
    assert g["low"] < g["central"] < g["high"]
