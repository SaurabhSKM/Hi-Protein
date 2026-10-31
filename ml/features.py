"""Phenological weather windows, built from Meteo-France monthly station data.

Annual rainfall totals correlate weakly with pulse yield because what matters is
WHEN the water arrives. These windows follow the crop's biology:

  establishment    Mar-Apr rain        emergence and early root growth
  flowering        May-Jun rain - ETP  pod set; the single strongest driver
  heat stress      Jun days Tmax>=30   flower abortion in pea and fava bean
  bruchid pressure May days Tmax>=20   beetle egg-laying on pods
  harvest risk     Jul rain            fungal staining, seed splitting, downgrade
  frost            Apr frost days      damage to early-sown spring pulses
  recharge         Oct(y-1)-Mar rain   refills plant-available soil water
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Monthly aggregations: (output column, source column, months, how)
WINDOWS: list[tuple[str, str, tuple[int, ...], str]] = [
    ("establishment_rain_mm", "RR", (3, 4), "sum"),
    ("flowering_rain_mm", "RR", (5, 6), "sum"),
    ("flowering_etp_mm", "ETP", (5, 6), "sum"),
    ("harvest_rain_mm", "RR", (7,), "sum"),
    ("late_harvest_rain_mm", "RR", (8,), "sum"),
    ("summer_rain_mm", "RR", (6, 7, 8), "sum"),
    ("jun_heat_days_30c", "NBJTX30", (6,), "sum"),
    ("may_jun_heat_days_25c", "NBJTX25", (5, 6), "sum"),
    ("jul_heat_days_30c", "NBJTX30", (7,), "sum"),
    ("apr_frost_days", "NBJGELEE", (4,), "sum"),
    ("mar_frost_days", "NBJGELEE", (3,), "sum"),
    ("may_cool_days_below_20c", "NBJTXI20", (5,), "sum"),
    ("spring_tmean_c", "TM", (4, 5, 6), "mean"),
    ("flowering_tmax_c", "TX", (5, 6), "mean"),
    ("apr_jun_tmin_c", "TN", (4, 5, 6), "mean"),
]

RECHARGE_MONTHS = (10, 11, 12, 1, 2, 3)

FEATURE_COLUMNS = [
    "establishment_rain_mm",
    "flowering_rain_mm",
    "flowering_etp_mm",
    "flowering_water_balance_mm",
    "harvest_rain_mm",
    "late_harvest_rain_mm",
    "summer_rain_mm",
    "jun_heat_days_30c",
    "may_jun_heat_days_25c",
    "jul_heat_days_30c",
    "apr_frost_days",
    "mar_frost_days",
    "may_days_above_20c",
    "spring_tmean_c",
    "flowering_tmax_c",
    "apr_jun_tmin_c",
    "recharge_rain_mm",
    "reserve_utile_mm",
    "soil_ph",
    "drought_stress_index",
    "heat_x_shallow_soil",
    "latitude",
    # Department rotation history, from the Agreste SAA area series itself (see
    # ml/sources.py:load_legume_pressure). The closest honest proxy for "crop
    # history" the TRAINING data can support, at the department-year grain the
    # Agreste yield labels actually live at. Both are lagged by construction, so
    # neither is contemporary with the yield they help predict.
    "legume_share_lag1",
    "legume_share_lag2to4_mean",
]


def _agg_station_year(mon: pd.DataFrame) -> pd.DataFrame:
    """Aggregate monthly station rows into one row per (station, year)."""
    out: list[pd.DataFrame] = []
    for col, src, months, how in WINDOWS:
        if src not in mon.columns:
            continue
        sub = mon[mon["month"].isin(months)]
        g = sub.groupby(["NUM_POSTE", "year"])[src]
        ser = g.sum(min_count=1) if how == "sum" else g.mean()
        out.append(ser.rename(col))

    # Winter recharge spans a year boundary, so shift Oct-Dec forward to the
    # agricultural year that actually benefits from it.
    rech = mon[mon["month"].isin(RECHARGE_MONTHS)].copy()
    rech["ag_year"] = np.where(rech["month"] >= 10, rech["year"] + 1, rech["year"])
    rr = (
        rech.groupby(["NUM_POSTE", "ag_year"])["RR"]
        .sum(min_count=1)
        .rename("recharge_rain_mm")
        .reset_index()
        .rename(columns={"ag_year": "year"})
        .set_index(["NUM_POSTE", "year"])["recharge_rain_mm"]
    )
    out.append(rr)

    df = pd.concat(out, axis=1).reset_index()
    lat = mon.groupby("NUM_POSTE")["LAT"].first().rename("latitude")
    return df.merge(lat, on="NUM_POSTE", how="left")


def department_year_features(mon: pd.DataFrame, min_stations: int = 3) -> pd.DataFrame:
    """Collapse station-year rows to a robust department-year median.

    The median, not the mean, because a single station with a thunderstorm cell or a
    long data gap would otherwise move a whole department's rainfall feature.
    """
    sy = _agg_station_year(mon)
    agg_cols = [c for c, *_ in WINDOWS if c in sy.columns] + ["recharge_rain_mm", "latitude"]
    dept = (
        sy.groupby("year")[agg_cols]
        .median()
        .join(sy.groupby("year")["NUM_POSTE"].nunique().rename("n_stations"))
        .reset_index()
    )
    dept = dept[dept["n_stations"] >= min_stations]
    dept["dept_code"] = mon["dept_code"].iloc[0]

    # "Days with Tmax >= 20 C in May" drives bruchid egg-laying. Meteo-France
    # publishes the complement (NBJTXI20 = days BELOW 20 C), so invert it.
    if "may_cool_days_below_20c" in dept.columns:
        dept["may_days_above_20c"] = (31.0 - dept["may_cool_days_below_20c"]).clip(lower=0)
    else:
        dept["may_days_above_20c"] = np.nan
    return dept


def add_soil_and_interactions(
    df: pd.DataFrame, soil_by_dept: dict[str, dict]
) -> pd.DataFrame:
    """Attach soil properties and the physically motivated interaction terms."""
    df = df.copy()
    df["reserve_utile_mm"] = df["dept_code"].map(
        lambda d: soil_by_dept.get(d, {}).get("reserve_utile_mm", 130.0)
    )
    df["soil_ph"] = df["dept_code"].map(
        lambda d: soil_by_dept.get(d, {}).get("ph", 7.0)
    )

    df["flowering_water_balance_mm"] = df["flowering_rain_mm"] - df["flowering_etp_mm"]

    # Normalising the flowering deficit by plant-available water capacity is what makes
    # the feature transferable: -80 mm on a 160 mm deep loam is an inconvenience, the
    # same -80 mm on a 75 mm shallow limestone is a crop failure.
    df["drought_stress_index"] = (
        -df["flowering_water_balance_mm"] / df["reserve_utile_mm"].clip(lower=40.0)
    )

    # Heat damage is worse where the soil cannot buffer it.
    df["heat_x_shallow_soil"] = df["jun_heat_days_30c"] * (
        140.0 / df["reserve_utile_mm"].clip(lower=40.0)
    )

    df["year_index"] = df["year"] - 2010
    return df


def build_weather_panel(depts: list[str], soil_by_dept: dict[str, dict]) -> pd.DataFrame:
    """Full department-year weather + soil feature panel for the given departments."""
    import sources  # local module

    frames = []
    for d in depts:
        try:
            mon = sources.load_meteo_monthly(d)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip dept {d}: {exc}")
            continue
        f = department_year_features(mon)
        if not f.empty:
            frames.append(f)
    if not frames:
        raise RuntimeError("No weather data could be loaded for any department.")
    panel = pd.concat(frames, ignore_index=True)
    return add_soil_and_interactions(panel, soil_by_dept)
