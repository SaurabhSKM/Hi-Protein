"""End-to-end contract tests through the ASGI app."""
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
        "department_code": "28", "parcel_id": "RPG-28-09412", "area_ha": 45.0,
        "soil_type": "deep_loam", "has_livestock_ugb_5": False,
        "baseline_rotation": ["soft_wheat", "spring_barley", "rapeseed"],
        "candidate_pulse_year2": "field_pea", "n_simulations": 500, "random_seed": 3,
    }
    b.update(kw)
    return b


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_blueprint_contract_fields_all_present(client):
    """Every field name from the frozen Section 6 schema must still exist."""
    r = client.post(f"{BASE}/simulate-rotation", json=_body())
    assert r.status_code == 200, r.text
    d = r.json()
    assert {"crop_recommended", "agronomic_validation", "ml_predictions_year2",
            "financial_3yr_comparison_per_ha", "environmental_impact",
            "matched_offtake_contracts"} <= set(d)
    av = d["agronomic_validation"]
    assert {"is_valid", "return_interval_years", "terres_inovia_note"} <= set(av)
    ml = d["ml_predictions_year2"]
    assert {"yield_q15_t_ha", "yield_median_t_ha", "yield_q85_t_ha",
            "prob_human_grade"} <= set(ml)
    fin = d["financial_3yr_comparison_per_ha"]
    assert {"baseline_3yr_net_margin_eur", "pulse_rotation_median_eur",
            "pulse_rotation_worst_case_q15_eur", "breakdown_year2_year3_gains"} <= set(fin)
    brk = fin["breakdown_year2_year3_gains"]
    assert {"pac_coupled_aid_eur", "nitrogen_saved_year3_eur",
            "wheat_yield_boost_year3_eur"} <= set(brk)
    env = d["environmental_impact"]
    assert {"co2e_saved_tons_total", "synthetic_n_reduced_kg_total", "source"} <= set(env)


def test_every_numeric_block_carries_provenance(client):
    d = client.post(f"{BASE}/simulate-rotation", json=_body()).json()
    for key in ("agronomic_validation", "ml_predictions_year2",
                "financial_3yr_comparison_per_ha", "environmental_impact"):
        p = d[key]["provenance"]
        assert p["mode"] in {
            "live_api", "cached", "reference_table", "model_output", "assumption"
        }
        assert p["source"]


def test_quantiles_ordered_and_probabilities_bounded(client):
    d = client.post(f"{BASE}/simulate-rotation", json=_body()).json()
    ml = d["ml_predictions_year2"]
    assert ml["yield_q15_t_ha"] <= ml["yield_median_t_ha"] <= ml["yield_q85_t_ha"]
    assert 0.0 <= ml["prob_human_grade"] <= 1.0
    risk = d["financial_3yr_comparison_per_ha"]["risk"]
    assert 0.0 <= risk["prob_pulse_beats_baseline"] <= 1.0
    assert risk["delta_q15_eur_ha"] <= risk["median_delta_eur_ha"] <= risk["delta_q85_eur_ha"]


def test_whole_parcel_scales_with_area(client):
    small = client.post(f"{BASE}/simulate-rotation", json=_body(area_ha=10.0)).json()
    big = client.post(f"{BASE}/simulate-rotation", json=_body(area_ha=100.0)).json()
    a = small["financial_3yr_whole_parcel_eur"]["delta_median_eur"]
    b = big["financial_3yr_whole_parcel_eur"]["delta_median_eur"]
    assert b == pytest.approx(a * 10.0, rel=0.02)


def test_blocked_rotation_still_returns_200_with_warning_first(client):
    d = client.post(f"{BASE}/simulate-rotation", json=_body(
        candidate_pulse_year2="green_lentil", crop_history=["rapeseed", "field_pea"],
    )).json()
    assert d["agronomic_validation"]["is_valid"] is False
    assert d["agronomic_validation"]["severity"] == "blocked"
    assert "BLOCKED" in d["assumptions"][0]


def test_non_legume_candidate_rejected(client):
    r = client.post(f"{BASE}/simulate-rotation", json=_body(candidate_pulse_year2="soft_wheat"))
    assert r.status_code == 422
    assert "not a legume" in r.text


def test_unknown_crop_rejected(client):
    r = client.post(f"{BASE}/simulate-rotation", json=_body(candidate_pulse_year2="quinoa"))
    assert r.status_code == 422


def test_bad_rotation_length_rejected(client):
    r = client.post(f"{BASE}/simulate-rotation",
                    json=_body(baseline_rotation=["soft_wheat", "rapeseed"]))
    assert r.status_code == 422


def test_extra_field_rejected(client):
    """The contract is frozen, so an unexpected key must fail loudly."""
    r = client.post(f"{BASE}/simulate-rotation", json=_body(sneaky_field=1))
    assert r.status_code == 422


def test_contract_floor_improves_downside_through_api(client):
    free = client.post(f"{BASE}/simulate-rotation", json=_body(n_simulations=2000)).json()
    held = client.post(f"{BASE}/simulate-rotation", json=_body(
        n_simulations=2000, selected_buyer_id="BUY-ROQ-01")).json()
    assert (held["financial_3yr_comparison_per_ha"]["risk"]["delta_q15_eur_ha"]
            > free["financial_3yr_comparison_per_ha"]["risk"]["delta_q15_eur_ha"])


def test_rank_candidates_covers_every_pulse_and_sorts_blocked_last(client):
    d = client.post(f"{BASE}/rank-candidates", json=_body(n_simulations=400)).json()
    assert len(d["ranked"]) >= 5
    sev = [r["agronomic_severity"] == "blocked" for r in d["ranked"]]
    assert sev == sorted(sev)  # blocked candidates sink to the bottom


