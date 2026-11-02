"""Haulage economics and the optical-sorter siting optimiser, pinned as tests.

The claim these protect is the regional half of the product: that "stranded potential"
is a financial category derived from a cost, not a label attached to a distance. If the
closed-form distance shift ever stops matching the Monte Carlo it is derived from, every
hectare the optimiser reports becomes fiction, so that equivalence is tested directly
rather than assumed.
"""
import numpy as np
import pytest
from app.services import finance as F
from app.services import logistics as L
from app.services import siting as S
from app.services import weather


def _seasons(dept="28", n=800, seed=5):
    rng = np.random.default_rng(seed)
    return [weather.sample_seasons(dept, n, rng) for _ in range(3)], rng


def _sim(**kw):
    dept = kw.pop("dept", "28")
    seasons, rng = _seasons(dept=dept, n=kw.pop("n", 800), seed=kw.pop("seed", 5))
    defaults = dict(
        dept=dept, soil="deep_loam",
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        pulse="field_pea", seasons=seasons, rng=rng, preceding_crop="soft_wheat",
    )
    defaults.update(kw)
    return F.simulate(**defaults)


# --------------------------------------------------------------------------- #
# Haulage
# --------------------------------------------------------------------------- #
def test_haul_inside_the_collection_radius_is_free():
    """The first 25 km is already inside the RICA operating cost both arms carry.

    Charging it would double-count it AND would charge the pulse arm for a haul the
    baseline cereal arm also makes, manufacturing a penalty out of an accounting error.
    """
    radius = L.ref()["haulage"]["local_collection_radius_km"]
    assert L.food_haulage_eur_per_tonne(0.0) == 0.0
    assert L.food_haulage_eur_per_tonne(radius) == 0.0
    assert L.food_haulage_eur_per_tonne(radius - 5) == 0.0
    assert L.food_haulage_eur_per_tonne(radius + 10) > 0.0


def test_haul_is_linear_in_distance_beyond_the_radius():
    """Linearity is what lets the optimiser shift a Monte Carlo result in closed form."""
    r = L.ref()["haulage"]["local_collection_radius_km"]
    rate = L.ref()["haulage"]["eur_per_tonne_km"]
    for extra in (10.0, 50.0, 200.0):
        assert L.food_haulage_eur_per_tonne(r + extra) == pytest.approx(rate * extra)


def test_road_distance_exceeds_great_circle():
    a, b = (1.5, 48.3), (4.8, 47.4)
    assert L.road_km(a, b) > L.haversine_km(a, b)
    assert L.road_km(a, b) == pytest.approx(
        L.haversine_km(a, b) * L.ref()["haulage"]["road_detour_factor"]
    )


def test_haul_is_charged_on_food_tonnes_only_so_a_bad_grading_year_hauls_less():
    """A wet harvest downgrades the lot, and a downgraded lot does not need sorting.

    The sign matters: haulage must partly OFFSET a grading loss rather than compound it,
    because the fraction that fails food specification goes to a local feed outlet.
    """
    cost_good = L.haulage_cost_eur_ha(4.0, 0.8, 150.0)
    cost_bad = L.haulage_cost_eur_ha(4.0, 0.2, 150.0)
    assert float(cost_bad) < float(cost_good)
    assert float(L.haulage_cost_eur_ha(4.0, 0.0, 150.0)) == 0.0


def test_distance_reduces_the_margin_through_the_simulation():
    near = _sim(sorter_road_km=20.0)
    far = _sim(sorter_road_km=260.0)
    assert float(np.median(far["haulage_eur"])) > float(np.median(near["haulage_eur"]))
    assert float(np.median(far["delta"])) < float(np.median(near["delta"]))


def test_breakeven_food_fraction_rises_with_distance():
    """Haulage scales with the food fraction, so it belongs in the break-even spread.

    An earlier version left it in the fixed term, which understated the break-even
    fraction on exactly the distant parcels where the answer decides the planting.
    """
    # Chickpea in Vendee, where the pulse is comfortably profitable and the break-even
    # fraction therefore sits well inside (0, 1). The quantity is clipped to [0, 1], so
    # a crop that loses money at any grading outcome reports a flat 1.0 at every
    # distance and cannot show a distance effect at all - which rules out field pea in
    # Beauce and green lentil almost everywhere.
    kw = dict(dept="85", soil="clay_loam", pulse="chickpea")
    near = F.breakeven_human_fraction(_sim(sorter_road_km=20.0, **kw))
    far = F.breakeven_human_fraction(_sim(sorter_road_km=140.0, **kw))
    assert near is not None and far is not None
    assert 0.0 < near < 1.0, f"saturated against the clip at {near}"
    assert far > near


