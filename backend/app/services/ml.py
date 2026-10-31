"""Yield model inference: conformalised quantiles, then parcel-level widening."""
from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ..config import ML_ARTIFACT_DIR, crop, soils

_LOCK = threading.Lock()
_BUNDLE: dict | None = None
ARTIFACT = Path(ML_ARTIFACT_DIR) / "yield_model.joblib"

# Fallback reference yields if no artifact is present, so the API still answers.
_FALLBACK_SOIL_FACTOR = {
    "deep_loam": 1.12, "clay_loam": 1.0, "deep_clay": 0.93,
    "shallow_limestone": 0.82, "sandy": 0.80, "boulbene": 0.88,
}


def bundle() -> dict | None:
    global _BUNDLE
    if _BUNDLE is None:
        with _LOCK:
            if _BUNDLE is None and ARTIFACT.exists():
                _BUNDLE = joblib.load(ARTIFACT)
    return _BUNDLE


def is_trained() -> bool:
    return bundle() is not None


def model_version() -> str:
    b = bundle()
    return b["model_version"] if b else "reference-table-fallback-0"


# Crops with no series of their own in the Agreste COP sheet, expressed as a
# documented multiple of a crop that does have one. Without this, winter pea fell
# through to a hand-written reference yield and ranked FIRST among candidates in
# Cote-d'Or and Gers on a number that came from nobody's data.
#
# Agreste publishes a single "Pois proteagineux" series (LIB_SAA code 41) covering
# both spring and winter habit, so winter pea cannot be separated from it. Autumn-sown
# peas root deeper and largely escape the June drought that caps spring peas, which is
# worth roughly a tenth of yield in French trial references; they also carry
# winter-kill risk that the uplift deliberately does not try to price, because the
# weather model already penalises hard frost.
BASELINE_PROXY: dict[str, tuple[str, float, str]] = {
    "winter_pea": (
        "field_pea", 1.10,
        "Agreste reports one 'pois proteagineux' series covering both spring and "
        "winter habit, so this is the spring-pea baseline with a documented +10% "
        "winter-habit uplift, not an independently measured winter-pea yield.",
    ),
}

# Crops that are not in the Agreste COP sheet at all. Lucerne is published in the
# forage (FOU) sheet, which this pipeline does not ingest.
NO_AGRESTE_SERIES = {"alfalfa"}

# Bounds on the soil adjustment below. The crop-by-soil means are confounded by
# where each crop is grown (lentil's deep-clay mean comes from a handful of
# departments), so an unclipped ratio can invert the agronomy.
_SOIL_ADJ_MIN, _SOIL_ADJ_MAX = 0.70, 1.25


@lru_cache(maxsize=16)
def _soil_means(crop_key: str) -> dict[str, float]:
    b = bundle()
    if b is None:
        return {}
    return {
        r["soil_type"]: float(r["yield_t_ha"])
        for r in b["soil_crop_baseline"]
        if r["crop"] == crop_key and r.get("yield_t_ha")
    }


@lru_cache(maxsize=1)
def _dominant_soils() -> dict[str, str]:
    from ..config import load_ref

    return {
        k: v for k, v in load_ref("dept_soils").items()
        if not k.startswith("_") and isinstance(v, str)
    }


def _soil_adjustment(crop_key: str, dept_code: str, soil_type: str) -> float:
    """Scale a department baseline from its dominant soil to this parcel's soil.

    A department mean yield already embeds that department's dominant soil. Taking
    it unchanged for a parcel on a different soil means the soil selector moves the
    weather features but not the yield LEVEL, which let shallow limestone in Beauce
    score fractionally above deep loam - the opposite of the agronomy.
    """
    dominant = _dominant_soils().get(dept_code)
    if not dominant or dominant == soil_type:
        return 1.0
    means = _soil_means(crop_key)
    a, b_ = means.get(soil_type), means.get(dominant)
    if not a or not b_:
        # Fall back to the reference soil factors when a cell is unpopulated.
        a = _FALLBACK_SOIL_FACTOR.get(soil_type)
        b_ = _FALLBACK_SOIL_FACTOR.get(dominant)
        if not a or not b_:
            return 1.0
    return float(np.clip(a / b_, _SOIL_ADJ_MIN, _SOIL_ADJ_MAX))


