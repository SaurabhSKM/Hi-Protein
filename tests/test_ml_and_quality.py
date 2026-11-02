"""Model-facing invariants: calibrated intervals and a grading model that reacts."""
import numpy as np
import pytest
from app.services import ml, quality, weather


def _seasons(dept="28", n=400):
    return weather.sample_seasons(dept, n, np.random.default_rng(3))


def test_quantiles_are_monotonic_for_every_crop_and_soil():
    s = _seasons()
    for crop in ["field_pea", "fava_bean", "green_lentil", "chickpea", "soybean", "soft_wheat"]:
        for soil in ["deep_loam", "shallow_limestone", "clay_loam"]:
            q = ml.predict_yield_quantiles(crop, "28", soil, s)
            assert np.all(q["q15"] <= q["q50"] + 1e-9), (crop, soil)
            assert np.all(q["q50"] <= q["q85"] + 1e-9), (crop, soil)
            assert np.all(q["q15"] >= 0.0)


def test_sampled_yields_reproduce_the_stated_interval():
    """The two-piece normal must honour an asymmetric interval.

    A single symmetric sd drove the sampled lower tail far below anything observed,
    which is what this guards against.
    """
    s = _seasons(n=4000)
    for crop in ["green_lentil", "field_pea"]:
        rng = np.random.default_rng(11)
        y, q = ml.sample_yields(rng, crop, "28", "deep_loam", s)
        stated_lo = float(np.median(q["q15"]))
        sampled_lo = float(np.quantile(y, 0.15))
        assert sampled_lo == pytest.approx(stated_lo, rel=0.30), crop


def test_shallow_soil_lowers_expected_yield():
    s = _seasons()
    deep = ml.predict_yield_quantiles("field_pea", "28", "deep_loam", s)
    shallow = ml.predict_yield_quantiles("field_pea", "28", "shallow_limestone", s)
    assert np.median(deep["q50"]) > np.median(shallow["q50"])


def test_parcel_intervals_are_wider_than_department_intervals():
    s = _seasons()
    dept = ml.predict_yield_quantiles("field_pea", "28", "deep_loam", s, parcel_level=False)
    parcel = ml.predict_yield_quantiles("field_pea", "28", "deep_loam", s, parcel_level=True)
    assert np.mean(parcel["q85"] - parcel["q15"]) >= np.mean(dept["q85"] - dept["q15"])


def test_baseline_falls_back_gracefully_for_unknown_department():
    v, src = ml.baseline_yield("field_pea", "99", "deep_loam")
    assert v > 0 and src in {
        "agreste_same_soil_archetype", "agreste_national_mean", "crop_reference_table",
    }


def test_wet_harvest_cuts_grading_probability():
    dry = quality.human_grade_probability(
        "green_lentil", harvest_rain_mm=25, may_days_above_20c=8,
        drought_stress_index=0.3, jun_heat_days_30c=3,
    )["prob"]
    wet = quality.human_grade_probability(
        "green_lentil", harvest_rain_mm=130, may_days_above_20c=8,
        drought_stress_index=0.3, jun_heat_days_30c=3,
    )["prob"]
    assert wet < dry * 0.75


def test_bruchid_hits_fava_bean_harder_than_chickpea():
    kw = dict(harvest_rain_mm=30, drought_stress_index=0.3, jun_heat_days_30c=3)
    hot, cool = 26, 8
    fava_drop = (
        quality.human_grade_probability("fava_bean", may_days_above_20c=cool, **kw)["prob"]
        - quality.human_grade_probability("fava_bean", may_days_above_20c=hot, **kw)["prob"]
    )
    chick_drop = (
        quality.human_grade_probability("chickpea", may_days_above_20c=cool, **kw)["prob"]
        - quality.human_grade_probability("chickpea", may_days_above_20c=hot, **kw)["prob"]
    )
    assert fava_drop > chick_drop


def test_vectorised_grading_matches_scalar():
    hr = np.array([20.0, 60.0, 120.0])
    md = np.array([8.0, 16.0, 24.0])
    ds = np.array([0.2, 0.9, 1.4])
    jh = np.array([2.0, 8.0, 14.0])
    vec = quality.human_grade_probability_vec(
        "green_lentil", harvest_rain_mm=hr, may_days_above_20c=md,
        drought_stress_index=ds, jun_heat_days_30c=jh,
    )
    for i in range(3):
        scalar = quality.human_grade_probability(
            "green_lentil", harvest_rain_mm=hr[i], may_days_above_20c=md[i],
            drought_stress_index=ds[i], jun_heat_days_30c=jh[i],
        )["prob"]
        assert vec[i] == pytest.approx(scalar)


def test_human_fraction_bounded_and_has_total_loss_mass():
    rng = np.random.default_rng(0)
    f = quality.sample_human_fraction(rng, np.full(5000, 0.6), 0.1)
    assert f.min() >= 0.0 and f.max() <= 1.0
    assert 0.05 < float((f == 0.0).mean()) < 0.2