def test_the_food_premium_itself_caps_how_far_a_crop_can_travel():
    """A finding the haulage model produces, not an assumption fed into it.

    Field pea's food-versus-feed spread is about 78 EUR/t, so at 0.45 EUR/t/km the haul
    consumes the whole premium by roughly 200 km and NO food-grade share makes sorting
    access worth paying for - `breakeven_human_fraction` correctly reports that no
    break-even exists. Green lentil's spread is about 565 EUR/t and would pay to cross
    the country. One national 80 km rule treats those two cases identically, and it
    should not.
    """
    pea = L.max_viable_haul_km("field_pea")
    lentil = L.max_viable_haul_km("green_lentil")
    assert pea["max_viable_road_km"] < lentil["max_viable_road_km"] / 4
    assert 150 < pea["max_viable_road_km"] < 250

    beyond = pea["max_viable_road_km"] + 60
    assert F.breakeven_human_fraction(_sim(sorter_road_km=beyond)) is None
    assert F.breakeven_human_fraction(_sim(sorter_road_km=40.0)) is not None


def test_toll_sorting_fee_is_not_charged_to_the_farmer():
    """It is in the reference data to size a new unit's revenue, not the farm's cost.

    Contract prices in this engine are quoted delivered to the buyer, so charging the
    station's toll fee again on the farm side would double-count it.
    """
    assert L.sorting_fee_eur_per_tonne() > 0
    sim = _sim(sorter_road_km=30.0)
    expected = float(
        np.median(
            sim["pulse_yield"] * sim["human_fraction"]
            * L.food_haulage_eur_per_tonne(30.0)
        )
    )
    assert float(np.median(sim["haulage_eur"])) == pytest.approx(expected, rel=1e-9)


def test_unit_economics_improves_with_throughput():
    low = L.unit_economics(2000.0)
    high = L.unit_economics(10000.0)
    assert high["levelised_cost_eur_t"] < low["levelised_cost_eur_t"]
    assert high["utilisation_pct"] > low["utilisation_pct"]


# --------------------------------------------------------------------------- #
# The closed-form shift the optimiser depends on
# --------------------------------------------------------------------------- #
def test_closed_form_distance_shift_matches_a_direct_simulation():
    """THE load-bearing test of the regional engine.

    The optimiser never re-runs the Monte Carlo per candidate site. It runs it once per
    department at zero haulage and shifts the result analytically by distance. That is
    only legitimate if the shift reproduces what a direct simulation at that distance
    would have returned. Checked against a real simulation at three distances.
    """
    dept = "28"
    prof = S.compute_profile(dept, n_sim=800, seed=11)
    assert prof is not None
    pulse = prof["pulse"]

    for km in (40.0, 120.0, 300.0):
        seasons, rng = _seasons(dept=dept, n=800, seed=11)
        direct = F.simulate(
            dept=dept, soil=prof["soil"], baseline_rotation=prof["baseline_rotation"],
            pulse=pulse, seasons=seasons, rng=rng,
            preceding_crop=prof["baseline_rotation"][0],
            has_optical_sorting_access=km <= L.ref()["sorting"]["max_distance_km"],
            sorter_road_km=km,
        )
        predicted = float(S.delta_at_km(prof, km))
        observed = float(np.median(direct["delta"]))
        # Tolerance is a few EUR/ha: the shift is exact on the mean of the haulage term
        # but the median of a shifted distribution is not exactly the shifted median.
        assert observed == pytest.approx(predicted, abs=12.0), (
            f"{km} km: closed form {predicted:.1f} vs direct {observed:.1f}"
        )


def test_delta_falls_monotonically_with_distance():
    prof = S.profiles()["profiles"]["28"]
    km = np.array([0.0, 25.0, 50.0, 79.0, 120.0, 400.0])
    d = S.delta_at_km(prof, km)
    assert np.all(np.diff(d) <= 1e-9)


