"""Build the commune-level demand surface the siting optimiser runs on.

Why communes and not RPG parcels. The optimiser's question is "where does a 450k EUR
optical sorter go", and the answer moves at the scale of tens of kilometres. Individual
RPG parcels are the wrong grain for that: there are 9.5 million of them, the WFS serves
them with full polygon geometry, and aggregating them nationally would be a day of
downloading to produce a surface that is identical, at 80 km resolution, to the one
below. Communes give roughly 15,000 real demand points across the 42 departments this
project has weather and yield data for, each with real IGN geometry and real cadastral
area, which is the right grain and is honest about being an aggregate.

What is real here and what is assumed, stated plainly because the heatmap is the most
visually persuasive thing in the product and it should not overclaim:

* REAL: commune boundary geometry and centroid (IGN ADMINEXPRESS), commune cadastral
  area in hectares (IGN, from the cadastre), department and region codes (INSEE via
  IGN), commune population (INSEE census).
* REAL: each department's total arable hectares and total pulse hectares, from the
  Agreste SAA departmental area series, the same file that provides this project's
  yield labels.
* ASSUMED: the split of a department's arable hectares BETWEEN its communes, which is
  taken proportional to cadastral area. Agreste publishes no commune-level areas, so
  there is nothing to measure this against. It is right on average and wrong for any
  individual commune - a commune that is mostly forest or town gets credited with
  arable land it does not have.

The consequence of that last point is bounded and worth stating: the optimiser sums
demand over an 80 km radius containing hundreds of communes, so the allocation error
averages out at the scale the DECISION is made at, even though it is visible at the
scale the MAP is drawn at.

Run: python scripts/build_communes.py
Output: data/processed/communes.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "processed" / "communes.json"

WFS = "https://data.geopf.fr/wfs/ows"
LAYER = "ADMINEXPRESS-COG.LATEST:commune"
UA = {"User-Agent": "hiprotein-hackathon/1.0"}

# The departments this project has Meteo-France weather for. Keeping the commune
# surface to exactly this set means every point on the map is backed by a department
# the yield model can actually make a prediction for.
DEPTS = [
    "01", "02", "10", "11", "14", "16", "17", "18", "21", "27", "28", "31", "32",
    "36", "37", "38", "39", "40", "41", "45", "47", "51", "52", "54", "55", "58",
    "60", "64", "65", "68", "70", "71", "77", "78", "79", "80", "81", "82", "85",
    "86", "89", "91",
]


def fetch_dept(dept: str) -> list[dict]:
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": LAYER,
        "OUTPUTFORMAT": "application/json",
        "SRSNAME": "CRS:84",
        "COUNT": "5000",
        "CQL_FILTER": f"code_insee_du_departement='{dept}'",
    }
    r = requests.get(WFS, params=params, headers=UA, timeout=180)
    r.raise_for_status()
    return r.json().get("features") or []


def centroid_of(geom: dict) -> tuple[float, float] | None:
    """Area-weighted centroid of a (multi)polygon, in lon/lat.

    Shapely's planar centroid on geographic coordinates is a small approximation at
    commune scale - a few hundred metres at French latitudes - which is immaterial
    against an 80 km haulage radius.
    """
    try:
        g = shape(geom)
        if g.is_empty:
            return None
        c = g.representative_point() if not g.is_valid else g.centroid
        return (round(float(c.x), 5), round(float(c.y), 5))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    rows: list[dict] = []
    for i, dept in enumerate(DEPTS, 1):
        for attempt in (1, 2, 3):
            try:
                feats = fetch_dept(dept)
                break
            except Exception as e:  # noqa: BLE001
                print(f"  dept {dept} attempt {attempt} failed: {e}")
                if attempt == 3:
                    feats = []
                time.sleep(2 * attempt)
        kept = 0
        for f in feats:
            p = f.get("properties") or {}
            c = centroid_of(f.get("geometry") or {})
            if c is None:
                continue
            area = p.get("superficie_cadastrale")
            if not area or float(area) <= 0:
                continue
            rows.append({
                "insee": p.get("code_insee"),
                "name": p.get("nom_officiel"),
                "dept": p.get("code_insee_du_departement"),
                "insee_region": p.get("code_insee_de_la_region"),
                "lon": c[0],
                "lat": c[1],
                "cadastral_ha": int(area),
                "population": int(p.get("population") or 0),
            })
            kept += 1
        print(f"[{i}/{len(DEPTS)}] dept {dept}: {kept} communes")

    if not rows:
        print("No communes fetched. Is the network reachable?")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {
            "source": "IGN ADMINEXPRESS-COG.LATEST:commune via data.geopf.fr WFS 2.0.0",
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "n_communes": len(rows),
            "departments": sorted({r["dept"] for r in rows}),
            "fields": {
                "cadastral_ha": "Commune cadastral area, hectares, from the IGN field "
                                "superficie_cadastrale. NOT arable area: the arable share "
                                "is applied per department at load time from Agreste.",
                "lon_lat": "Area-weighted polygon centroid in WGS84.",
            },
        },
        "communes": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    size_mb = OUT.stat().st_size / 1e6
    print(f"\nWrote {len(rows)} communes to {OUT} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