def test_weather_sampling_preserves_real_dependence():
    """Drought and heat co-occur in nature; independent draws would lose that."""
    s = weather.sample_seasons("28", 4000, np.random.default_rng(1))
    r = np.corrcoef(s["flowering_water_balance_mm"], s["jun_heat_days_30c"])[0, 1]
    assert r < -0.3


def test_winter_pea_baseline_comes_from_agreste_not_a_hand_written_number():
    """Agreste publishes one pea series covering both habits.

    Before this was wired up, winter pea fell through to a reference constant and
    ranked first among candidates on a number that came from nobody's data.
    """
    for dept in ("21", "28", "32"):
        wp, wp_src = ml.baseline_yield("winter_pea", dept, "shallow_limestone")
        fp, _ = ml.baseline_yield("field_pea", dept, "shallow_limestone")
        assert wp_src.endswith("_via_proxy"), wp_src
        assert "crop_reference_table" not in wp_src
        # Tracks the spring-pea series with the documented winter-habit uplift.
        assert wp == pytest.approx(fp * 1.10, rel=1e-6)


def test_proxy_and_reference_baselines_are_flagged_to_the_user():
    _, wp_src = ml.baseline_yield("winter_pea", "21", "clay_loam")
    note = ml.baseline_caveat("winter_pea", wp_src)
    assert note and "winter" in note.lower()

    _, al_src = ml.baseline_yield("alfalfa", "21", "clay_loam")
    assert al_src == "crop_reference_table"
    assert "forage sheet" in (ml.baseline_caveat("alfalfa", al_src) or "")

    # A data-backed crop carries no such warning.
    _, fp_src = ml.baseline_yield("field_pea", "21", "clay_loam")
    assert ml.baseline_caveat("field_pea", fp_src) is None


def test_weather_only_departments_do_not_leak_into_training():
    """Some departments are carried for climate but have too little pulse area to label.

    They must appear in the weather panel so a parcel there gets a real local climate
    instead of the national pool, and must NOT appear in the training panel, where
    they would contribute a meaningless yield observation.
    """
    from pathlib import Path

    import pandas as pd
    from app.config import DATA_DIR

    root = Path(DATA_DIR).parent
    extra_path = root / "ml" / "weather_only_depts.txt"
    if not extra_path.exists():
        pytest.skip("no weather-only departments configured")
    extra = set(extra_path.read_text().split())
    assert extra, "weather_only_depts.txt is empty"

    w = pd.read_csv(Path(DATA_DIR) / "processed" / "weather_panel.csv", dtype={"dept_code": str})
    t = pd.read_csv(Path(DATA_DIR) / "processed" / "training_panel.csv", dtype={"dept_code": str})

    assert extra <= set(w["dept_code"]), "weather-only departments missing from the weather panel"
    assert not (extra & set(t["dept_code"])), "weather-only departments leaked into training"


def test_weather_only_department_yields_a_flagged_fallback_baseline():
    """Such a department has no yield history, so the baseline source must say so."""
    _, src = ml.baseline_yield("field_pea", "78", "deep_loam")
    assert src in {
        "agreste_same_soil_archetype", "agreste_national_mean", "crop_reference_table",
    }
    assert src != "agreste_department_history"


def test_weather_only_department_gets_its_own_local_climate():
    """Not the national pool: the sampled seasons must come from that department."""
    s = weather.sample_seasons("78", 500, np.random.default_rng(1))
    assert len(s) == 500
    summary = weather.climate_summary("78")
    assert summary["n_years"] >= 25
    assert "78" in weather.available_departments()


def test_legume_rotation_pressure_feature_has_no_gaps_and_is_bounded():
    """The weather bootstrap draws 30 years back; Agreste only covers 2010-2024.

    Every sampled season still has to carry a value for the new rotation-history
    feature, or roughly half of every simulation would silently feed NaN to a model
    that was never trained on NaN for this column.
    """
    from pathlib import Path

    import pandas as pd
    from app.config import DATA_DIR

    w = pd.read_csv(
        Path(DATA_DIR) / "processed" / "weather_panel.csv", dtype={"dept_code": str}
    )
    cols = ["legume_share_lag1", "legume_share_lag2to4_mean"]
    assert w[cols].isna().sum().sum() == 0
    for c in cols:
        assert w[c].min() >= 0.0
        assert w[c].max() <= 1.0


def test_legume_rotation_pressure_is_higher_in_a_high_pulse_department():
    """Gers has grown far more pulses than Eure-et-Loir for over a decade."""
    from pathlib import Path

    import pandas as pd
    from app.config import DATA_DIR

    w = pd.read_csv(
        Path(DATA_DIR) / "processed" / "weather_panel.csv", dtype={"dept_code": str}
    )
    recent = w[w["year"] == 2024]
    gers = float(recent.loc[recent["dept_code"] == "32", "legume_share_lag1"].iloc[0])
    beauce = float(recent.loc[recent["dept_code"] == "28", "legume_share_lag1"].iloc[0])
    assert gers > beauce * 2


