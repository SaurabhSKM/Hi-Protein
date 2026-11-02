#!/usr/bin/env python3
"""Exercise every endpoint against a running API and print a readable report."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

OK, BAD = "ok  ", "FAIL"


def call(base: str, path: str, body: dict | None = None, timeout: float = 90.0):
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"content-type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), 1000 * (time.perf_counter() - t0)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), 1000 * (time.perf_counter() - t0)
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}, 1000 * (time.perf_counter() - t0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    a = ap.parse_args()
    base = f"http://{a.host}:{a.port}"
    v = f"{base}/api/v1"

    parcel = {
        "department_code": "21", "parcel_id": "RPG-21-00421", "area_ha": 40.0,
        "soil_type": "shallow_limestone",
        # Cote-d'Or's own rotation, from refdata/dept_rotations.json.
        "baseline_rotation": ["soft_wheat", "rapeseed", "spring_barley"],
        "candidate_pulse_year2": "winter_pea",
        "crop_history": ["soft_wheat", "rapeseed", "soft_wheat", "winter_barley"],
        "n_simulations": 1500, "random_seed": 7,
    }

    checks: list[tuple[str, int, float, str]] = []

    def record(name, status, ms, detail="", want=200):
        checks.append((name, status, ms, detail))
        flag = OK if status == want else BAD
        print(f"  [{flag}] {name:34s} {status:>3}  {ms:7.0f} ms  {detail}")

    print(f"\nHi-Protein smoke test against {base}\n" + "-" * 86)

    st, d, ms = call(base, "/health")
    record("GET  /health", st, ms,
           f"model={d.get('model_version')} depts={d.get('weather_departments')} "
           f"offline={d.get('offline_mode')}")

    st, d, ms = call(v, "/reference")
    record("GET  /reference", st, ms,
           f"{len(d.get('crops', {}))} crops, {len(d.get('buyers', []))} buyers")

    st, d, ms = call(v, "/model-report")
    ce = (d or {}).get("calibration_effect", {})
    record("GET  /model-report", st, ms,
           f"coverage {ce.get('interval_coverage_raw')} -> {ce.get('interval_coverage_conformal')}")

    st, d, ms = call(v, "/yield-trend")
    worst = (d.get("crops") or [{}])[0]
    record("GET  /yield-trend", st, ms,
           f"worst {worst.get('crop')} {worst.get('change_pct')}%")

    st, d, ms = call(v, "/simulate-rotation", parcel)
    risk = d.get("financial_3yr_comparison_per_ha", {}).get("risk", {})
    record("POST /simulate-rotation", st, ms,
           f"delta {risk.get('median_delta_eur_ha')} EUR/ha, "
           f"P(win) {risk.get('prob_pulse_beats_baseline')}")

    sa = d.get("sorter_access") or {}
    record("  .. sorter access", st, 0,
           f"{sa.get('road_km')} km, {sa.get('haulage_cost_eur_ha_median')} EUR/ha haul, "
           f"stranded={sa.get('is_stranded')}")

    bf = d.get("breeder_fallback") or {}
    record("  .. breeder fallback", st, 0,
           f"CVaR15 {bf.get('cvar_without_fallback_eur_ha')} -> "
           f"{bf.get('cvar_with_fallback_eur_ha')} EUR/ha, "
           f"{len(bf.get('matches') or [])} holdings")

    mvc = ((d.get("financial_3yr_comparison_per_ha") or {})
           .get("risk_preference") or {}).get("minimum_viable_contract") or {}
    record("  .. minimum viable contract", st, 0, str(mvc.get("headline"))[:58])

    st, d, ms = call(v, "/simulate-rotation", {**parcel, "lon": 0.664, "lat": 48.984})
    sa = d.get("sorter_access") or {}
    record("POST /simulate-rotation (stranded)", st, ms,
           f"from {sa.get('measured_from')}, {sa.get('road_km')} km, "
           f"stranded={sa.get('is_stranded')}")

    st, d, ms = call(v, "/simulate-rotation", {**parcel, "selected_buyer_id": "BUY-ROQ-01"})
    r2 = d.get("financial_3yr_comparison_per_ha", {}).get("risk", {})
    record("POST /simulate-rotation (contract)", st, ms,
           f"bad-year {r2.get('delta_q15_eur_ha')} EUR/ha")

    st, d, ms = call(v, "/simulate-rotation",
                     {**parcel, "candidate_pulse_year2": "green_lentil",
                      "crop_history": ["rapeseed", "field_pea"]})
    record("POST /simulate-rotation (blocked)", st, ms,
           f"severity={d.get('agronomic_validation', {}).get('severity')}")

    st, d, ms = call(v, "/rank-candidates", parcel)
    top = (d.get("ranked") or [{}])[0]
    record("POST /rank-candidates", st, ms,
           f"best {top.get('crop')} at {top.get('median_delta_eur_ha')} EUR/ha")

    st, d, ms = call(v, "/parcel", {"lon": 1.4, "lat": 48.45})
    record("POST /parcel (live IGN RPG)", st, ms,
           f"found={d.get('found')} mode={d.get('provenance', {}).get('mode')} "
           f"{d.get('surface_ha')} ha")

    st, d, ms = call(v, "/regional-overview")
    tot = d.get("surface_totals") or {}
    record("GET  /regional-overview", st, ms,
           f"{len(d.get('departments', []))} departments, "
           f"{tot.get('stranded_ha')} ha stranded of {tot.get('total_convertible_ha')} "
           "convertible")

    st, d, ms = call(v, "/stranded-surface")
    record("GET  /stranded-surface", st, ms,
           f"{d.get('n_total')} communes, {d.get('n_returned')} returned")

    st, d, ms = call(v, "/optimise-sorters", {"k": 3})
    imp = d.get("impact") or {}
    sites = ", ".join(x["commune"] for x in (d.get("sites") or [])[:3])
    record("POST /optimise-sorters (greedy)", st, ms,
           f"{imp.get('hectares_unlocked')} ha, {imp.get('co2e_saved_tons')} t CO2e "
           f"[{sites}]")

    st, d, ms = call(v, "/optimise-sorters",
                     {"k": 2, "region_code": "FRB0", "verify_milp": True})
    mv = (d.get("optimisation") or {}).get("milp_verification") or {}
    record("POST /optimise-sorters (exact)", st, ms,
           f"greedy at {mv.get('greedy_share_of_optimum')} of the HiGHS optimum "
           f"(floor {mv.get('theoretical_floor')})")

    st, d, ms = call(v, "/breeders?lon=1.5&lat=48.3&pulse=field_pea&downgraded_lot_t=60")
    record("GET  /breeders", st, ms,
           f"{len(d.get('matches') or [])} holdings within "
           f"{d.get('radius_km')} km, pays "
           f"{(d.get('pricing') or {}).get('offered_price_eur_t')} EUR/t")

    st, d, ms = call(v, "/food-demand?n_simulations=300")
    nat = d.get("national", {})
    record("GET  /food-demand", st, ms,
           f"{len(d.get('regions', []))} regions, France grows "
           f"{nat.get('self_sufficiency_current_pct')}% of what it eats")

    st, d, ms = call(v, "/climate-outlook?department_code=28&crop=green_lentil&n_simulations=400")
    rows = d.get("rows") or []
    first, last = (rows[0] if rows else {}), (rows[-1] if rows else {})
    record("GET  /climate-outlook", st, ms,
           f"{len(rows)} horizons, food t/ha "
           f"{first.get('food_grade_tonnes_per_ha')} -> {last.get('food_grade_tonnes_per_ha')}")

    st, d, ms = call(v, "/simulate-rotation", {**parcel, "climate_horizon": "tracc_2050"})
    fo = d.get("food_outcome") or {}
    record("POST /simulate-rotation (TRACC 2050)", st, ms,
           f"food {fo.get('food_grade_tonnes_median')} t, feeds "
           f"{fo.get('people_fed_at_recommended_intake')} people")

    st, d, ms = call(v, "/dossier", parcel)
    record("POST /dossier", st, ms, f"{len(d.get('agronomic_checklist', []))} checklist items")

    st, d, ms = call(v, "/simulate-rotation", {**parcel, "candidate_pulse_year2": "soft_wheat"})
    record("POST /simulate-rotation (reject wheat)", st, ms, "rejects a non-legume", want=422)

    print("-" * 86)
    bad = [
        c[0] for c in checks
        if c[1] != (422 if "reject" in c[0] else 200)
    ]
    if bad:
        print(f"{len(bad)} check(s) FAILED: {', '.join(bad)}\n")
        return 1
    worst_ms = max(c[2] for c in checks)
    print(f"all {len(checks)} checks passed, slowest {worst_ms:.0f} ms\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