def test_crossing_the_access_threshold_costs_more_than_the_marginal_kilometre():
    """The grading penalty for losing sorting access is a step, not a slope.

    Only for the crops that actually need an optical sorter to reach retail
    specification. `quality.json` applies the access penalty to lentil, chickpea and
    fava bean - whole seeds sold visible, where staining and insect damage are graded by
    eye - and not to pea or soybean, which reach consumers split, milled or processed.
    So the step exists for a lentil department and legitimately does not for a pea one,
    and the test has to pick the right crop rather than assume the step is universal.
    """
    import json

    from app.config import REFDATA_DIR

    # REFDATA_DIR is absolute, so this does not depend on the directory pytest was
    # invoked from.
    spec = json.loads((REFDATA_DIR / "quality.json").read_text(encoding="utf-8"))
    sorted_crops = set(spec["penalties"]["no_optical_sorting_access"]["applies_to"])
    assert sorted_crops, "the access penalty must apply to something"

    prof = next(
        (
            p for p in S.profiles()["profiles"].values()
            if p["pulse"] in sorted_crops
        ),
        None,
    )
    if prof is None:
        # Build one directly rather than skipping: the step is a load-bearing claim.
        prof = S.compute_profile("86", n_sim=400)
        prof = next(
            c for c in prof["candidates"] if c["pulse"] in sorted_crops
        )

    max_km = L.ref()["sorting"]["max_distance_km"]
    step = float(S.delta_at_km(prof, max_km - 0.5)) - float(S.delta_at_km(prof, max_km + 0.5))
    slope = float(S.delta_at_km(prof, 100.0)) - float(S.delta_at_km(prof, 101.0))
    assert step > slope


def test_the_access_penalty_is_scoped_to_visually_graded_crops():
    """Pinning the scope so a future edit cannot silently make it universal.

    A pea sold as split pea or flour does not need an optical sorter the way a whole
    green lentil does, and pretending otherwise would overstate the infrastructure case.
    """
    from app.services import quality

    for crop_key in ("green_lentil", "chickpea"):
        with_access = quality.human_grade_probability(
            crop_key, harvest_rain_mm=60, may_days_above_20c=8,
            drought_stress_index=0.5, jun_heat_days_30c=4,
            has_optical_sorting_access=True,
        )["prob"]
        without = quality.human_grade_probability(
            crop_key, harvest_rain_mm=60, may_days_above_20c=8,
            drought_stress_index=0.5, jun_heat_days_30c=4,
            has_optical_sorting_access=False,
        )["prob"]
        assert without < with_access

    for crop_key in ("field_pea", "soybean"):
        same = [
            quality.human_grade_probability(
                crop_key, harvest_rain_mm=60, may_days_above_20c=8,
                drought_stress_index=0.5, jun_heat_days_30c=4,
                has_optical_sorting_access=a,
            )["prob"]
            for a in (True, False)
        ]
        assert same[0] == pytest.approx(same[1])


def test_delta_vec_matches_the_scalar_path():
    tbl = S._profile_tables()
    code = tbl["codes"][0]
    prof = S.profiles()["profiles"][code]
    km = np.array([10.0, 60.0, 150.0])
    ids = np.full(3, tbl["ids"][code])
    assert np.allclose(S.delta_vec(ids, km), S.delta_at_km(prof, km))


def test_unmodelled_departments_are_nan_not_zero():
    """A department with no viable pulse is unknown, not break-even."""
    out = S.delta_vec(np.array([-1]), np.array([50.0]))
    assert np.isnan(out[0])


# --------------------------------------------------------------------------- #
# Demand surface
# --------------------------------------------------------------------------- #
def test_demand_surface_covers_the_departments_with_weather_data():
    d = S.demand_surface()
    assert d["n"] > 10000, "the commune surface should be the whole arable core"
    assert len(set(d["dept"])) >= 40


def test_commune_arable_sums_back_to_the_agreste_department_total():
    """The allocation between communes is proportional; the department total is real."""
    from app.config import departments

    d = S.demand_surface()
    depts = departments()
    for code in list(depts)[:6]:
        m = np.array([x == code for x in d["dept"]])
        if not m.any():
            continue
        assert float(d["arable_ha"][m].sum()) == pytest.approx(
            float(depts[code]["arable_ha"]), rel=1e-6
        )


