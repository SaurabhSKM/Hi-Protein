"""Reads the baked adoption artifacts and rolls them up for the land-change view.

Every number this module returns is computed here from an artifact on disk. Nothing is
written down as a literal, because a literal in a service is a number that was true
when someone typed it. The artifacts are:

  data/processed/adoption_panel.csv        Agreste SAA area by department, crop, year
  data/processed/adoption_panel_meta.json  its provenance and caveats
  data/processed/dept_geometry.json        IGN department polygons, simplified
  ml/artifacts/adoption_report.json        the attribution result
  data/processed/rpg_change_beauce.json    RPG parcels, ten campaigns, one region

Built by scripts/build_adoption_panel.py, ml/train_adoption.py and
scripts/build_rpg_change.py respectively. Each is independently rebuildable and each
carries its own `_meta`, so a reader can trace any figure on the page back to a source.
"""
from __future__ import annotations

import json
from functools import cache
from typing import Any

import pandas as pd

from ..config import DATA_DIR, ML_ARTIFACT_DIR

PROC = DATA_DIR / "processed"
PANEL_PATH = PROC / "adoption_panel.csv"
PANEL_META_PATH = PROC / "adoption_panel_meta.json"
GEOM_PATH = PROC / "dept_geometry.json"
RPG_CHANGE_PATH = PROC / "rpg_change_beauce.json"
ATTRIBUTION_PATH = ML_ARTIFACT_DIR / "adoption_report.json"

# The crops the view ranks and charts. Kept in the order the page reads them: the two
# human-food pulses first, because they are the question, then the two feed pulses
# that moved the other way, then soy.
VIEW_CROPS = ("green_lentil", "chickpea", "field_pea", "fava_bean", "soybean")

_MISSING = (
    "Missing {path}. Run scripts/build_adoption_panel.py (and ml/train_adoption.py, "
    "scripts/build_rpg_change.py) to bake the adoption artifacts."
)


@cache
def panel() -> pd.DataFrame:
    if not PANEL_PATH.exists():
        raise FileNotFoundError(_MISSING.format(path=PANEL_PATH))
    return pd.read_csv(PANEL_PATH, dtype={"dept_code": str, "quality_status": str})


@cache
def panel_meta() -> dict[str, Any]:
    if not PANEL_META_PATH.exists():
        raise FileNotFoundError(_MISSING.format(path=PANEL_META_PATH))
    return json.loads(PANEL_META_PATH.read_text(encoding="utf-8"))


@cache
def geometry() -> dict[str, Any]:
    if not GEOM_PATH.exists():
        raise FileNotFoundError(_MISSING.format(path=GEOM_PATH))
    return json.loads(GEOM_PATH.read_text(encoding="utf-8"))


@cache
def attribution() -> dict[str, Any]:
    if not ATTRIBUTION_PATH.exists():
        raise FileNotFoundError(_MISSING.format(path=ATTRIBUTION_PATH))
    return json.loads(ATTRIBUTION_PATH.read_text(encoding="utf-8"))


@cache
def rpg_change() -> dict[str, Any]:
    if not RPG_CHANGE_PATH.exists():
        raise FileNotFoundError(_MISSING.format(path=RPG_CHANGE_PATH))
    return json.loads(RPG_CHANGE_PATH.read_text(encoding="utf-8"))


def _f(v) -> float | None:
    """NaN and numpy scalars are not JSON, and a silent NaN becomes a blank chart."""
    if v is None or pd.isna(v):
        return None
    return float(v)


# --------------------------------------------------------------------------- #
# National rollup
# --------------------------------------------------------------------------- #
@cache
def national() -> dict[str, Any]:
    """National area and share per crop per year, plus the headline change."""
    df = panel()
    years = sorted(int(y) for y in df["year"].unique())

    by_crop_year = (
        df.groupby(["crop", "year"])
        .agg(area_ha=("area_ha", "sum"), prod_t=("prod_t", "sum"))
        .reset_index()
    )
    # One denominator for every share on the page: the mapped COP area nationally.
    cop = df.groupby("year")["area_ha"].sum()

    series = {}
    for crop in VIEW_CROPS:
        d = by_crop_year[by_crop_year["crop"] == crop].set_index("year")
        rows = []
        for y in years:
            area = _f(d["area_ha"].get(y))
            rows.append({
                "year": y,
                "area_ha": None if area is None else round(area, 1),
                "share_pct": None if area is None or not cop.get(y)
                else round(100 * area / float(cop[y]), 4),
                # Area-weighted national yield, which is the only honest way to
                # aggregate a per-hectare figure across departments of different size.
                "yield_t_ha": _national_yield(df, crop, y),
            })
        series[crop] = rows

    # Peak year matters here: four of the five crops peaked before 2024, so a
    # first-to-last comparison alone would report a plateau as a decline.
    headline = {}
    for crop in VIEW_CROPS:
        rows = [r for r in series[crop] if r["area_ha"] is not None]
        if not rows:
            continue
        first, last = rows[0], rows[-1]
        peak = max(rows, key=lambda r: r["area_ha"])
        headline[crop] = {
            "first_year": first["year"], "first_area_ha": first["area_ha"],
            "last_year": last["year"], "last_area_ha": last["area_ha"],
            "peak_year": peak["year"], "peak_area_ha": peak["area_ha"],
            "change_first_to_last_ha": round(last["area_ha"] - first["area_ha"], 1),
            "multiple_first_to_last": round(last["area_ha"] / first["area_ha"], 2)
            if first["area_ha"] else None,
            "multiple_first_to_peak": round(peak["area_ha"] / first["area_ha"], 2)
            if first["area_ha"] else None,
            "pct_off_peak": round(100 * (1 - last["area_ha"] / peak["area_ha"]), 1)
            if peak["area_ha"] else None,
        }

    groups = {}
    for name in sorted(df["crop_group"].dropna().unique()):
        if name == "other":
            continue
        g = df[df["crop_group"] == name].groupby("year")["area_ha"].sum()
        groups[name] = [
            {"year": y, "area_ha": round(float(g.get(y, 0.0)), 1),
             "share_pct": round(100 * float(g.get(y, 0.0)) / float(cop[y]), 4)
             if cop.get(y) else None}
            for y in years
        ]

    return {
        "years": years,
        "cop_area_ha": {str(y): round(float(cop[y]), 1) for y in years},
        "series": series,
        "headline": headline,
        "crop_groups": groups,
        "n_departments": int(df["dept_code"].nunique()),
        "provenance": panel_meta(),
    }