@lru_cache(maxsize=512)
def baseline_yield(crop_key: str, dept_code: str, soil_type: str) -> tuple[float, str]:
    """Long-run expected yield for this crop here, and how it was obtained."""
    b = bundle()
    if b is None:
        ref = float(crop(crop_key)["yield_t_ha_ref"])
        return ref * _FALLBACK_SOIL_FACTOR.get(soil_type, 1.0), "crop_reference_table"

    # A crop with no series of its own borrows one, with a documented factor, rather
    # than silently falling through to a hand-written reference yield.
    proxy = BASELINE_PROXY.get(crop_key)
    lookup, factor = (proxy[0], proxy[1]) if proxy else (crop_key, 1.0)
    suffix = "_via_proxy" if proxy else ""

    for rec in b["dept_crop_baseline"]:
        if rec["crop"] == lookup and str(rec["dept_code"]).zfill(2) == dept_code:
            adj = _soil_adjustment(lookup, dept_code, soil_type)
            src = (
                "agreste_department_history"
                if adj == 1.0
                else "agreste_department_history_soil_adjusted"
            )
            return float(rec["yield_t_ha"]) * adj * factor, src + suffix
    for rec in b["soil_crop_baseline"]:
        if rec["crop"] == lookup and rec["soil_type"] == soil_type:
            return float(rec["yield_t_ha"]) * factor, "agreste_same_soil_archetype" + suffix
    nat = b["national_crop_baseline"].get(lookup)
    if nat:
        return float(nat) * factor, "agreste_national_mean" + suffix
    ref = float(crop(crop_key)["yield_t_ha_ref"])
    return ref * _FALLBACK_SOIL_FACTOR.get(soil_type, 1.0), "crop_reference_table"


def baseline_caveat(crop_key: str, source: str) -> str | None:
    """Plain-language warning when a yield baseline is not this crop's own data."""
    if source == "crop_reference_table":
        if crop_key in NO_AGRESTE_SERIES:
            return (
                f"{crop(crop_key)['label_fr']} has no series in the Agreste COP sheet "
                "(lucerne is published in the forage sheet, which this pipeline does "
                "not ingest), so its yield comes from a hand-written reference value "
                "and is far weaker evidence than the other candidates."
            )
        return (
            f"No Agreste history was found for {crop(crop_key)['label_fr']} here, so "
            "its yield comes from a hand-written reference value rather than measured "
            "data. Treat the comparison against data-backed crops with caution."
        )
    if source.endswith("_via_proxy"):
        proxy = BASELINE_PROXY.get(crop_key)
        if proxy:
            return proxy[2]
    return None


def _design(weather: pd.DataFrame, crop_key: str, soil_type: str, b: dict) -> pd.DataFrame:
    X = pd.DataFrame(index=weather.index)
    for name in b["feature_names"]:
        if name.startswith("crop_"):
            X[name] = 1.0 if name == f"crop_{crop_key}" else 0.0
        elif name.startswith("soil_"):
            X[name] = 1.0 if name == f"soil_{soil_type}" else 0.0
        elif name in weather.columns:
            X[name] = weather[name].to_numpy(dtype=float)
        else:
            X[name] = np.nan
    # Soil features must describe the PARCEL, overriding the department default the
    # weather panel was built with.
    s = soils().get(soil_type)
    if s:
        if "reserve_utile_mm" in X.columns:
            X["reserve_utile_mm"] = s["reserve_utile_mm"]
        if "soil_ph" in X.columns:
            X["soil_ph"] = s["ph"]
        if "drought_stress_index" in X.columns and "flowering_water_balance_mm" in weather:
            X["drought_stress_index"] = (
                -weather["flowering_water_balance_mm"].to_numpy(dtype=float)
                / max(s["reserve_utile_mm"], 40.0)
            )
        if "heat_x_shallow_soil" in X.columns and "jun_heat_days_30c" in weather:
            X["heat_x_shallow_soil"] = weather["jun_heat_days_30c"].to_numpy(dtype=float) * (
                140.0 / max(s["reserve_utile_mm"], 40.0)
            )
    return X[b["feature_names"]]