def test_convertible_hectares_respect_both_ceilings():
    """The policy target and the disease return interval, whichever binds first.

    The rotation ceiling is the aggregate form of the Aphanomyces constraint: a pulse on
    a five-year return interval cannot occupy more than a fifth of a rotation at steady
    state, whatever the economics say.
    """
    from app.config import crop, load_ref, pulse_crops

    d = S.demand_surface()
    conv = S.convertible_ha()
    target = float(load_ref("departments")["_meta"]["national_target"]["target_pulse_share_pct"])
    interval = float(
        np.mean([crop(p).get("return_interval_years", 5) for p in pulse_crops()])
    )
    assert np.all(conv >= 0)
    assert np.all(conv <= d["arable_ha"] * target / 100.0 + 1e-6)
    assert np.all(conv <= d["arable_ha"] / interval + 1e-6)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def test_stranded_is_strictly_infrastructure_limited():
    """Stranded must mean "a sorter would fix this", never merely "this loses money".

    Conflating stranded with uneconomic is how infrastructure money gets spent where no
    amount of sorting capacity would help.
    """
    surf = S.classify()
    # The one-euro band classify() documents. Asserted against the published band
    # rather than against zero, because a category boundary drawn at exactly zero
    # would be decided by rounding noise.
    eps = 1.0
    stranded = [c for c in surf["communes"] if c["status"] == "stranded"]
    assert stranded, "the whole regional argument needs this category to be non-empty"
    for c in stranded:
        # Compared with <= because the published value is rounded to one decimal.
        assert c["delta_eur_ha"] <= -eps
        assert c["delta_eur_ha_if_served"] >= -eps
        assert c["delta_eur_ha_if_served"] > c["delta_eur_ha"]

    for c in surf["communes"]:
        if c["status"] == "uneconomic":
            assert c["delta_eur_ha_if_served"] < -eps
        if c["status"] == "viable":
            assert c["delta_eur_ha"] >= -eps


def test_adding_a_site_can_only_shrink_the_stranded_set():
    """Monotonicity. More sorting capacity must never strand more land."""
    before = S.classify()["totals"]["stranded_communes"]
    after = S.classify(extra_sites=((0.5, 46.6), (2.3, 47.9)))["totals"]
    assert after["stranded_communes"] <= before


# --------------------------------------------------------------------------- #
# The optimiser
# --------------------------------------------------------------------------- #
def test_more_units_never_unlock_fewer_hectares():
    """Monotonicity of the submodular objective, which greedy relies on."""
    vals = []
    for k in (1, 2, 4):
        r = S.optimise(k=k, region_code="FRB0")
        assert "error" not in r
        vals.append(r["impact"]["hectares_unlocked"])
    assert vals == sorted(vals)


def test_marginal_gains_are_non_increasing():
    """Diminishing returns are the defining property of a submodular objective.

    If a later site ever beat an earlier one, greedy's (1 - 1/e) guarantee would not
    apply and the reported ranking would be meaningless.
    """
    r = S.optimise(k=5, region_code="FRB0")
    gains = [s["marginal_value_eur"] for s in r["sites"]]
    assert gains == sorted(gains, reverse=True)


def test_no_unit_is_loaded_beyond_its_throughput():
    r = S.optimise(k=4)
    cap = L.ref()["new_unit"]["capacity_t_yr"]
    for s in r["sites"]:
        assert s["tonnes_unlocked"] <= cap + 1.0
        assert s["unit_economics"]["utilisation_pct"] <= 100.5


def test_greedy_lands_close_to_the_exact_milp_optimum():
    """The honest version of the rigour claim.

    (1 - 1/e) = 0.632 is the worst case. What matters is the realised ratio against an
    exact HiGHS solve over a candidate set forced to contain greedy's own picks, which
    makes the MILP value a true upper bound here.
    """
    r = S.optimise(k=3, region_code="FRB0", verify_milp=True, milp_candidates=30)
    v = r["optimisation"]["milp_verification"]
    assert v["solved"], v.get("reason")
    ratio = v["greedy_share_of_optimum"]
    assert ratio >= 0.632, "below the submodular worst-case bound means a bug"
    assert ratio <= 1.0 + 1e-6, "greedy cannot beat an exact solve that contains its picks"
    assert ratio > 0.95, f"realised ratio unexpectedly poor: {ratio}"