def test_rotation_pressure_feature_is_a_real_trained_feature_not_a_decoration():
    """It must have non-zero gain in the trained model, not just exist in the schema."""
    b = ml.bundle()
    fi = b["feature_importance"]
    assert fi.get("legume_share_lag1", 0.0) > 0.0
    assert fi.get("legume_share_lag2to4_mean", 0.0) > 0.0


def test_rotation_pressure_feature_reaches_the_design_matrix_at_inference():
    s = weather.sample_seasons("21", 50, np.random.default_rng(2))
    b = ml.bundle()
    X = ml._design(s, "green_lentil", "shallow_limestone", b)
    assert "legume_share_lag1" in X.columns
    assert "legume_share_lag2to4_mean" in X.columns
    assert X["legume_share_lag1"].between(0.0, 1.0).all()


# --------------------------------------------------------------------------- #
# Borrowed yield baselines must always be flagged to the user
# --------------------------------------------------------------------------- #
def test_every_non_local_yield_baseline_warns_the_user():
    """Audited and found leaking: 60 of 240 pairs borrowed a baseline with no warning.

    `baseline_caveat` covered the hand-written reference table and the documented
    winter-pea proxy, but not `agreste_same_soil_archetype` (57 pairs) or
    `agreste_national_mean` (3). Those included Seine-et-Marne chickpea, which is the
    regional food view's headline "best for food" tonnage — a borrowed number presented
    as solidly as a measured one. Pinned so it cannot regress.
    """
    import numpy as np
    from app.config import departments, pulse_crops
    from app.services import ml, weather

    rng = np.random.default_rng(1)
    unwarned = []
    for dept, d in departments().items():
        if dept not in weather.available_departments():
            continue
        seasons = weather.sample_seasons(dept, 20, rng)
        for crop_key in pulse_crops():
            _, q = ml.sample_yields(rng, crop_key, dept, d["dominant_soil"], seasons)
            src = q["baseline_source"]
            if src == "agreste_department_history":
                continue  # the crop's own local data needs no caveat
            if ml.baseline_caveat(crop_key, src) is None:
                unwarned.append((dept, crop_key, src))
    assert not unwarned, f"baselines borrowed with no user warning: {unwarned[:8]}"


def test_borrowed_baseline_warning_names_the_weakness():
    """The warning has to say WHY it is weak, not merely that it is."""
    from app.services import ml

    soil = ml.baseline_caveat("chickpea", "agreste_same_soil_archetype")
    assert soil and "borrowed" in soil and "climate may not" in soil

    nat = ml.baseline_caveat("chickpea", "agreste_national_mean")
    assert nat and "weakest evidence" in nat

    # Borrowed AND proxied must report both problems, worst first.
    both = ml.baseline_caveat("winter_pea", "agreste_same_soil_archetype_via_proxy")
    assert both and "borrowed" in both and "proxy-derived" in both

    # A crop's own local history stays silent.
    assert ml.baseline_caveat("field_pea", "agreste_department_history") is None


def test_crop_dummies_carry_no_level_information_in_training():
    """Explains why crop_* ranks high in the importance chart, and pins it.

    The target is yield / department-crop historical mean, with the mean taken over the
    FIT block only. So in training the ratio averages exactly 1.0 for every crop, and a
    crop dummy cannot be predicting yield level — it is a gate the trees split on to
    learn crop-specific weather responses and crop-specific interval widths.

    If this ever stops being true, the importance chart's caption becomes wrong and the
    crop dummies really would be doing level correction, which is the baseline failing.
    """
    import pandas as pd

    df = pd.read_csv("data/processed/training_panel.csv", dtype={"dept_code": str})
    fit = df[df.year < 2017]
    dept = fit.groupby(["crop", "dept_code"])["yield_t_ha"].mean().rename("b")
    joined = fit.join(dept, on=["crop", "dept_code"])
    joined = joined[joined.b.notna() & (joined.b > 0)]
    ratio = joined.yield_t_ha / joined.b

    means = ratio.groupby(joined.crop).mean()
    assert means.max() - means.min() < 0.01, (
        f"crop ratio means have diverged ({means.to_dict()}); the baseline is no longer "
        "normalising per crop and the chart caption needs rewriting"
    )

    # And the thing a crop dummy legitimately IS needed for: residual spread differs
    # by crop by several multiples, so the quantile models need to know the crop.
    sds = ratio.groupby(joined.crop).std()
    assert sds.max() / sds.min() > 3, sds.to_dict()


def test_the_grading_model_does_not_claim_a_calibration_it_does_not_have():
    """An earlier _meta said base(crop) was set to match published market balances.

    Checked: no market-balance series exists in this repository and nothing pins those
    values to one. A false provenance claim is worse than no claim, because it invites
    trust and then loses it on inspection.
    """
    from app.config import load_ref

    meta = load_ref("quality")["_meta"]
    cal = meta["calibration"]
    assert "NOT CALIBRATED" in cal
    assert "expert judgement" in cal
    assert "treat every number in this file as a prior" in cal.lower()