def predict_yield_quantiles(
    crop_key: str,
    dept_code: str,
    soil_type: str,
    weather: pd.DataFrame,
    *,
    parcel_level: bool = True,
    suitability: float = 1.0,
) -> dict[str, np.ndarray]:
    """Absolute yield quantiles (t/ha), one row per weather draw.

    Conformal offsets fitted on a held-out forward calibration block are applied to
    both the interval width and the median bias, then the interval is widened by the
    parcel variance inflation factor because the training labels are department means.
    """
    n = len(weather)
    base, base_src = baseline_yield(crop_key, dept_code, soil_type)
    b = bundle()

    if b is None:
        # Reference-table fallback: a fixed CV around the reference yield.
        cv = 0.26
        med = np.full(n, base * suitability)
        return {
            "q15": med * (1 - 1.04 * cv), "q50": med, "q85": med * (1 + 1.04 * cv),
            "baseline": base, "baseline_source": base_src, "ratio_q50": np.ones(n),
        }

    X = _design(weather, crop_key, soil_type, b)
    lo = b["models"]["q15"].predict(X)
    med = b["models"]["q50"].predict(X)
    hi = b["models"]["q85"].predict(X)

    off = b["conformal_offsets"]
    o = off.get(crop_key, off["__global__"])
    # One-sided corrections: each tail is adjusted by its own conformity quantile.
    # Older artifacts stored a single symmetric "width"; fall back to it if present.
    wlo = o.get("width_lo", o.get("width", 0.0))
    whi = o.get("width_hi", o.get("width", 0.0))
    lo, med, hi = lo - wlo, med + o["median_bias"], hi + whi
    lo, hi = np.minimum(lo, med), np.maximum(hi, med)

    if parcel_level:
        k = float(b.get("parcel_variance_inflation", 1.2))
        lo, hi = med - (med - lo) * k, med + (hi - med) * k

    lo, med, hi = (np.clip(v, 0.0, None) for v in (lo, med, hi))
    f = base * float(suitability)
    return {
        "q15": lo * f, "q50": med * f, "q85": hi * f,
        "baseline": base, "baseline_source": base_src, "ratio_q50": med,
    }


def sample_yields(
    rng: np.random.Generator,
    crop_key: str,
    dept_code: str,
    soil_type: str,
    weather: pd.DataFrame,
    *,
    suitability: float = 1.0,
    common_shock: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """Draw one yield per weather row.

    The spread around the conditional median is split into a part explained by the
    sampled weather (already in the quantiles) and an unexplained residual. Passing
    `common_shock` reuses the SAME standardised residual draw across crops, so a
    farmer who is unlucky in the pulse arm is equally unlucky in the baseline arm.
    Without that, the comparison would credit the pulse with the baseline's noise.
    """
    q = predict_yield_quantiles(
        crop_key, dept_code, soil_type, weather, suitability=suitability
    )
    # The conformalised interval is ASYMMETRIC around the median: for lentil the
    # median sits much closer to q15 than to q85. A single symmetric sd would not
    # reproduce either stated quantile, and in practice drove the sampled lower tail
    # far below anything ever observed. A two-piece normal reproduces both.
    # The 15th and 85th percentiles of a standard normal sit at -+1.0364.
    sd_lo = np.maximum((q["q50"] - q["q15"]) / 1.0364, 1e-6)
    sd_hi = np.maximum((q["q85"] - q["q50"]) / 1.0364, 1e-6)
    z = common_shock if common_shock is not None else rng.standard_normal(len(weather))
    draw = q["q50"] + np.where(z < 0.0, sd_lo, sd_hi) * z
    return np.clip(draw, 0.0, q["q50"] * 2.2), q


def irrigation_factor(crop_key: str, irrigated: bool) -> tuple[float, str]:
    """Correct the mixed Agreste departmental yield to the parcel's water regime.

    Agreste publishes one yield per department per crop, blending irrigated and
    rain-fed area. For soybean, whose French area is majority irrigated, using that
    blended mean for a rain-fed parcel overstates yield by roughly 25 percent.
    """
    from ..config import load_ref

    ref = load_ref("irrigation")
    spec = ref["crops"].get(crop_key, ref["default"])
    s = float(spec["irrigated_share_of_area"])
    u = float(spec["irrigation_yield_uplift"])
    rainfed = 1.0 / (1.0 + s * u)
    if irrigated:
        factor, how = rainfed * (1.0 + u), "irrigated"
    else:
        factor, how = rainfed, "rain-fed"
    note = (
        f"Agreste departmental yield blends {s:.0%} irrigated area; "
        f"adjusted to a {how} parcel by x{factor:.2f}."
    )
    return float(factor), note