def test_siting_respects_the_requested_scope():
    r = S.optimise(k=2, department="21")
    assert all(s["dept"] == "21" for s in r["sites"])


def test_optimiser_is_fast_enough_to_be_interactive():
    """Greedy only. The exact solve is opt-in precisely because it is not interactive."""
    import time

    S.optimise(k=1)  # warm the pair index
    t0 = time.perf_counter()
    r = S.optimise(k=5)
    assert (time.perf_counter() - t0) < 3.0
    assert r["compute_ms"] < 3000


def test_unlocked_hectares_move_the_pulse_share_towards_the_target():
    r = S.optimise(k=6)
    i = r["impact"]
    assert i["pulse_share_after_pct"] > i["pulse_share_before_pct"]
    assert i["pulse_share_after_pct"] <= i["target_share_pct"]
    assert i["hectares_unlocked"] > 0
    assert i["co2e_saved_tons"] > 0


def test_every_numeric_parameter_in_logistics_states_its_basis():
    """A bare number in reference data reads as a measurement. None may be bare.

    Added after an audit found `capacity_t_yr` undocumented — the single parameter the
    regional headline is most sensitive to, since the machine count needed to reach the
    area target scales inversely with it.
    """
    from app.config import load_ref

    ref = load_ref("logistics")
    bare = []
    for block_name, block in ref.items():
        if block_name.startswith("_") or not isinstance(block, dict):
            continue
        for key, val in block.items():
            if not isinstance(val, (int, float)):
                continue
            # The file documents `capex_eur` as `capex_note`, i.e. it drops the unit
            # suffix. That is a real convention, so look for the note under both the
            # full key and the key with a trailing unit stripped.
            stems = {key}
            for unit in ("_eur_t_km", "_eur_t", "_eur_yr", "_eur_ha", "_eur",
                         "_t_yr", "_km", "_yr", "_pct"):
                if key.endswith(unit):
                    stems.add(key[: -len(unit)])
            documented = any(
                f"{stem}{suffix}" in block
                for stem in stems
                for suffix in ("_note", "_source", "_range")
            ) or "source" in block
            if not documented:
                bare.append(f"{block_name}.{key}")
    assert not bare, f"numeric parameters with no stated basis: {bare}"


def test_machine_count_for_the_target_is_a_band_not_a_single_figure():
    """The most quotable number in the product, and it rests on one soft parameter.

    Throughput is a plant-configuration choice, not a measurement, and hectares per
    unit scale linearly with it. One figure invites a challenge it cannot answer.
    """
    r = S.optimise(k=3)
    b = r["units_for_target"]
    assert b["gap_to_target_ha"] > 0
    # Bigger lines, fewer of them.
    assert b["low"]["units_required"] < b["central"]["units_required"] < b["high"]["units_required"]
    assert b["low"]["capacity_t_yr"] > b["high"]["capacity_t_yr"]
    assert b["low"]["capex_eur"] < b["high"]["capex_eur"]
    # And the band has to be wide enough to matter, or reporting it is theatre.
    assert b["high"]["units_required"] > 1.5 * b["low"]["units_required"]


def test_removed_parameters_stay_removed():
    """Two numbers were deleted for being unsourced AND unused. Guard the deletion.

    `irrigation_share_pct` was 42 hand-written per-department percentages sitting in
    reference data where they read as measurements, consumed by nothing.
    `food_grade_loss_in_sorting_pct` was deliberately not charged anywhere, so it was
    an undefendable number doing no work.
    """
    from app.config import departments, load_ref

    for code, d in departments().items():
        assert "irrigation_share_pct" not in d, code
        assert "weather_station_dept" not in d, code
    assert "food_grade_loss_in_sorting_pct" not in load_ref("logistics")["sorting"]

    # Irrigation still enters the engine where it IS evidenced.
    irr = load_ref("irrigation")
    assert irr["crops"], "the evidenced irrigation decomposition must remain"
