"""Forward climate horizons: the 'tomorrow' half of the brief.

The engine's weather bootstrap answers "what does a season look like, drawn from the
last thirty". That is the right question for next spring and the wrong one for a
machinery purchase, a sorting line, or a 2030 area target.

Rather than hand-writing climate deltas, this module MEASURES how each phenological
variable has responded to temperature in the project's own Meteo-France panel, then
shifts observed seasons by the warming increment of a chosen horizon. Two consequences
worth knowing:

* The projection updates itself when the panel is refreshed. There is no table of
  assumed deltas to go stale.
* The measured response is honest about where it is weak. Harvest rain barely
  correlates with temperature in the observed record, so it is left alone instead of
  being given an invented trend - which turns out to be the substantive finding: what
  warming threatens about pulse grading is insect pressure, not wetter harvests.

The sensitivities are fitted on INTERANNUAL variation, within department, which is a
space-for-time substitution. Sound for thermal variables where the mechanism is direct;
weak for rainfall, where circulation change matters. The fitted correlation travels with
every coefficient so a reader can discount it.
"""
from __future__ import annotations

import threading
from functools import cache

import numpy as np
import pandas as pd

from ..config import load_ref

_LOCK = threading.Lock()
_FIT: dict | None = None

# The temperature variable everything is regressed against. Spring mean covers the
# establishment-to-flowering window that drives pulse outcomes, and it is the column
# with the fewest gaps in the panel.
_T_COL = "spring_tmean_c"

# Variables that cannot go negative, and the day-count ceilings.
_NON_NEGATIVE = (
    "flowering_rain_mm", "establishment_rain_mm", "harvest_rain_mm",
    "late_harvest_rain_mm", "summer_rain_mm", "recharge_rain_mm", "flowering_etp_mm",
    "jun_heat_days_30c", "jul_heat_days_30c", "may_jun_heat_days_25c",
    "apr_frost_days", "mar_frost_days", "may_days_above_20c", "may_cool_days_below_20c",
)
_DAY_CAPS = {
    "may_days_above_20c": 31.0, "may_cool_days_below_20c": 31.0,
    "jun_heat_days_30c": 30.0, "jul_heat_days_30c": 31.0,
    "may_jun_heat_days_25c": 61.0, "apr_frost_days": 30.0, "mar_frost_days": 31.0,
}


def spec() -> dict:
    return load_ref("climate_projection")


def horizons() -> dict:
    return spec()["horizons"]


def horizon_keys() -> list[str]:
    return list(horizons())


def _panel() -> pd.DataFrame:
    # Imported here rather than at module scope: weather imports nothing from climate,
    # and keeping the dependency one-way avoids a cycle when weather calls back in.
    from . import weather

    return weather.panel()


def fit() -> dict:
    """Measure each variable's sensitivity to local warming, and the window offset.

    Fitted once and memoised. Two products:

    `sensitivity[var]` - change in `var` per +1 C of spring mean temperature, estimated
    within department (both sides de-meaned by department) so the slope describes a
    response to warming rather than the fact that Gers is hotter than the Marne.

    `window_catchup_c` - how far the recency-weighted bootstrap window sits BELOW the
    last ten observed years. This is not a modelling choice; it is a measurement, and
    it says the raw bootstrap describes a climate that has already gone.
    """
    global _FIT
    if _FIT is not None:
        return _FIT
    with _LOCK:
        if _FIT is not None:
            return _FIT

        from . import weather

        df = _panel().dropna(subset=[_T_COL]).copy()
        cfg = spec()
        wanted = [c for c in cfg["projected_variables"]["include"] if c in df.columns]
        r_min = float(cfg["min_abs_correlation_to_project"])

        # De-mean within department: the question is "what does a warm year do here",
        # not "what do warm departments look like".
        df["_t"] = df[_T_COL] - df.groupby("dept_code")[_T_COL].transform("mean")
        x = df["_t"].to_numpy(dtype=float)

        sens: dict[str, dict] = {}
        for c in wanted:
            y = (df[c] - df.groupby("dept_code")[c].transform("mean")).to_numpy(dtype=float)
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() < 100 or np.std(x[m]) < 1e-9 or np.std(y[m]) < 1e-12:
                continue
            slope = float(np.polyfit(x[m], y[m], 1)[0])
            r = float(np.corrcoef(x[m], y[m])[0, 1])
            applied = abs(r) >= r_min
            sens[c] = {
                "per_degree_c": round(slope if applied else 0.0, 4),
                "fitted_per_degree_c": round(slope, 4),
                "r": round(r, 3),
                "n": int(m.sum()),
                "applied": applied,
                "observed_mean": round(float(df[c].mean()), 2),
            }

        # Offset between the sampling distribution the engine actually draws from and
        # the most recent decade, computed under the SAME recency weights weather.py
        # uses, so the number corrects the real bias rather than a hypothetical one.
        last = int(df["year"].max())
        win = df[df["year"] > last - weather.WINDOW_YEARS]
        w = 0.5 ** ((int(win["year"].max()) - win["year"].to_numpy()) / weather.RECENCY_HALF_LIFE)
        win_mean = float(np.average(win["_t"].to_numpy(dtype=float), weights=w))
        recent = df[df["year"] > last - 10]
        catchup = float(recent["_t"].mean() - win_mean)

        _FIT = {
            "temperature_column": _T_COL,
            "sensitivity": sens,
            "window_catchup_c": round(catchup, 3),
            "n_rows": int(len(df)),
            "panel_years": [int(df["year"].min()), last],
            "n_departments": int(df["dept_code"].nunique()),
            "min_abs_correlation_to_project": r_min,
        }
    return _FIT


