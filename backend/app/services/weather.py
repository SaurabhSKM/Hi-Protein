"""Weather sampling for the Monte Carlo engine.

Real observed department-years are bootstrapped rather than drawing each weather
variable from its own Gaussian. A dry flowering and a hot June co-occur in nature;
independent draws would break that dependence and quietly understate how often a
genuinely bad pulse year happens.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR

PANEL_PATH = Path(DATA_DIR) / "processed" / "weather_panel.csv"

# Draw from the last 30 complete seasons: long enough for stable extremes, recent
# enough that the sampled climate is the one a farmer is planting into.
WINDOW_YEARS = 30
# Exponential recency weighting. A 12-year half-life roughly doubles the weight of
# the most recent decade relative to the oldest in the window.
RECENCY_HALF_LIFE = 12.0

_LOCK = threading.Lock()
_PANEL: pd.DataFrame | None = None

REQUIRED = [
    "flowering_water_balance_mm", "harvest_rain_mm", "jun_heat_days_30c",
    "may_days_above_20c", "drought_stress_index", "recharge_rain_mm",
]


def panel() -> pd.DataFrame:
    global _PANEL
    if _PANEL is None:
        with _LOCK:
            if _PANEL is None:
                if not PANEL_PATH.exists():
                    raise FileNotFoundError(
                        f"Weather panel missing at {PANEL_PATH}. Run `python ml/build_dataset.py`."
                    )
                df = pd.read_csv(PANEL_PATH, dtype={"dept_code": str})
                _PANEL = df.dropna(subset=REQUIRED)
    return _PANEL


def available_departments() -> list[str]:
    return sorted(panel()["dept_code"].unique())


def department_window(dept_code: str) -> pd.DataFrame:
    p = panel()
    sub = p[p["dept_code"] == dept_code]
    if sub.empty:
        # Fall back to the national pool so an unseen department still gets a
        # plausible climate rather than an error.
        sub = p
    last = int(sub["year"].max())
    return sub[sub["year"] > last - WINDOW_YEARS].reset_index(drop=True)


def _weights(years: np.ndarray) -> np.ndarray:
    age = years.max() - years
    w = 0.5 ** (age / RECENCY_HALF_LIFE)
    return w / w.sum()


def sample_seasons(
    dept_code: str, n: int, rng: np.random.Generator, *, jitter: float = 0.12
) -> pd.DataFrame:
    """Draw n seasons for this department.

    Resampling 30 observed years alone gives only 30 distinct outcomes, which makes
    the tails of a 2000-path simulation lumpy. A small multiplicative jitter on each
    continuous feature smooths the support while preserving the joint structure of the
    season that was drawn.
    """
    win = department_window(dept_code)
    if win.empty:
        raise RuntimeError(f"No weather available for department {dept_code}")
    idx = rng.choice(len(win), size=n, replace=True, p=_weights(win["year"].to_numpy()))
    out = win.iloc[idx].reset_index(drop=True).copy()
    out["sampled_year"] = out["year"]

    num = out.select_dtypes(include=[np.number]).columns
    skip = {"year", "sampled_year", "n_stations", "latitude", "soil_ph", "reserve_utile_mm"}
    for c in num:
        if c in skip:
            continue
        sd = float(win[c].std(ddof=0)) if c in win.columns else 0.0
        if sd > 0:
            out[c] = out[c].to_numpy() + rng.normal(0.0, jitter * sd, size=n)

    # Re-derive quantities that must stay internally consistent after jitter.
    if {"flowering_rain_mm", "flowering_etp_mm"} <= set(out.columns):
        out["flowering_water_balance_mm"] = out["flowering_rain_mm"] - out["flowering_etp_mm"]
    for c in ("harvest_rain_mm", "flowering_rain_mm", "establishment_rain_mm",
              "recharge_rain_mm", "late_harvest_rain_mm", "summer_rain_mm"):
        if c in out.columns:
            out[c] = out[c].clip(lower=0.0)
    for c in ("jun_heat_days_30c", "jul_heat_days_30c", "may_jun_heat_days_25c",
              "apr_frost_days", "mar_frost_days"):
        if c in out.columns:
            out[c] = out[c].clip(lower=0.0)
    if "may_days_above_20c" in out.columns:
        out["may_days_above_20c"] = out["may_days_above_20c"].clip(0.0, 31.0)
    # Area shares cannot be negative, and a department running the whole farm in
    # legumes is not physical either; a generous upper bound just guards against the
    # jitter pushing an already-small share past zero for a low-pulse department.
    for c in ("legume_share_lag1", "legume_share_lag2to4_mean"):
        if c in out.columns:
            out[c] = out[c].clip(0.0, 1.0)
    return out


def climate_summary(dept_code: str) -> dict:
    win = department_window(dept_code)
    cols = [
        "flowering_water_balance_mm", "harvest_rain_mm",
        "jun_heat_days_30c", "may_days_above_20c", "recharge_rain_mm",
    ]
    return {
        "years": [int(win["year"].min()), int(win["year"].max())],
        "n_years": int(len(win)),
        "medians": {c: round(float(win[c].median()), 1) for c in cols if c in win},
    }
