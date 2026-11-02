"""Bake the national pulse-adoption panel: which French land moved to legumes, and when.

WHY THIS IS AGRESTE AND NOT RPG
-------------------------------
RPG is the authoritative parcel-level record of what is actually grown, and it is
what `clients/ign_rpg.py` queries for a single field. It is the wrong source for a
NATIONAL time series: 9.5 million polygons per campaign and ten published campaigns
(2015-2024 on the Geoplateforme WFS) is roughly a day of downloading to answer a
question that department-level Agreste already answers for 2010-2024, across 97
departments rather than the 42 this project has weather for. RPG earns its place on
the page as the ZOOM-IN - one region, two campaigns, real field boundaries - which is
what `scripts/build_rpg_change.py` produces.

WHAT MAKES THIS DIFFERENT FROM THE TRAINING PANEL
-------------------------------------------------
`data/processed/training_panel.csv` exists to fit a yield model, so it keeps only
rows with a published yield. That filter silently deletes the most interesting half
of an adoption question: a department that grew NO lentils in 2010 and 400 ha in 2019
only has the second half of that transition once `area_ha == 0` rows are dropped, and
the arrival becomes invisible. 113 department-crop pairs in this file go from a true
zero to a real area over the series. So this panel is built with
`sources.load_saa(require_yield=False)`.

THE DENOMINATOR, STATED ONCE
----------------------------
Shares are over the twelve crops `SAA_CROP_CODES` maps (the COP sheet: cereals,
oilseeds, protein crops), NOT over total arable area. Oats, triticale, rye, potatoes,
beet and forage are published but unmapped, so the denominator understates real
arable land by roughly a fifth. It is applied identically to every department and
year, so trends and cross-department comparisons are sound; the absolute share level
reads high. This is the same denominator `ml/sources.load_legume_pressure` uses, on
purpose, so the page and the yield model cannot disagree.

Run: .venv/bin/python scripts/build_adoption_panel.py
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml import sources  # noqa: E402

PROC = ROOT / "data" / "processed"
PANEL_OUT = PROC / "adoption_panel.csv"
GEOM_OUT = PROC / "dept_geometry.json"
META_OUT = PROC / "adoption_panel_meta.json"

WFS = "https://data.geopf.fr/wfs/ows"
DEPT_LAYER = "ADMINEXPRESS-COG.LATEST:departement"
UA = {"User-Agent": "hiprotein-hackathon/1.0"}

# Crop groupings the page reads by. Deliberately NOT one "legumes" bucket: the whole
# finding is that food pulses and feed pulses moved in opposite directions, and a
# single aggregate hides it.
PULSES = ("field_pea", "fava_bean", "green_lentil", "chickpea", "soybean")
FOOD_PULSES = ("green_lentil", "chickpea")       # overwhelmingly human-food outlets
FEED_PULSES = ("field_pea", "fava_bean")         # overwhelmingly compound-feed outlets
# Soy sits in neither: it is a crushed oilseed-protein crop whose meal goes to feed and
# whose area is driven by irrigation access, so it is reported on its own.

# Simplification tolerance in degrees for the choropleth polygons. 0.004 deg is about
# 300 m at French latitudes - invisible on a national map, and it takes the IGN
# department layer from 127 MB to well under one.
SIMPLIFY_DEG = 0.004

# Corsica and the overseas departments are in the IGN layer and in SAA, but grow
# effectively no mapped COP crops and would stretch the map's bounds for nothing.
EXCLUDE_DEPTS = frozenset({"2A", "2B", "971", "972", "973", "974", "975", "976"})


def fetch_dept_geometry() -> dict[str, dict]:
    """Simplified department polygons and centroids, keyed by INSEE code."""
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": DEPT_LAYER,
        "OUTPUTFORMAT": "application/json",
        "SRSNAME": "CRS:84",
        "COUNT": "110",
    }
    r = requests.get(WFS, params=params, headers=UA, timeout=300)
    r.raise_for_status()
    out: dict[str, dict] = {}
    for f in r.json().get("features") or []:
        props = f.get("properties") or {}
        code = str(props.get("code_insee") or "").strip()
        if not code or code in EXCLUDE_DEPTS:
            continue
        g = shape(f["geometry"])
        # Invalid rings survive simplify_preserve_topology badly; buffer(0) repairs
        # them. Area error is immaterial at 300 m tolerance.
        if not g.is_valid:
            g = g.buffer(0)
        small = g.simplify(SIMPLIFY_DEG, preserve_topology=True)
        if small.is_empty:
            small = g
        c = small.centroid if small.is_valid else small.representative_point()
        out[code] = {
            "name": props.get("nom_officiel"),
            "region_code": props.get("code_insee_de_la_region"),
            "centroid": [round(float(c.x), 4), round(float(c.y), 4)],
            "geometry": _round_coords(mapping(small), 4),
        }
    return out


def _round_coords(geom: dict, nd: int):
    """Round every coordinate in place. Four decimals is ~11 m, far finer than the
    300 m simplification, and it halves the file size versus full float repr."""
    def walk(o):
        if isinstance(o, (list, tuple)):
            if o and isinstance(o[0], (int, float)):
                return [round(float(v), nd) for v in o]
            return [walk(v) for v in o]
        return o

    return {"type": geom["type"], "coordinates": walk(geom["coordinates"])}


def build_panel() -> pd.DataFrame:
    saa = sources.load_saa("dep", require_yield=False)
    saa = saa[~saa["dept_code"].isin(EXCLUDE_DEPTS)].copy()

    # Dept-year denominator over the mapped COP crops.
    total = (
        saa.groupby(["dept_code", "year"])["area_ha"].sum().rename("cop_area_ha")
    )
    panel = saa.merge(total, on=["dept_code", "year"], how="left")
    panel["crop_share"] = (panel["area_ha"] / panel["cop_area_ha"]).fillna(0.0)

    group = {c: "food_pulse" for c in FOOD_PULSES}
    group.update({c: "feed_pulse" for c in FEED_PULSES})
    group["soybean"] = "soy"
    panel["crop_group"] = panel["crop"].map(group).fillna("other")
    panel["is_pulse"] = panel["crop"].isin(PULSES)

    cols = [
        "dept_code", "geo_name", "year", "crop", "crop_group", "is_pulse",
        "area_ha", "yield_t_ha", "prod_t", "cop_area_ha", "crop_share",
        "quality_status",
    ]
    out = panel[cols].rename(columns={"geo_name": "dept_name"})
    return out.sort_values(["dept_code", "crop", "year"]).reset_index(drop=True)


def main() -> int:
    print("building adoption panel from Agreste SAA (zeros preserved) ...")
    panel = build_panel()
    PROC.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_OUT, index=False)
    print(f"  {len(panel)} rows, {panel.dept_code.nunique()} departments, "
          f"{panel.year.min()}-{panel.year.max()} -> {PANEL_OUT.name}")

    # The IGN department layer is a 127 MB download that simplifies to under one, and
    # administrative boundaries do not move between runs. Re-fetch only on --force.
    if GEOM_OUT.exists() and "--force" not in sys.argv:
        geom = json.loads(GEOM_OUT.read_text(encoding="utf-8"))
        print(f"  reusing {GEOM_OUT.name} ({len(geom)} departments); --force to refetch")
    else:
        print("fetching IGN department geometry ...")
        geom = fetch_dept_geometry()
        GEOM_OUT.write_text(json.dumps(geom, separators=(",", ":")), encoding="utf-8")
    size_mb = GEOM_OUT.stat().st_size / 1e6
    print(f"  {len(geom)} departments, {size_mb:.2f} MB -> {GEOM_OUT.name}")

    missing = sorted(set(panel.dept_code) - set(geom))
    pulses = panel[panel.is_pulse]
    nat = pulses.groupby(["year", "crop"])["area_ha"].sum().unstack()

    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "scripts/build_adoption_panel.py",
        "area_source": (
            "Agreste Statistique agricole annuelle, series longues 2010-2025, "
            "departmental workbook, sheet COP"
        ),
        "geometry_source": f"IGN {DEPT_LAYER} via data.geopf.fr WFS 2.0.0",
        "years": [int(panel.year.min()), int(panel.year.max())],
        "n_departments": int(panel.dept_code.nunique()),
        "n_rows": int(len(panel)),
        "zero_area_rows_kept": int((panel.area_ha == 0).sum()),
        "denominator": (
            "Shares are over the twelve COP crops SAA_CROP_CODES maps, not total "
            "arable area. Understates arable by roughly a fifth, identically in every "
            "department and year, so trends compare but the share level reads high."
        ),
        "crop_groups": {
            "food_pulse": list(FOOD_PULSES),
            "feed_pulse": list(FEED_PULSES),
            "soy": ["soybean"],
        },
        "agreste_data_cutoff": (
            "Workbook header, verbatim: 'Donnees arretees au 30/03/2026. Donnees 2025 "
            "provisoires.' 2025 is therefore excluded and 2010-2024 are definitive. "
            "The header also records that the series were made consistent with the "
            "2020 recensement agricole and back-cast over 2010-2019."
        ),
        "quality_status_mix_pulse_area_pct": {
            str(k): round(float(v), 2)
            for k, v in (
                100
                * pulses.groupby(pulses.quality_status.replace("", "(blank)"))["area_ha"].sum()
                / pulses["area_ha"].sum()
            ).items()
        },
        "quality_status_caveat": (
            "Agreste publishes a per-series STATUT_QUALITE of 1, 2, 3 or NC. The "
            "workbook defines the codes only by reference to a methodology page that "
            "currently returns an error, so the codes are reported as a mix and NOT "
            "interpreted here. Every row carries a value for all 15 years regardless "
            "of status, so the flag changes no figure in this panel."
        ),
        "geometry_simplify_deg": SIMPLIFY_DEG,
        "departments_without_geometry": missing,
        "excluded_departments": sorted(EXCLUDE_DEPTS),
        "national_pulse_area_ha": {
            str(int(y)): {c: (None if pd.isna(v) else round(float(v)))
                          for c, v in row.items()}
            for y, row in nat.iterrows()
        },
        "caveat": (
            "Area is a DECLARED, department-aggregated figure, not a parcel record. "
            "It shows that land moved; it does not by itself say why."
        ),
    }
    META_OUT.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  meta -> {META_OUT.name}")
    if missing:
        print(f"  WARNING: no geometry for {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
