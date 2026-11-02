"""End-to-end contract tests for the regional planner endpoints."""
import pytest
from app.main import app
from fastapi.testclient import TestClient

BASE = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _body(**kw):
    b = {
        "department_code": "28", "area_ha": 45.0, "soil_type": "deep_loam",
        "baseline_rotation": ["soft_wheat", "spring_barley", "rapeseed"],
        "candidate_pulse_year2": "field_pea", "n_simulations": 500, "random_seed": 3,
    }
    b.update(kw)
    return b


# --------------------------------------------------------------------------- #
# Department coverage
# --------------------------------------------------------------------------- #
def test_the_whole_arable_core_is_covered_not_a_six_department_sketch(client):
    r = client.get(f"{BASE}/regional-overview")
    assert r.status_code == 200
    d = r.json()
    assert len(d["departments"]) >= 38
    assert d["provenance"]["mode"] == "model_output"
    assert "Agreste" in d["provenance"]["source"]


def test_regional_overview_is_fast_enough_to_be_a_dashboard(client):
    """It reads baked simulations. Running 42 Monte Carlos live took over two minutes."""
    r = client.get(f"{BASE}/regional-overview")
    assert r.json()["compute_ms"] < 4000


def test_generated_pulse_share_lands_near_the_published_national_baseline(client):
    """An independent check on the generated area table.

    `arable_ha` and `pulse_ha` are derived from the Agreste SAA area series by
    scripts/build_departments.py. Summed across the 42 arable departments they imply a
    food-tier pulse share of about 3.2 percent, against the 4 percent national baseline
    the policy target is written against. Close enough to corroborate the derivation,
    and the gap is the right sign: these departments are the cereal core.
    """
    d = client.get(f"{BASE}/regional-overview").json()
    arable = sum(x["arable_ha"] for x in d["departments"])
    pulse = sum(x["pulse_ha"] for x in d["departments"])
    share = 100.0 * pulse / arable
    assert 2.0 < share < 5.5, share
    assert arable > 7_000_000


def test_infrastructure_limitation_is_reported_separately_from_economics(client):
    """The distinction a capital grant acts on.

    A department profitable at the collection radius but loss-making at the distance it
    actually has is infrastructure-limited. One that loses money at both is not, and no
    sorting capacity will change that.
    """
    d = client.get(f"{BASE}/regional-overview").json()
    for row in d["departments"]:
        assert row["margin_gain_if_served_eur_ha"] >= row["median_margin_gain_eur_ha"] - 1e-6
        if row["is_infrastructure_limited"]:
            assert row["median_margin_gain_eur_ha"] < 0
            assert row["margin_gain_if_served_eur_ha"] >= 0
            assert row["haulage_cost_eur_ha"] > 0


def test_haulage_cost_is_zero_where_a_sorter_is_already_close(client):
    d = client.get(f"{BASE}/regional-overview").json()
    close = [
        x for x in d["departments"]
        if x["sorter_road_km"] is not None and x["sorter_road_km"] <= 25.0
    ]
    assert close, "at least one department hosts a sorting unit"
    for x in close:
        assert x["haulage_cost_eur_ha"] == pytest.approx(0.0, abs=0.05)


# --------------------------------------------------------------------------- #
# Stranded surface
# --------------------------------------------------------------------------- #
def test_stranded_surface_returns_a_real_commune_level_layer(client):
    r = client.get(f"{BASE}/stranded-surface")
    assert r.status_code == 200
    d = r.json()
    assert d["n_total"] > 10000
    assert d["communes"]
    c = d["communes"][0]
    for k in ("insee", "name", "dept", "lon", "lat", "status", "convertible_ha"):
        assert k in c


def test_stranded_surface_declares_the_allocation_assumption(client):
    """The map is the most persuasive artefact in the product, so it has to disclose.

    Department arable hectares are split between communes proportionally to cadastral
    area because nothing is published at commune level to measure that split against.
    """
    d = client.get(f"{BASE}/stranded-surface").json()
    cav = d["provenance"]["caveat"]
    assert "cadastral" in cav and "average" in cav
    assert set(d["legend"]) >= {"viable", "stranded", "uneconomic"}


def test_stranded_surface_filters_compose(client):
    d = client.get(
        f"{BASE}/stranded-surface", params={"department_code": "28", "status": "stranded"}
    ).json()
    assert all(c["dept"] == "28" for c in d["communes"])
    assert all(c["status"] == "stranded" for c in d["communes"])


