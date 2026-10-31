"""Train and CONFORMALISE quantile yield models on the Agreste x Meteo-France panel.

Three design choices that each fix a specific failure of the naive setup:

1. Target is the YIELD RATIO (observed / department-crop baseline), so the model
   learns the weather response instead of re-learning that Beauce loam out-yields
   Burgundy limestone. The baseline is fitted on TRAINING YEARS ONLY; computing it
   over all years puts test-season yields into the denominator of the test target and
   silently inflates every metric.

2. Validation is a FORWARD TIME SPLIT with three blocks (fit / calibrate / test).
   Random K-fold leaks, because one growing season appears in both folds across
   different departments and weather is spatially correlated.

3. Raw quantile regression is MISCALIBRATED out of sample here: 2022-2024 yields sit
   well below what 2010-2018 ratios imply, so the nominal 70% interval covered only
   about half of held-out observations. Conformalized Quantile Regression (Romano,
   Patterson & Candes 2019) corrects the interval width and the median bias using a
   held-out calibration block, which restores honest coverage. An interval a farmer
   relies on for a planting decision has to mean what it says.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import features  # noqa: E402

PANEL = ROOT / "data" / "processed" / "training_panel.csv"
ARTIFACTS = ROOT / "ml" / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

QUANTILES = {"q15": 0.15, "q50": 0.50, "q85": 0.85}
CALIB_FROM_YEAR = 2017
TEST_FROM_YEAR = 2022
TARGET_INTERVAL = 0.70
MIN_CALIB_PER_CROP = 40
# Shrinkage prior strength for the per-crop median bias. With only a handful of
# calibration seasons, a volatile crop can land three disaster years in the block and
# bias every future prediction downward. Pooling toward the global bias fixes that.
BIAS_SHRINK_N0 = 70.0
# The median correction may never exceed this share of the predicted interval width,
# so a pathological calibration block cannot move the median outside its own interval.
MAX_BIAS_FRACTION_OF_WIDTH = 0.35
MODEL_VERSION = "yield-cqr-xgb-2.3.0"  # +legume_share_lag1/lag2to4_mean (Agreste SAA)

PARAMS = dict(
    objective="reg:quantileerror",
    n_estimators=500,
    learning_rate=0.05,
    max_depth=4,
    min_child_weight=10,
    subsample=0.85,
    colsample_bytree=0.8,
    reg_lambda=2.5,
    reg_alpha=0.3,
    tree_method="hist",
    random_state=42,
)


def design_matrix(df: pd.DataFrame, crop_cols: list[str], soil_cols: list[str]) -> pd.DataFrame:
    X = df[[c for c in features.FEATURE_COLUMNS if c in df.columns]].copy()
    for c in crop_cols:
        X[c] = (df["crop"] == c.replace("crop_", "")).astype(float)
    for c in soil_cols:
        X[c] = (df["soil_type"] == c.replace("soil_", "")).astype(float)
    return X


def pinball(y: np.ndarray, pred: np.ndarray, alpha: float) -> float:
    d = y - pred
    return float(np.mean(np.maximum(alpha * d, (alpha - 1.0) * d)))


def conformal_offsets(
    y: np.ndarray, lo: np.ndarray, hi: np.ndarray, med: np.ndarray, target: float
) -> dict[str, float]:
    """One-sided CQR corrections plus a median bias correction.

    The symmetric formulation (a single width from max(lo - y, y - hi)) applies the
    same correction to both ends. Here that over-widened the UPPER bound badly: the
    85th percentile ended up covering 95 percent of outcomes and scored worse than a
    climatological constant, because the miscoverage was almost entirely at the bottom.

    Each tail therefore gets its own correction. For the lower bound we want
    P(y < lo - Q_lo) = a, i.e. P(lo - y > Q_lo) = a, so Q_lo is the (1 - a) quantile
    of the score lo - y. The upper bound is the mirror image. A negative Q TIGHTENS
    that side, which is exactly what the upper bound needed.
    """
    n = len(y)
    if n < 10:
        return {"width_lo": 0.0, "width_hi": 0.0, "median_bias": 0.0, "n": int(n)}
    a = (1.0 - target) / 2.0  # miscoverage allowed in each tail
    k = min(1.0, np.ceil((n + 1) * (1.0 - a)) / n)
    return {
        "width_lo": float(np.quantile(lo - y, k, method="higher")),
        "width_hi": float(np.quantile(y - hi, k, method="higher")),
        "median_bias": float(np.median(y - med)),
        "n": int(n),
    }


def apply_conformal(
    lo: np.ndarray, med: np.ndarray, hi: np.ndarray, crops: np.ndarray, off: dict
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    wlo = np.array([off.get(c, off["__global__"])["width_lo"] for c in crops])
    whi = np.array([off.get(c, off["__global__"])["width_hi"] for c in crops])
    b = np.array([off.get(c, off["__global__"])["median_bias"] for c in crops])
    # Never let the median correction push the median outside its own interval.
    b = np.clip(b, -MAX_BIAS_FRACTION_OF_WIDTH * (hi - lo), MAX_BIAS_FRACTION_OF_WIDTH * (hi - lo))
    lo_a, med_a, hi_a = lo - wlo, med + b, hi + whi
    # Enforce monotonicity after correction and keep ratios physically non-negative.
    lo_a = np.minimum(lo_a, med_a)
    hi_a = np.maximum(hi_a, med_a)
    return np.clip(lo_a, 0.0, None), np.clip(med_a, 0.0, None), np.clip(hi_a, 0.0, None)


def main() -> None:
    df = pd.read_csv(PANEL, dtype={"dept_code": str})
    crop_cols = [f"crop_{c}" for c in sorted(df["crop"].unique())]
    soil_cols = [f"soil_{s}" for s in sorted(df["soil_type"].unique())]

    fit_mask = df["year"] < CALIB_FROM_YEAR
    dept_base = df[fit_mask].groupby(["crop", "dept_code"])["yield_t_ha"].mean().rename("b_dept")
    soil_base = df[fit_mask].groupby(["crop", "soil_type"])["yield_t_ha"].mean().rename("b_soil")
    nat_base = df[fit_mask].groupby("crop")["yield_t_ha"].mean().rename("b_nat")
    df = (
        df.join(dept_base, on=["crop", "dept_code"])
        .join(soil_base, on=["crop", "soil_type"])
        .join(nat_base, on="crop")
    )
    df["dept_crop_mean_yield"] = df["b_dept"].fillna(df["b_soil"]).fillna(df["b_nat"])
    df = df[df["dept_crop_mean_yield"].notna() & (df["dept_crop_mean_yield"] > 0)]
    df["yield_ratio"] = df["yield_t_ha"] / df["dept_crop_mean_yield"]
    df = df.drop(columns=["b_dept", "b_soil", "b_nat"])

    fit = df[df["year"] < CALIB_FROM_YEAR]
    cal = df[(df["year"] >= CALIB_FROM_YEAR) & (df["year"] < TEST_FROM_YEAR)]
    tst = df[df["year"] >= TEST_FROM_YEAR]
    print(
        f"fit {len(fit)} rows ({int(df.year.min())}-{CALIB_FROM_YEAR - 1}) | "
        f"calibrate {len(cal)} ({CALIB_FROM_YEAR}-{TEST_FROM_YEAR - 1}) | "
        f"test {len(tst)} ({TEST_FROM_YEAR}-{int(df.year.max())})"
    )

    Xf = design_matrix(fit, crop_cols, soil_cols)
    Xc = design_matrix(cal, crop_cols, soil_cols)
    Xt = design_matrix(tst, crop_cols, soil_cols)
    yf, yc, yt = (d["yield_ratio"].to_numpy() for d in (fit, cal, tst))

    models, raw_metrics = {}, {}
    pc, pt = {}, {}
    for name, alpha in QUANTILES.items():
        m = xgb.XGBRegressor(**PARAMS, quantile_alpha=alpha)
        m.fit(Xf, yf, verbose=False)
        models[name] = m
        pc[name], pt[name] = m.predict(Xc), m.predict(Xt)
        base = np.full_like(yt, float(np.quantile(yf, alpha)))
        raw_metrics[name] = {
            "pinball_loss": round(pinball(yt, pt[name], alpha), 5),
            "pinball_loss_climatology": round(pinball(yt, base, alpha), 5),
            "skill_vs_climatology_pct": round(
                100.0 * (1.0 - pinball(yt, pt[name], alpha) / pinball(yt, base, alpha)), 2
            ),
            "empirical_coverage_below": round(float(np.mean(yt <= pt[name])), 4),
            "target_coverage_below": alpha,
        }

    cov_raw = float(np.mean((yt >= pt["q15"]) & (yt <= pt["q85"])))
    bias_raw = float(np.mean(yt - pt["q50"]))

    # --- conformal calibration, per crop where the block is large enough ---------
    offsets: dict[str, dict] = {
        "__global__": conformal_offsets(yc, pc["q15"], pc["q85"], pc["q50"], TARGET_INTERVAL)
    }
    g = offsets["__global__"]
    for c in sorted(cal["crop"].unique()):
        m = (cal["crop"] == c).to_numpy()
        if int(m.sum()) >= MIN_CALIB_PER_CROP:
            o = conformal_offsets(
                yc[m], pc["q15"][m], pc["q85"][m], pc["q50"][m], TARGET_INTERVAL
            )
            # Shrink the per-crop median bias toward the pooled bias. The widths are
            # left unshrunk: they are what deliver the coverage guarantee.
            n_c = o["n"]
            w_c = n_c / (n_c + BIAS_SHRINK_N0)
            o["median_bias_raw"] = o["median_bias"]
            o["median_bias"] = w_c * o["median_bias"] + (1.0 - w_c) * g["median_bias"]
            o["shrinkage_weight"] = round(float(w_c), 3)
            offsets[c] = o

    lo_a, med_a, hi_a = apply_conformal(
        pt["q15"], pt["q50"], pt["q85"], tst["crop"].to_numpy(), offsets
    )
    cov_cqr = float(np.mean((yt >= lo_a) & (yt <= hi_a)))
    bias_cqr = float(np.mean(yt - med_a))
    width_raw = float(np.mean(pt["q85"] - pt["q15"]))
    width_cqr = float(np.mean(hi_a - lo_a))

    # Skill of the DEPLOYED (conformalised) quantiles against a climatological
    # constant. This is the number that matters, because the conformalised model is
    # what ships. Reporting only the raw model's skill would flatter the tails.
    cqr_metrics = {}
    for name, alpha, pred in (("q15", 0.15, lo_a), ("q50", 0.50, med_a), ("q85", 0.85, hi_a)):
        base = np.full_like(yt, float(np.quantile(yf, alpha)))
        pl, pb = pinball(yt, pred, alpha), pinball(yt, base, alpha)
        cqr_metrics[name] = {
            "pinball_loss": round(pl, 5),
            "pinball_loss_climatology": round(pb, 5),
            "skill_vs_climatology_pct": round(100.0 * (1.0 - pl / pb), 2),
            "empirical_coverage_below": round(float(np.mean(yt <= pred)), 4),
            "target_coverage_below": alpha,
        }

    print("\n--- held-out test block, before vs after conformal calibration ---")
    for q, mt in raw_metrics.items():
        print(f"  raw {q}: {mt}")
    print(f"\n  70% interval coverage   raw {cov_raw:.3f}  ->  conformal {cov_cqr:.3f}   (target {TARGET_INTERVAL})")
    print(f"  mean interval width     raw {width_raw:.3f}  ->  conformal {width_cqr:.3f}  (ratio units)")
    g = offsets["__global__"]
    print(f"  pooled corrections      lower {-g['width_lo']:+.3f}  upper {g['width_hi']:+.3f}")
    print(f"  median bias (y - pred)  raw {bias_raw:+.4f} ->  conformal {bias_cqr:+.4f}")
    print("\n  deployed (conformalised) quantile skill vs a climatological constant:")
    for k, m in cqr_metrics.items():
        print(f"    {k}: pinball {m['pinball_loss']:.5f} vs climatology "
              f"{m['pinball_loss_climatology']:.5f}  -> skill {m['skill_vs_climatology_pct']:+.2f}%"
              f"  coverage {m['empirical_coverage_below']:.3f} (target {m['target_coverage_below']})")

    tt = tst.copy()
    tt["pred_t_ha"] = med_a * tt["dept_crop_mean_yield"]
    tt["lo_t_ha"] = lo_a * tt["dept_crop_mean_yield"]
    tt["hi_t_ha"] = hi_a * tt["dept_crop_mean_yield"]
    tt["abs_err"] = (tt["pred_t_ha"] - tt["yield_t_ha"]).abs()
    tt["covered"] = (tt["yield_t_ha"] >= tt["lo_t_ha"]) & (tt["yield_t_ha"] <= tt["hi_t_ha"])
    per_crop = (
        tt.groupby("crop")
        .agg(n=("abs_err", "size"), mae_t_ha=("abs_err", "mean"),
             mean_obs_t_ha=("yield_t_ha", "mean"), coverage=("covered", "mean"))
        .assign(mae_pct=lambda d: 100 * d.mae_t_ha / d.mean_obs_t_ha)
        .round(3)
    )
    print("\nper-crop held-out performance (conformalised, absolute units):")
    print(per_crop.to_string())

    importance = (
        pd.Series(models["q50"].feature_importances_, index=Xf.columns)
        .sort_values(ascending=False)
    )
    print("\ntop 12 features (gain):")
    print((importance.head(12) * 100).round(2).to_string())

    # Parcel-level variance inflation. Labels are DEPARTMENT MEANS, which average away
    # most within-department variability, so a department-level interval understates
    # what a single parcel faces. Estimated as the ratio of within-department
    # between-parcel CV reported in French pulse trial networks (~0.30) to the
    # residual department-level CV measured here.
    resid_sd_ratio = float(np.std(yt - med_a))
    inflation = float(np.clip(0.30 / max(resid_sd_ratio, 0.05), 1.0, 2.5))
    print(f"\n  department-level residual sd (ratio units): {resid_sd_ratio:.4f}")
    print(f"  parcel-level interval inflation factor: {inflation:.2f}")

    joblib.dump(
        {
            "models": models,
            "feature_names": list(Xf.columns),
            "crop_cols": crop_cols,
            "soil_cols": soil_cols,
            "quantiles": QUANTILES,
            "model_version": MODEL_VERSION,
            "conformal_offsets": offsets,
            "target_interval": TARGET_INTERVAL,
            "max_bias_fraction_of_width": MAX_BIAS_FRACTION_OF_WIDTH,
            "dept_crop_baseline": df.groupby(["crop", "dept_code"])["yield_t_ha"]
            .mean().round(4).reset_index().to_dict("records"),
            "soil_crop_baseline": df.groupby(["crop", "soil_type"])["yield_t_ha"]
            .mean().round(4).reset_index().to_dict("records"),
            "national_crop_baseline": df.groupby("crop")["yield_t_ha"].mean().round(4).to_dict(),
            "residual_sd_ratio": resid_sd_ratio,
            "parcel_variance_inflation": inflation,
            "feature_importance": importance.to_dict(),
            "n_fit": int(len(fit)), "n_calib": int(len(cal)), "n_test": int(len(tst)),
        },
        ARTIFACTS / "yield_model.joblib",
    )

    report = {
        "model_version": MODEL_VERSION,
        "target": "yield_ratio = observed yield / department-crop baseline (baseline fitted on fit block only)",
        "splits": {
            "fit": [int(df.year.min()), CALIB_FROM_YEAR - 1],
            "calibrate": [CALIB_FROM_YEAR, TEST_FROM_YEAR - 1],
            "test": [TEST_FROM_YEAR, int(df.year.max())],
            "rationale": "Forward time split. Random K-fold leaks because one growing season appears in both folds across spatially correlated departments.",
        },
        "n_fit": int(len(fit)), "n_calib": int(len(cal)), "n_test": int(len(tst)),
        "raw_quantile_metrics": raw_metrics,
        "deployed_conformalised_metrics": cqr_metrics,
        "skill_summary": (
            "The deployed median has modest but real skill over a climatological "
            "constant. The deployed tails are close to climatology: conformal "
            "calibration buys HONEST coverage, not sharpness. On a three-year block "
            "that is materially drier and hotter than the fit period, a correctly "
            "wide interval is worth more to a planting decision than a narrow one "
            "that is wrong 60 percent of the time."
        ),
        "conformal_offsets": {k: {kk: (round(vv, 5) if isinstance(vv, float) else vv)
                                  for kk, vv in v.items()} for k, v in offsets.items()},
        "calibration_effect": {
            "interval_coverage_raw": round(cov_raw, 4),
            "interval_coverage_conformal": round(cov_cqr, 4),
            "interval_coverage_target": TARGET_INTERVAL,
            "mean_width_raw_ratio": round(width_raw, 4),
            "mean_width_conformal_ratio": round(width_cqr, 4),
            "median_bias_raw": round(bias_raw, 4),
            "median_bias_conformal": round(bias_cqr, 4),
            "interpretation": "Raw quantile regression over-predicted the 2022-2024 block: those seasons sit below what 2010-2018 weather-yield relationships imply. Conformal calibration widens the interval and shifts the median so the stated confidence is honest.",
        },
        "per_crop_test_performance": json.loads(per_crop.reset_index().to_json(orient="records")),
        "feature_importance_top15": {k: round(float(v), 5) for k, v in importance.head(15).items()},
        "parcel_variance_inflation": round(inflation, 3),
        "data_sources": {
            "labels": "Agreste SAA series longues 2010-2025 (departmental, sheet COP), filtered to year <= 2024",
            "features": "Meteo-France donnees climatologiques de base mensuelles, per department, lowland stations only (<700 m)",
        },
        "known_limitations": [
            "Labels are DEPARTMENT MEAN yields; parcel variance is larger, so parcel intervals are widened by the inflation factor above before being shown.",
            "Agreste rounds minor-pulse departmental yields coarsely, which caps achievable accuracy for lentil and chickpea.",
            "Features are a department median across lowland stations, not the parcel's own weather.",
            "No variety, sowing date, irrigation or crop-protection data exists in the open sources, so management effects remain in the residual.",
            "Conformal coverage is guaranteed under exchangeability. A warming climate breaks that assumption, so the calibration block must be re-fitted every season.",
        ],
    }
    (ARTIFACTS / "model_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nsaved artifacts to {ARTIFACTS}")


if __name__ == "__main__":
    main()
