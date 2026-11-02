"""Tests for the land-change view: the data, the rollups and the endpoints.

The emphasis is on the claims the page makes in words. A chart that renders from a
plausible-looking payload is not the failure mode worth guarding against; a page that
says "the share tripled" when the underlying series broke, or that quietly loses the
zero rows an arrival depends on, is. So these tests assert the SUBSTANCE: that zeros
survive, that the denominator is consistent, that the attribution's null result is
still a null result, and that the RPG vocabulary break is still detected.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import adoption

client = TestClient(app)

PULSES = ("green_lentil", "chickpea", "field_pea", "fava_bean", "soybean")


@pytest.fixture(scope="module")
def panel():
    return adoption.panel()


@pytest.fixture(scope="module")
def overview():
    r = client.get("/api/v1/adoption/overview")
    assert r.status_code == 200
    return r.json()


# --------------------------------------------------------------------------- #
# The panel itself
# --------------------------------------------------------------------------- #
def test_panel_keeps_zero_area_rows(panel):
    """The whole point of the adoption panel: area == 0 means "not grown", and
    dropping it makes a department's first hectare look like the start of the series
    rather than an arrival."""
    assert (panel["area_ha"] == 0).sum() > 0
    # And no blank areas, which are a missing publication rather than a zero.
    assert panel["area_ha"].notna().all()


def test_panel_covers_more_departments_than_the_training_panel(panel):
    """The yield model is limited to departments with Meteo-France weather; the
    descriptive view is not, and that difference is the reason this panel exists
    separately."""
    assert panel["dept_code"].nunique() > 42


def test_panel_excludes_provisional_year(panel):
    """The Agreste workbook header states 2025 is provisional. It must not appear."""
    assert panel["year"].max() == 2024
    assert panel["year"].min() == 2010


def test_crop_share_matches_its_own_denominator(panel):
    """share = area / cop_area, with cop_area the dept-year total over mapped crops.
    If these ever disagree the map and the charts are drawing different quantities."""
    d = panel[panel["cop_area_ha"] > 0].head(2000)
    recomputed = d["area_ha"] / d["cop_area_ha"]
    assert (recomputed - d["crop_share"]).abs().max() < 1e-9


def test_every_pulse_is_present(panel):
    assert set(PULSES) <= set(panel["crop"])


# --------------------------------------------------------------------------- #
# National rollup
# --------------------------------------------------------------------------- #
def test_overview_reports_opposite_directions(overview):
    """The finding the page leads with: human-food pulses multiplied while
    animal-feed pulses fell. If this ever flips, the page's headline prose is wrong
    and should fail loudly rather than quietly contradict the chart beside it."""
    h = overview["headline"]
    assert h["green_lentil"]["multiple_first_to_last"] > 1.5
    assert h["chickpea"]["multiple_first_to_last"] > 1.5
    assert h["field_pea"]["multiple_first_to_last"] < 1.0
    assert h["fava_bean"]["multiple_first_to_last"] < 1.0


def test_overview_reports_peak_not_just_endpoints(overview):
    """Four of the five crops peaked before the last year. A view that compared only
    first and last would describe a plateau-and-retreat as steady growth."""
    h = overview["headline"]
    off_peak = [c for c in PULSES if h[c]["peak_year"] < h[c]["last_year"]]
    assert len(off_peak) >= 3
    for crop in PULSES:
        assert h[crop]["peak_area_ha"] >= h[crop]["last_area_ha"]


def test_national_area_equals_sum_of_departments(overview, panel):
    """Guards the rollup against double counting or a dropped department."""
    for crop in PULSES:
        for row in overview["series"][crop]:
            if row["area_ha"] is None:
                continue
            expected = panel[
                (panel["crop"] == crop) & (panel["year"] == row["year"])
            ]["area_ha"].sum()
            assert row["area_ha"] == pytest.approx(expected, abs=0.5)


def test_arrivals_require_the_zero_rows(overview):
    """An arrival is area == 0 in the first year and > 0 in the last, which is only
    observable because the panel keeps the zeros."""
    assert overview["arrivals"]["total_department_crop_arrivals"] > 0


def test_national_yield_is_area_weighted(overview, panel):
    crop, year = "green_lentil", 2024
    row = next(r for r in overview["series"][crop] if r["year"] == year)
    d = panel[(panel["crop"] == crop) & (panel["year"] == year)]
    d = d[d["area_ha"] > 0].dropna(subset=["yield_t_ha"])
    weighted = (d["yield_t_ha"] * d["area_ha"]).sum() / d["area_ha"].sum()
    assert row["yield_t_ha"] == pytest.approx(weighted, abs=1e-3)
    # An unweighted mean would be a different number; this asserts we did not ship it.
    assert row["yield_t_ha"] != pytest.approx(d["yield_t_ha"].mean(), abs=1e-6)


# --------------------------------------------------------------------------- #
# Departments
# --------------------------------------------------------------------------- #
def test_departments_endpoint_and_geometry_align():
    r = client.get("/api/v1/adoption/departments?crop=green_lentil")
    assert r.status_code == 200
    data = r.json()
    geo = client.get("/api/v1/adoption/geometry").json()
    matched = [d for d in data["departments"] if d["dept_code"] in geo]
    # A choropleth that silently drops departments is the bug this catches.
    assert len(matched) / len(data["departments"]) > 0.95


def test_department_share_series_is_complete():
    data = client.get("/api/v1/adoption/departments?crop=chickpea").json()
    years = {str(y) for y in data["years"]}
    for d in data["departments"][:10]:
        assert set(d["share_pct_by_year"]) == years
        assert set(d["area_ha_by_year"]) == years


def test_unknown_crop_is_404():
    assert client.get("/api/v1/adoption/departments?crop=banana").status_code == 404


# --------------------------------------------------------------------------- #
# Attribution: the null result must stay a null result
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def attribution():
    r = client.get("/api/v1/adoption/attribution")
    assert r.status_code == 200
    return r.json()


def test_weather_does_not_explain_adoption(attribution):
    """The page states that weather explains nothing once a national shock and a
    department effect are accounted for. If a future panel or feature set changes
    that, the prose must change too, so this asserts the claim rather than the
    machinery."""
    increments = [
        r["variance_explained_increment_pct"]["weather_and_soil"]
        for r in attribution["decomposition"]
        if "variance_explained_increment_pct" in r
    ]
    assert increments, "decomposition produced nothing"
    # Cross-fitted, so "adds nothing" means at or below zero for most crops.
    assert sum(1 for v in increments if v <= 0) >= len(increments) - 1


def test_cross_fitted_weather_is_far_below_in_sample(attribution):
    """The guard against the specific mistake this analysis was built to avoid:
    an in-sample fit on 12 weather columns reports weather explaining most of the
    variance, and that number is an artifact."""
    for r in attribution["decomposition"]:
        check = r.get("weather_stage_overfit_check_pct")
        if not check:
            continue
        assert check["in_sample"] > check["cross_fitted_by_year"]


def test_held_out_model_does_not_beat_no_change(attribution):
    skills = [
        r["skill_vs_no_change_pct"]
        for r in attribution["held_out_prediction"]
        if r.get("skill_vs_no_change_pct") is not None
    ]
    assert skills
    # Allow a crop or two of marginal positive skill; the claim is that there is no
    # material predictive power, not that every number is negative.
    assert max(skills) < 20


def test_attribution_lists_what_it_cannot_observe(attribution):
    drivers = " ".join(attribution["unobserved_drivers"]).lower()
    for term in ("price", "coupled aid", "contract"):
        assert term in drivers


def test_weather_features_are_lagged(attribution):
    """Using season t's weather to explain season t's planting decision would be
    leakage dressed as insight."""
    assert "t-1" in attribution["lag_policy"]
    for r in attribution["decomposition"]:
        for name in r.get("weather_importance_top8", {}):
            if name in ("reserve_utile_mm", "soil_ph"):
                continue
            if name.startswith("share_pp") or name.startswith("yield_ratio"):
                continue
            assert name.endswith("_lag1"), f"{name} is not lagged"


# --------------------------------------------------------------------------- #
# RPG: the vocabulary break must stay detected
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def rpg():
    r = client.get("/api/v1/adoption/rpg-change")
    assert r.status_code == 200
    return r.json()


def test_rpg_detects_the_2023_vocabulary_change(rpg):
    """The trap: taken at face value the region's pulse share rises sharply across
    2023, and most of that is three codes that did not exist before that campaign."""
    v = rpg["vocabulary_change_2023"]
    codes = {s["code_cultu"] for s in v["pulse_codes_introduced_in_2023"]}
    assert codes, "no introduced codes detected"
    # Each one must be absent from the older code table and appear only from 2023.
    for s in v["pulse_codes_introduced_in_2023"]:
        assert s["absent_from_2022_code_table"] is True
        assert s["first_year_present_in_region"] >= 2023
        assert s["ha_in_first_year"] > 0


def test_introduced_codes_are_zero_before_they_existed(rpg):
    suspects = {s["code_cultu"] for s in
                rpg["vocabulary_change_2023"]["pulse_codes_introduced_in_2023"]}
    for row in rpg["pulse_code_series"]:
        if row["code_cultu"] not in suspects:
            continue
        for year, ha in row["ha_by_year"].items():
            if int(year) < 2023:
                assert ha == 0, f"{row['code_cultu']} has {ha} ha in {year}"


def test_like_for_like_share_is_lower_than_published(rpg):
    """The honest number has to be smaller after the break and identical before it."""
    totals = rpg["totals_by_year"]
    assert totals["2024"]["pulse_share_pct_like_for_like"] < totals["2024"]["pulse_share_pct"]
    for year in ("2015", "2022"):
        assert (totals[year]["pulse_share_pct_like_for_like"]
                == pytest.approx(totals[year]["pulse_share_pct"]))


def test_lentil_growth_is_real(rpg):
    """LEC is in the 2022, 2023 and 2024 code tables alike and declared in every
    campaign, so lentil growth needs no adjustment and is the clean signal."""
    totals = rpg["totals_by_year"]
    assert totals["2024"]["lentil_ha"] > 2 * totals["2015"]["lentil_ha"]


def test_rpg_pulse_definition_uses_official_groups(rpg):
    """Taking the pulse total from the project's yield-model crop map instead would
    drop MPC and PAG and miss lupin entirely."""
    d = rpg["_meta"]["pulse_definition"]
    assert "8" in d and "15" in d and "SOJ" in d


def test_rpg_declines_to_match_parcels_across_years(rpg):
    """id_parcel is not stable between campaigns, so a field-level before/after claim
    would be invention. The artifact has to say so."""
    assert "not stable" in rpg["_meta"]["no_parcel_matching"]


def test_rpg_declared_area_is_from_surf_parc(rpg):
    assert "surf_parc" in rpg["_meta"]["area_basis"]


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def test_every_artifact_states_its_source(overview, attribution, rpg):
    assert "Agreste" in overview["provenance"]["area_source"]
    assert overview["provenance"]["denominator"]
    assert "2025 provisoires" in overview["provenance"]["agreste_data_cutoff"]
    assert attribution["coverage"]["reason"]
    assert "RPG" in rpg["_meta"]["source"]


def test_quality_status_is_reported_not_interpreted(overview):
    """Agreste's STATUT_QUALITE codes are defined only by reference to a methodology
    page that currently errors, so the panel reports the mix and declines to claim it
    knows what 1, 2, 3 and NC mean."""
    prov = overview["provenance"]
    mix = prov["quality_status_mix_pulse_area_pct"]
    assert sum(mix.values()) == pytest.approx(100.0, abs=0.1)
    assert "not interpreted" in prov["quality_status_caveat"].lower()


def test_missing_artifact_returns_503(monkeypatch, tmp_path):
    """A missing bake must say which script to run, not 500."""
    monkeypatch.setattr(adoption, "RPG_CHANGE_PATH", tmp_path / "nope.json")
    adoption.rpg_change.cache_clear()
    try:
        r = client.get("/api/v1/adoption/rpg-change")
        assert r.status_code == 503
        assert "build_rpg_change" in r.json()["detail"]
    finally:
        adoption.rpg_change.cache_clear()


def test_artifacts_are_valid_json_on_disk():
    for path in (adoption.PANEL_META_PATH, adoption.ATTRIBUTION_PATH,
                 adoption.RPG_CHANGE_PATH, adoption.GEOM_PATH):
        assert path.exists(), path
        json.loads(path.read_text(encoding="utf-8"))