def delta_c(horizon: str) -> float:
    """Total temperature shift to apply to a sampled season, in degrees C.

    Two parts: the measured gap between the bootstrap window and the present decade,
    and the horizon's additional warming above the present. Splitting them matters -
    the first is a correction to a known bias, the second is a projection, and a reader
    is entitled to see which is which.
    """
    h = horizons().get(horizon)
    if h is None:
        raise KeyError(f"Unknown climate horizon '{horizon}'. Known: {horizon_keys()}")
    shift = float(h["additional_warming_vs_present_c"])
    if h.get("correct_window_to_present"):
        shift += float(fit()["window_catchup_c"])
    return shift


@cache
def horizon_detail(horizon: str) -> dict:
    """Everything the API needs to describe one horizon, including its own caveats."""
    h = dict(horizons()[horizon])
    f = fit()
    d = delta_c(horizon)
    return {
        "horizon": horizon,
        "label_fr": h.get("label_fr"),
        "label_en": h.get("label_en"),
        "warming_level_c": h.get("warming_level_c"),
        "additional_warming_vs_present_c": h.get("additional_warming_vs_present_c"),
        "window_catchup_applied_c": (
            f["window_catchup_c"] if h.get("correct_window_to_present") else 0.0
        ),
        "total_shift_applied_c": round(d, 3),
        "notes": h.get("notes"),
    }


def apply_shift(seasons: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """Return a copy of `seasons` moved to the climate of `horizon`.

    Delta-change: every row stays a real observed season, with its internal
    correlations intact, and only its level moves. A warm-and-dry year is still
    warm-and-dry afterwards; there are just more of the hot days in it.
    """
    d = delta_c(horizon)
    if abs(d) < 1e-9:
        return seasons

    sens = fit()["sensitivity"]
    out = seasons.copy()

    for col, s in sens.items():
        if col not in out.columns or not s["applied"]:
            continue
        out[col] = out[col].to_numpy(dtype=float) + s["per_degree_c"] * d

    for col in _NON_NEGATIVE:
        if col in out.columns:
            out[col] = out[col].clip(lower=0.0)
    for col, cap in _DAY_CAPS.items():
        if col in out.columns:
            out[col] = out[col].clip(0.0, cap)

    # Re-derive the composites from their shifted components instead of shifting them
    # too. Shifting a water balance AND its rain and ETP terms would apply the warming
    # twice, and the result would no longer be an internally consistent season.
    if {"flowering_rain_mm", "flowering_etp_mm"} <= set(out.columns):
        out["flowering_water_balance_mm"] = (
            out["flowering_rain_mm"] - out["flowering_etp_mm"]
        )
    # Both composites below reproduce ml/features.py exactly, including its clip
    # bounds and constants. If they drift apart, the projected season stops being the
    # same kind of object the model was trained on, which is worse than not projecting.
    if {"drought_stress_index", "reserve_utile_mm", "flowering_water_balance_mm"} <= set(out.columns):
        ru = out["reserve_utile_mm"].clip(lower=40.0).to_numpy(dtype=float)
        out["drought_stress_index"] = (
            -out["flowering_water_balance_mm"].to_numpy(dtype=float) / ru
        )
    if {"heat_x_shallow_soil", "jun_heat_days_30c", "reserve_utile_mm"} <= set(out.columns):
        ru = out["reserve_utile_mm"].clip(lower=40.0).to_numpy(dtype=float)
        out["heat_x_shallow_soil"] = (
            out["jun_heat_days_30c"].to_numpy(dtype=float) * (140.0 / ru)
        )

    out["climate_horizon"] = horizon
    out["climate_shift_c"] = d
    return out


def report() -> dict:
    """The fitted sensitivities, for /api/v1/climate-outlook and the Method tab."""
    f = fit()
    cfg = spec()
    rows = []
    for col, s in sorted(f["sensitivity"].items(), key=lambda kv: -abs(kv[1]["r"])):
        rows.append({"variable": col, **s})
    return {
        "method": cfg["_meta"]["method"],
        "warming_source": cfg["_meta"]["warming_source"],
        "caveat": cfg["_meta"]["caveat"],
        "temperature_column": f["temperature_column"],
        "panel_years": f["panel_years"],
        "n_rows": f["n_rows"],
        "n_departments": f["n_departments"],
        "window_catchup_c": f["window_catchup_c"],
        "window_catchup_note": (
            "Measured gap between the recency-weighted bootstrap window and the last "
            "ten observed years. Applied by every horizon except 'observed'."
        ),
        "min_abs_correlation_to_project": f["min_abs_correlation_to_project"],
        "unprojected_note": cfg["min_abs_correlation_note"],
        "sensitivities": rows,
        "horizons": [horizon_detail(k) for k in horizon_keys()],
    }