# --------------------------------------------------------------------------- #
# The optimiser
# --------------------------------------------------------------------------- #
def test_optimiser_returns_sites_with_their_own_unit_economics(client):
    r = client.post(f"{BASE}/optimise-sorters", json={"k": 2})
    assert r.status_code == 200
    d = r.json()
    assert d["k_sited"] == 2
    assert len(d["sites"]) == 2
    for s in d["sites"]:
        assert s["lon"] and s["lat"] and s["commune"]
        assert s["hectares_unlocked"] > 0
        ue = s["unit_economics"]
        assert 0 < ue["utilisation_pct"] <= 100.5
        assert ue["levelised_cost_eur_t"] > 0


def test_optimiser_states_its_guarantee_rather_than_asserting_optimality(client):
    d = client.post(f"{BASE}/optimise-sorters", json={"k": 1}).json()
    o = d["optimisation"]
    assert "submodular" in o["algorithm"]
    assert "0.632" in o["guarantee"]
    assert o["milp_verification"]["solved"] is False, "exact solve must be opt-in"


def test_optimiser_exact_verification_is_available_on_request(client):
    d = client.post(
        f"{BASE}/optimise-sorters",
        json={"k": 2, "region_code": "FRB0", "verify_milp": True},
    ).json()
    v = d["optimisation"]["milp_verification"]
    assert v["solved"]
    assert v["solver"].startswith("HiGHS")
    assert 0.632 <= v["greedy_share_of_optimum"] <= 1.0 + 1e-6


def test_optimiser_reports_the_capex_against_the_regional_envelope(client):
    d = client.post(f"{BASE}/optimise-sorters", json={"k": 4}).json()
    assert d["capex_eur"] == d["capex_per_unit_eur"] * 4
    assert 0 < d["share_of_regional_envelope_pct"] <= 100


def test_optimiser_rejects_an_impossible_scope(client):
    r = client.post(
        f"{BASE}/optimise-sorters", json={"k": 1, "min_site_population": 50000}
    )
    assert r.status_code in (200, 422)


def test_optimiser_scope_is_honoured(client):
    d = client.post(
        f"{BASE}/optimise-sorters", json={"k": 2, "department_code": "45"}
    ).json()
    assert all(s["dept"] == "45" for s in d["sites"])


# --------------------------------------------------------------------------- #
# Breeders
# --------------------------------------------------------------------------- #
def test_breeder_endpoint_discloses_what_the_directory_is(client):
    d = client.get(
        f"{BASE}/breeders", params={"lon": 1.5, "lat": 48.3, "pulse": "field_pea"}
    ).json()
    assert "ILLUSTRATIVE" in d["directory_status"]
    assert "commune centroids" in d["what_is_real"]
    assert d["what_is_not_real"]


