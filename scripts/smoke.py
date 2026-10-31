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
        "baseline_rotation": ["soft_wheat", "spring_barley", "rapeseed"],
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

    st, d, ms = call(v, "/regional-overview?n_simulations=400")
    record("GET  /regional-overview", st, ms,
           f"{len(d.get('departments', []))} departments, "
           f"{d.get('total_gap_ha')} ha gap")

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