def _national_yield(df: pd.DataFrame, crop: str, year: int) -> float | None:
    d = df[(df["crop"] == crop) & (df["year"] == year)]
    d = d[d["area_ha"].fillna(0) > 0].dropna(subset=["yield_t_ha"])
    if d.empty:
        return None
    w = d["area_ha"].to_numpy()
    return round(float((d["yield_t_ha"].to_numpy() * w).sum() / w.sum()), 3)


# --------------------------------------------------------------------------- #
# Department rollup
# --------------------------------------------------------------------------- #
@cache
def departments(crop: str) -> dict[str, Any]:
    """Per-department trajectory for one crop, for the choropleth and the table."""
    df = panel()
    if crop not in set(df["crop"]):
        raise KeyError(f"Unknown crop '{crop}'. Known: {sorted(set(df['crop']))}")

    d = df[df["crop"] == crop]
    geo = geometry()
    years = sorted(int(y) for y in df["year"].unique())
    first, last = years[0], years[-1]

    rows = []
    for code, g in d.groupby("dept_code"):
        g = g.set_index("year").sort_index()
        area = {int(y): _f(v) for y, v in g["area_ha"].items()}
        a0, a1 = area.get(first), area.get(last)
        nonzero = [y for y, v in sorted(area.items()) if v and v > 0]
        peak_year = max(area, key=lambda y: (area[y] or -1)) if area else None
        info = geo.get(code) or {}
        rows.append({
            "dept_code": code,
            "dept_name": info.get("name") or str(g["dept_name"].iloc[0]),
            "centroid": info.get("centroid"),
            "area_ha_by_year": {str(y): area.get(y) for y in years},
            "share_pct_by_year": {
                str(y): (round(100 * float(v), 4) if (v := g["crop_share"].get(y)) is not None
                         and not pd.isna(v) else None)
                for y in years
            },
            f"area_ha_{first}": a0,
            f"area_ha_{last}": a1,
            "change_ha": None if a0 is None or a1 is None else round(a1 - a0, 1),
            "peak_year": peak_year,
            "peak_area_ha": area.get(peak_year) if peak_year else None,
            # The arrival year is only meaningful because the panel keeps area==0
            # rows; with them filtered out the series would simply start late.
            "first_year_with_area": nonzero[0] if nonzero else None,
            "arrived_during_series": bool(
                nonzero and a0 == 0.0 and (a1 or 0) > 0
            ),
            "quality_status": sorted(set(g["quality_status"].dropna().astype(str))),
        })

    rows.sort(key=lambda r: -(r["change_ha"] if r["change_ha"] is not None else -1e9))
    arrivals = [r["dept_code"] for r in rows if r["arrived_during_series"]]
    return {
        "crop": crop,
        "years": years,
        "compare_years": [first, last],
        "departments": rows,
        "n_departments": len(rows),
        "n_arrived_during_series": len(arrivals),
        "arrived_department_codes": arrivals,
    }


@cache
def arrivals_summary() -> dict[str, Any]:
    """Department-crop pairs that went from a true zero to a real area.

    This is the figure the yield-model training panel cannot produce: it drops
    `area_ha == 0` rows, so a department's first lentil hectare looks like the start
    of the series rather than an arrival.
    """
    out = {}
    total = 0
    for crop in VIEW_CROPS:
        d = departments(crop)
        out[crop] = {
            "n_arrived": d["n_arrived_during_series"],
            "department_codes": d["arrived_department_codes"],
        }
        total += d["n_arrived_during_series"]
    return {
        "by_crop": out,
        "total_department_crop_arrivals": total,
        "compare_years": departments(VIEW_CROPS[0])["compare_years"],
        "note": (
            "Counted as area == 0 in the first year of the series and > 0 in the "
            "last. Requires the zero rows the training panel filters out."
        ),
    }