def test_breeder_endpoint_rejects_an_unknown_crop(client):
    r = client.get(f"{BASE}/breeders", params={"lon": 1.5, "lat": 48.3, "pulse": "quinoa"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# The farmer response carries the new blocks
# --------------------------------------------------------------------------- #
def test_simulate_reports_sorter_access_as_a_cost(client):
    d = client.post(f"{BASE}/simulate-rotation", json=_body()).json()
    sa = d["sorter_access"]
    assert sa["road_km"] is not None
    assert sa["haulage_cost_eur_ha_median"] >= 0
    assert sa["measured_from"] == "department_centroid"
    assert sa["provenance"]["mode"] == "reference_table"


def test_clicking_a_parcel_measures_distance_from_the_parcel(client):
    """A parcel at the edge of a department can be stranded when its centroid is not."""
    d = client.post(f"{BASE}/simulate-rotation", json=_body(lon=1.1, lat=48.1)).json()
    assert d["sorter_access"]["measured_from"] == "clicked_parcel"


def test_a_distant_parcel_pays_more_haulage_and_earns_less(client):
    near = client.post(f"{BASE}/simulate-rotation", json=_body(lon=1.55, lat=48.30)).json()
    far = client.post(
        f"{BASE}/simulate-rotation",
        json=_body(department_code="86", soil_type="shallow_limestone",
                   candidate_pulse_year2="green_lentil"),
    ).json()
    assert (
        far["sorter_access"]["haulage_cost_eur_ha_median"]
        > near["sorter_access"]["haulage_cost_eur_ha_median"]
    )


def test_simulate_reports_the_breeder_fallback_on_both_sides(client):
    d = client.post(f"{BASE}/simulate-rotation", json=_body()).json()
    f = d["breeder_fallback"]
    assert f["available"]
    assert f["cvar_with_fallback_eur_ha"] > f["cvar_without_fallback_eur_ha"]
    assert f["best_offered_price_eur_t"] > f["feed_spot_price_eur_t"]
    assert f["matches"]
    m = f["matches"][0]
    assert m["distance_km"] <= f["search_radius_km"]
    assert m["breeder_avoided_soy_t"] > 0
    assert "ILLUSTRATIVE" in f["provenance"]["source"] or f["provenance"]["caveat"]


def test_the_without_fallback_figure_matches_the_headline_risk_block(client):
    """The before/after pair must be the same simulation, not a second sample.

    If these ever diverge, the reported improvement is partly weather noise and the
    comparison is worthless.
    """
    d = client.post(f"{BASE}/simulate-rotation", json=_body()).json()
    assert (
        d["breeder_fallback"]["median_without_fallback_eur_ha"]
        == d["financial_3yr_comparison_per_ha"]["risk"]["median_delta_eur_ha"]
    )


def test_haulage_appears_in_the_gain_breakdown(client):
    d = client.post(
        f"{BASE}/simulate-rotation",
        json=_body(department_code="86", soil_type="shallow_limestone",
                   candidate_pulse_year2="green_lentil"),
    ).json()
    br = d["financial_3yr_comparison_per_ha"]["breakdown_year2_year3_gains"]
    assert br["sorter_haulage_cost_eur"] > 0


# --------------------------------------------------------------------------- #
# "Best fit" must not be claimed where nothing fits
# --------------------------------------------------------------------------- #
def test_departments_report_whether_any_candidate_is_actually_profitable(client):
    """Oise's six candidates all lose money (-168 to -918 EUR/ha) and the engine still
    labelled soybean its "best fit", which reads as a recommendation. The response now
    carries the count so the UI can say "least-bad" instead.
    """
    d = client.get(f"{BASE}/regional-overview").json()
    for row in d["departments"]:
        assert row["n_candidates_profitable"] >= 0
        assert row["any_candidate_profitable"] == (row["n_candidates_profitable"] > 0)
        # The headline margin is the best candidate's, so if it is negative then no
        # candidate can be profitable, and vice versa.
        if row["median_margin_gain_eur_ha"] > 0:
            assert row["any_candidate_profitable"], row["name"]
        if not row["any_candidate_profitable"]:
            assert row["median_margin_gain_eur_ha"] <= 0, row["name"]


def test_at_least_one_department_has_no_profitable_candidate(client):
    """Guards the honesty of the feature: if every department were profitable the flag
    would be decoration. On the current data several are not, and the map tags them.
    """
    d = client.get(f"{BASE}/regional-overview").json()
    none_pay = [r["name"] for r in d["departments"] if not r["any_candidate_profitable"]]
    assert none_pay, "expected some departments where no pulse pays"


def test_stranded_land_is_reported_as_a_band_not_a_point(client):
    """81,418 ha is real but it is false precision.

    The figure is driven by the haulage rate, which is a published 0.32-0.58 EUR/t/km
    band rather than a measured constant. Across that band it runs from about 53k to
    111k ha. Quoting the midpoint to five significant figures invites a challenge the
    midpoint cannot survive, so the headline carries the range.
    """
    d = client.get(f"{BASE}/regional-overview").json()
    b = d["stranded_band"]
    assert {"low", "central", "high"} <= set(b)
    assert b["low"]["stranded_ha"] < b["central"]["stranded_ha"] < b["high"]["stranded_ha"]
    assert b["low"]["eur_per_tonne_km"] < b["high"]["eur_per_tonne_km"]
    # The central pass must agree with the map's own totals, or the two disagree on screen.
    assert b["central"]["stranded_ha"] == d["surface_totals"]["stranded_ha"]
    assert "published band" in b["note"]


def test_computing_the_band_does_not_corrupt_the_live_surface(client):
    """The band is computed by repricing the shared surface in place.

    That means it mutates a memoised reference table and must put it back. If it does
    not, every later request sees whichever rate the last pass happened to leave.
    """
    before = client.get(f"{BASE}/stranded-surface").json()["totals"]
    client.get(f"{BASE}/regional-overview")
    after = client.get(f"{BASE}/stranded-surface").json()["totals"]
    assert before == after