def test_carbon_conventions_differ_and_are_both_reported(client):
    d = client.post(f"{BASE}/simulate-rotation",
                    json=_body(carbon_convention="with_luc")).json()
    env = d["environmental_impact"]
    assert env["convention"] == "with_luc"
    assert env["co2e_saved_tons_total"] != env["co2e_saved_tons_other_convention"]


def test_reference_endpoint_feeds_the_frontend(client):
    d = client.get(f"{BASE}/reference").json()
    assert len(d["crops"]) > 10
    assert "field_pea" in d["pulse_crops"]
    assert d["departments"] and d["soils"] and d["buyers"]


def test_regional_overview_ranks_by_potential(client):
    d = client.get(f"{BASE}/regional-overview?n_simulations=200").json()
    assert d["departments"]
    pots = [r["conversion_potential_eur"] for r in d["departments"]]
    assert pots == sorted(pots, reverse=True)


def test_model_report_states_its_limitations(client):
    d = client.get(f"{BASE}/model-report").json()
    assert d["known_limitations"]
    ce = d["calibration_effect"]
    # Conformal calibration must bring coverage materially closer to target.
    off_raw = abs(ce["interval_coverage_raw"] - ce["interval_coverage_target"])
    off_cal = abs(ce["interval_coverage_conformal"] - ce["interval_coverage_target"])
    assert off_cal < off_raw


def test_yield_trend_reports_the_pulse_decline(client):
    d = client.get(f"{BASE}/yield-trend").json()
    by = {c["crop"]: c for c in d["crops"]}
    assert by["green_lentil"]["change_pct"] < by["soft_wheat"]["change_pct"]


def test_dossier_has_checklist_and_disclaimer(client):
    d = client.post(f"{BASE}/dossier", json=_body()).json()
    assert len(d["agronomic_checklist"]) >= 6
    assert "does not replace advice" in d["disclaimer"]
    assert any(s["title"] == "Decision summary" for s in d["sections"])


def test_parcel_lookup_shape(client):
    """Hits the live IGN API; tolerates it being unreachable."""
    r = client.post(f"{BASE}/parcel", json={"lon": 1.4, "lat": 48.45})
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"found", "history", "inferred_rotation", "provenance"}
    if d["found"]:
        assert d["geometry"]["type"] in {"Polygon", "MultiPolygon"}
        assert d["department_code"] == "28"


def test_out_of_france_coordinates_rejected(client):
    r = client.post(f"{BASE}/parcel", json={"lon": -74.0, "lat": 40.7})
    assert r.status_code == 422


def test_fallow_is_accepted_as_a_baseline_but_not_as_a_candidate(client):
    ok = client.post(f"{BASE}/simulate-rotation", json=_body(
        baseline_rotation=["soft_wheat", "fallow", "rapeseed"]))
    assert ok.status_code == 200
    rejected = client.post(f"{BASE}/simulate-rotation", json=_body(
        candidate_pulse_year2="fallow"))
    assert rejected.status_code == 422


def test_fallow_is_absent_from_the_candidate_ranking(client):
    d = client.post(f"{BASE}/rank-candidates", json=_body(n_simulations=300)).json()
    assert "fallow" not in {r["crop"] for r in d["ranked"]}


def test_winter_pea_response_discloses_its_proxied_baseline(client):
    d = client.post(f"{BASE}/simulate-rotation",
                    json=_body(candidate_pulse_year2="winter_pea")).json()
    blob = " ".join(d["assumptions"]) + d["ml_predictions_year2"]["provenance"]["caveat"]
    assert "pois proteagineux" in blob.lower()


def test_fallow_history_drives_the_bcae8_warning_and_strong_economics(client):
    """Shape of the real 5.8 ha Beauce parcel fallow since 2015."""
    d = client.post(f"{BASE}/simulate-rotation", json=_body(
        area_ha=5.8, baseline_rotation=["fallow", "fallow", "soft_wheat"],
        crop_history=["fallow"] * 6, n_simulations=800,
    )).json()
    av = d["agronomic_validation"]
    assert av["preceding_crop"] == "fallow"
    assert av["preceding_crop_suitability"] > 1.0
    assert av["observed_gap_years"] is None  # no Aphanomyces host in six years
    assert any("BCAE 8" in w for w in av["warnings"])
    risk = d["financial_3yr_comparison_per_ha"]["risk"]
    assert risk["prob_pulse_beats_baseline"] > 0.9


def test_unspecified_legume_cannot_be_chosen_as_a_candidate(client):
    """other_legume exists only to carry history; it has no predictable yield."""
    r = client.post(f"{BASE}/simulate-rotation",
                    json=_body(candidate_pulse_year2="other_legume"))
    assert r.status_code == 422
    d = client.get(f"{BASE}/reference").json()
    assert "other_legume" not in d["pulse_crops"]
    assert "other_legume" in d["crops"]


def test_environmental_impact_carries_monte_carlo_carbon_band(client):
    """co2e saved must come with a q15/q85 band, not just a point estimate."""
    d = client.post(f"{BASE}/simulate-rotation", json=_body()).json()
    env = d["environmental_impact"]
    assert {"co2e_saved_tons_q15", "co2e_saved_tons_q85",
            "carbon_abatement_cost_eur_per_tonne"} <= set(env)
    assert env["co2e_saved_tons_q15"] <= env["co2e_saved_tons_total"]
    assert env["co2e_saved_tons_total"] <= env["co2e_saved_tons_q85"]


def test_ml_provenance_mentions_the_rotation_pressure_feature(client):
    """The trained model's own description must say it uses rotation history."""
    d = client.post(f"{BASE}/simulate-rotation", json=_body()).json()
    assert "legume" in d["ml_predictions_year2"]["provenance"]["source"].lower()
