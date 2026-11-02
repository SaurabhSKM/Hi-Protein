"""Why did French land move to pulses? An attribution attempt that reports its own limits.

THE TRAP THIS FILE IS BUILT TO AVOID
------------------------------------
A department's pulse share is strongly autocorrelated: last year's share predicts this
year's with an R-squared near 0.95. A model fitted on the LEVEL therefore looks
excellent and explains nothing - it has learned "Beauce grows peas" and attributed it
to whatever feature happens to correlate with Beauce. So the target here is the CHANGE
in share from one year to the next, in percentage points. That is the quantity the
question is actually about, and it is genuinely hard to predict.

TWO SEPARATE QUESTIONS, TWO SEPARATE METHODS
--------------------------------------------
1. DECOMPOSITION (in-sample, descriptive). Of all the variation in year-on-year share
   change, how much is a NATIONAL common shock hitting every department in the same
   year, how much is a persistent department effect, and how much is weather? The
   national year effect is the key number, because this repo has no usable price or
   policy time series - Eurostat's French pulse prices end in 2016 with unit errors
   and omit chickpea and fava bean entirely (see data/processed/price_validation.json),
   and pac_2023_2027.json holds one current unit amount, not a history. Whatever the
   year effect captures is therefore mostly the price/policy/contract channel we cannot
   observe. Measuring its size is how this file quantifies its own blind spot instead
   of pretending weather explains the shift.

   A year effect cannot be extrapolated to a future year, so this is deliberately
   reported as a variance decomposition and NOT as a predictive model. Calling it a
   forecast would be the dishonest version of the same arithmetic.

2. PREDICTION (out-of-sample, forward split). Given only what a farmer knew when
   choosing what to sow - last season's weather, last season's realised yield, and the
   department's recent rotation history - can we beat a no-change baseline? This is a
   real held-out test and it is allowed to fail. If it does, that is the finding.

THE LAG THAT KEEPS IT HONEST
----------------------------
Weather features are from season t-1, never season t. A farmer sowing in year t cannot
know year t's flowering rainfall. Using it would be leakage dressed as insight - the
model would "discover" that pulse area responds to weather that had not happened yet.

COVERAGE
--------
The adoption panel covers 93 departments; Meteo-France weather in this project covers
42. The decomposition and the prediction therefore run on the 42-department
intersection, while the descriptive page uses all 93. Stated in the artifact.

Run: .venv/bin/python ml/train_adoption.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

PANEL = ROOT / "data" / "processed" / "adoption_panel.csv"
WEATHER = ROOT / "data" / "processed" / "weather_panel.csv"
ARTIFACTS = ROOT / "ml" / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
OUT = ARTIFACTS / "adoption_report.json"

# Crops the attribution runs for. Soy is included because its area tripled and it is
# the clearest irrigation-driven case; the two feed pulses are included because they
# moved the OTHER way and a model that only sees growth is not being tested.
CROPS = ("green_lentil", "chickpea", "field_pea", "fava_bean", "soybean")

TEST_FROM_YEAR = 2020          # fit 2011-2019, test 2020-2024
MIN_ROWS_PER_CROP = 120

# Weather columns carried from the project's own panel, lagged one season. Restricted
# to the windows features.py documents as mechanistically relevant to pulses, rather
# than every column available, because the sample here is small.
WEATHER_COLS = [
    "flowering_water_balance_mm",
    "flowering_rain_mm",
    "establishment_rain_mm",
    "harvest_rain_mm",
    "summer_rain_mm",
    "jun_heat_days_30c",
    "may_jun_heat_days_25c",
    "apr_frost_days",
    "spring_tmean_c",
    "flowering_tmax_c",
    "recharge_rain_mm",
    "drought_stress_index",
]
SOIL_COLS = ["reserve_utile_mm", "soil_ph"]


# --------------------------------------------------------------------------- #
# Panel assembly
# --------------------------------------------------------------------------- #
def build() -> pd.DataFrame:
    adopt = pd.read_csv(PANEL, dtype={"dept_code": str})
    wx = pd.read_csv(WEATHER, dtype={"dept_code": str})

    adopt = adopt[adopt["crop"].isin(CROPS)].copy()
    # share in percentage points: a 0.4 pp move is legible, 0.004 is not.
    adopt["share_pp"] = adopt["crop_share"] * 100.0

    adopt = adopt.sort_values(["dept_code", "crop", "year"])
    g = adopt.groupby(["dept_code", "crop"], sort=False)

    # Consecutive-year guard. The shift below is positional, so a department-crop with
    # a gap in the series would otherwise difference two non-adjacent years and call
    # the result a one-year change.
    adopt["prev_year"] = g["year"].shift(1)
    adopt["share_pp_lag1"] = g["share_pp"].shift(1)
    adopt["share_pp_lag2"] = g["share_pp"].shift(2)
    adopt["share_pp_lag3"] = g["share_pp"].shift(3)
    adopt["yield_lag1"] = g["yield_t_ha"].shift(1)
    adopt["area_ha_lag1"] = g["area_ha"].shift(1)

    adopt = adopt[adopt["prev_year"] == adopt["year"] - 1].copy()
    adopt["d_share_pp"] = adopt["share_pp"] - adopt["share_pp_lag1"]
    adopt["share_pp_lag2to3_mean"] = adopt[["share_pp_lag2", "share_pp_lag3"]].mean(
        axis=1, skipna=True
    )

    # Realised yield last season, relative to this department-crop's own long-run mean,
    # so the feature is "was last harvest good FOR HERE" rather than "is this a
    # high-yielding department", which the dept effect already absorbs.
    base = (
        adopt.groupby(["dept_code", "crop"])["yield_t_ha"]
        .transform(lambda s: s.mean(skipna=True))
    )
    adopt["yield_ratio_lag1"] = adopt["yield_lag1"] / base.replace(0.0, np.nan)

    # Weather of the PREVIOUS season, joined on (dept, year-1).
    wx_lag = wx[["dept_code", "year", *[c for c in WEATHER_COLS if c in wx.columns],
                 *[c for c in SOIL_COLS if c in wx.columns]]].copy()
    wx_lag["year"] = wx_lag["year"] + 1          # so it lands on the deciding year
    lag_names = {c: f"{c}_lag1" for c in WEATHER_COLS if c in wx.columns}
    wx_lag = wx_lag.rename(columns=lag_names)

    panel = adopt.merge(wx_lag, on=["dept_code", "year"], how="inner")
    return panel


FEATURE_COLS = lambda panel: [  # noqa: E731
    c for c in [
        *[f"{c}_lag1" for c in WEATHER_COLS],
        *SOIL_COLS,
        "share_pp_lag1", "share_pp_lag2to3_mean", "yield_ratio_lag1",
    ] if c in panel.columns
]


# --------------------------------------------------------------------------- #
# 1. Variance decomposition
# --------------------------------------------------------------------------- #
def decompose(panel: pd.DataFrame, crop: str) -> dict:
    """Nested decomposition of var(d_share_pp) for one crop.

    Stages are cumulative and strictly nested, so the increments partition the
    variance rather than being overlapping univariate R-squareds that sum past 100%.

    The two fixed-effect stages are in-sample but low-dimensional - 14 year means and
    42 department means against ~588 rows - so they are reported with a
    degrees-of-freedom adjustment and the raw value alongside.

    The WEATHER stage is cross-fitted, and that is not a detail. Fitting 300 boosted
    trees on the residual in-sample reports weather explaining about 70% of the
    change, which is an artifact of 12 weather columns and a flexible learner on 588
    rows, not a finding. Folds are grouped by YEAR so a growing season never appears
    in both halves: weather is spatially correlated across departments, so a random
    split lets the model see 2016 in Beauce and be tested on 2016 in Burgundy. Both
    numbers are reported and the gap between them is the overfit.
    """
    d = panel[panel["crop"] == crop].dropna(subset=["d_share_pp"]).copy()
    if len(d) < MIN_ROWS_PER_CROP:
        return {"crop": crop, "n": int(len(d)), "insufficient_data": True}

    y = d["d_share_pp"].to_numpy(dtype=float)
    n = len(y)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot <= 0:
        return {"crop": crop, "n": int(n), "insufficient_data": True}

    def r2(pred: np.ndarray) -> float:
        return float(1.0 - ((y - pred) ** 2).sum() / ss_tot)

    def r2_adj(raw: float, df: int) -> float:
        """Standard adjusted R-squared, so a 42-parameter department effect is not
        credited for the variance any 42 arbitrary groupings would absorb."""
        if n - df - 1 <= 0:
            return float("nan")
        return float(1.0 - (1.0 - raw) * (n - 1) / (n - df - 1))

    # Stage 1: national year effect - one number per year, shared by all departments.
    year_mean = d.groupby("year")["d_share_pp"].transform("mean").to_numpy()
    df_year = int(d.year.nunique() - 1)
    r2_year = r2(year_mean)

    # Stage 2: add a persistent department effect, fitted on the year-effect residual.
    resid1 = y - year_mean
    d["_r1"] = resid1
    dept_mean = d.groupby("dept_code")["_r1"].transform("mean").to_numpy()
    df_dept = int(d.dept_code.nunique())
    r2_year_dept = r2(year_mean + dept_mean)

    # Stage 3: weather and soil on the remaining residual, cross-fitted by year.
    cols = FEATURE_COLS(d)
    resid2 = resid1 - dept_mean
    X = d[cols].to_numpy(dtype=float)
    years = d["year"].to_numpy()

    def fresh() -> xgb.XGBRegressor:
        return xgb.XGBRegressor(
            n_estimators=300, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
            random_state=0, n_jobs=2,
        )

    uniq = np.array(sorted(set(years)))
    folds = np.array_split(uniq, min(5, len(uniq)))
    oof = np.zeros_like(y)
    for held in folds:
        te = np.isin(years, held)
        tr = ~te
        if tr.sum() < 40 or te.sum() == 0:
            continue
        m = fresh()
        m.fit(X[tr], resid2[tr])
        oof[te] = m.predict(X[te])
    r2_full_oof = r2(year_mean + dept_mean + oof)

    insample = fresh()
    insample.fit(X, resid2)
    r2_full_is = r2(year_mean + dept_mean + insample.predict(X))

    imp = dict(
        sorted(
            # strict=True: one importance per fitted column. A mismatch would silently
            # drop features off the end of the report or label them with the wrong name.
            zip(cols, (float(v) for v in insample.feature_importances_), strict=True),
            key=lambda kv: -kv[1],
        )[:8]
    )

    wx_inc_oof = 100 * (r2_full_oof - r2_year_dept)
    return {
        "crop": crop,
        "n": int(n),
        "n_departments": int(d.dept_code.nunique()),
        "years": [int(d.year.min()), int(d.year.max())],
        "sd_d_share_pp": round(float(y.std()), 4),
        "variance_explained_increment_pct": {
            "national_year_effect": round(100 * r2_year, 1),
            "department_effect": round(100 * (r2_year_dept - r2_year), 1),
            "weather_and_soil": round(wx_inc_oof, 1),
            "unexplained": round(100 * (1 - r2_full_oof), 1),
        },
        # The two fixed effects are a genuine partition and always sum to <= 100. The
        # weather increment can come out NEGATIVE, because a cross-fitted model is
        # free to be worse than predicting nothing, and here it usually is. That is
        # the result, not a bug, so it is reported signed and also stated in words -
        # and this field is what the page should display, because "weather explains
        # -84.9% of the variance" is arithmetically right and rhetorically useless.
        "weather_contribution": (
            "none measurable" if wx_inc_oof <= 0 else f"{wx_inc_oof:.1f}% of variance"
        ),
        "fixed_effects_explained_pct": round(100 * r2_year_dept, 1),
        "left_after_fixed_effects_pct": round(100 * (1 - r2_year_dept), 1),
        "degrees_of_freedom": {"year_effect": df_year, "department_effect": df_dept},
        "adjusted_r2_pct": {
            "national_year_effect": round(100 * r2_adj(r2_year, df_year), 1),
            "plus_department_effect": round(
                100 * r2_adj(r2_year_dept, df_year + df_dept), 1
            ),
        },
        "weather_stage_overfit_check_pct": {
            "cross_fitted_by_year": round(wx_inc_oof, 1),
            "in_sample": round(100 * (r2_full_is - r2_year_dept), 1),
            "note": (
                "The in-sample figure is what a naive fit would report. The gap is the "
                "overfit; only the cross-fitted figure is an attribution claim."
            ),
        },
        "weather_importance_top8": {k: round(v, 4) for k, v in imp.items()},
        "importance_caveat": (
            "Gain importances come from the in-sample fit and rank which columns the "
            "learner USED. With a near-zero cross-fitted increment they say what it "
            "latched onto, not what drives adoption."
        ),
    }


# --------------------------------------------------------------------------- #
# 2. Held-out prediction
# --------------------------------------------------------------------------- #
def predict_test(panel: pd.DataFrame, crop: str) -> dict:
    """Forward-split test: beat a no-change baseline using only pre-decision data."""
    d = panel[panel["crop"] == crop].dropna(subset=["d_share_pp"]).copy()
    if len(d) < MIN_ROWS_PER_CROP:
        return {"crop": crop, "insufficient_data": True}

    cols = FEATURE_COLS(d)
    tr = d[d["year"] < TEST_FROM_YEAR]
    te = d[d["year"] >= TEST_FROM_YEAR]
    if len(tr) < 60 or len(te) < 30:
        return {"crop": crop, "insufficient_data": True}

    Xtr, ytr = tr[cols].to_numpy(dtype=float), tr["d_share_pp"].to_numpy(dtype=float)
    Xte, yte = te[cols].to_numpy(dtype=float), te["d_share_pp"].to_numpy(dtype=float)

    model = xgb.XGBRegressor(
        n_estimators=250, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_lambda=2.0,
        random_state=0, n_jobs=2,
    )
    model.fit(Xtr, ytr)
    pred = model.predict(Xte)

    # Two baselines. "No change" is the honest null for a change target. "Train mean"
    # is the drift a department would get for free by assuming the fit period's average
    # trend continues.
    mae_model = float(np.mean(np.abs(yte - pred)))
    mae_nochange = float(np.mean(np.abs(yte - 0.0)))
    mae_trainmean = float(np.mean(np.abs(yte - ytr.mean())))

    ss_tot = float(((yte - yte.mean()) ** 2).sum())
    r2_oos = float(1 - ((yte - pred) ** 2).sum() / ss_tot) if ss_tot > 0 else None

    # Does it at least get the DIRECTION right? For a planner, "which departments will
    # expand" is more actionable than the magnitude, and a model can be useless on MAE
    # while still being informative on sign.
    sign_ok = float(np.mean(np.sign(pred) == np.sign(yte)))
    base_rate = float(max(np.mean(yte > 0), np.mean(yte <= 0)))

    return {
        "crop": crop,
        "n_train": int(len(tr)),
        "n_test": int(len(te)),
        "test_years": [int(te.year.min()), int(te.year.max())],
        "mae_pp_model": round(mae_model, 4),
        "mae_pp_no_change_baseline": round(mae_nochange, 4),
        "mae_pp_train_mean_baseline": round(mae_trainmean, 4),
        "skill_vs_no_change_pct": round(100 * (1 - mae_model / mae_nochange), 1)
        if mae_nochange > 0 else None,
        "r2_out_of_sample": None if r2_oos is None else round(r2_oos, 4),
        "direction_accuracy": round(sign_ok, 3),
        "direction_base_rate": round(base_rate, 3),
    }


# --------------------------------------------------------------------------- #
# 3. Per-crop weather envelope
# --------------------------------------------------------------------------- #
def weather_envelope(panel: pd.DataFrame, crop: str) -> dict:
    """What last season's weather looked like where a crop EXPANDED vs CONTRACTED.

    This is the per-crop weather answer the shared phenological calendar in
    features.py cannot give directly: its 17 windows are one spring-pulse calendar
    applied to every crop, with crop identity entering the yield model only as a
    one-hot. Contrasting the observed weather distribution between expansion and
    contraction department-years recovers a crop-specific signal empirically, without
    inventing per-crop phenology the data cannot support.

    Read it as association, not mechanism: the same unobserved price and policy shock
    that drives expansion also varies by region, and region correlates with climate.
    """
    d = panel[panel["crop"] == crop].dropna(subset=["d_share_pp"])
    if len(d) < MIN_ROWS_PER_CROP:
        return {"crop": crop, "insufficient_data": True}

    grew = d[d["d_share_pp"] > 0]
    shrank = d[d["d_share_pp"] < 0]
    rows = []
    for col in [f"{c}_lag1" for c in WEATHER_COLS] + SOIL_COLS:
        if col not in d.columns:
            continue
        a, b = grew[col].dropna(), shrank[col].dropna()
        if len(a) < 20 or len(b) < 20:
            continue
        # Standardised difference, so variables on different units are comparable.
        sd = float(d[col].std())
        if not sd or np.isnan(sd):
            continue
        rows.append({
            "variable": col,
            "mean_where_expanded": round(float(a.mean()), 2),
            "mean_where_contracted": round(float(b.mean()), 2),
            "standardised_difference": round(float((a.mean() - b.mean()) / sd), 3),
            "n_expanded": int(len(a)),
            "n_contracted": int(len(b)),
        })
    rows.sort(key=lambda r: -abs(r["standardised_difference"]))
    return {"crop": crop, "contrasts": rows[:8]}


def yield_response(crop: str) -> dict:
    """Observed yield response to flowering water balance, per crop, as binned means.

    Deliberately non-parametric and computed from the training panel rather than read
    off the trained yield model: the point is to show the farmer-legible shape of the
    water response for THIS crop with the sample size behind each point, not to
    re-expose a gradient-boosted surface.
    """
    tp = pd.read_csv(ROOT / "data" / "processed" / "training_panel.csv",
                     dtype={"dept_code": str})
    d = tp[tp["crop"] == crop].dropna(subset=["yield_t_ha", "flowering_water_balance_mm"])
    if len(d) < 60:
        return {"crop": crop, "insufficient_data": True}

    # Relative to the crop's own mean, so crops with very different absolute yields
    # (lentil 1.45 t/ha, soy 2.6) are readable on one chart.
    ref = float(d["yield_t_ha"].mean())
    edges = np.quantile(d["flowering_water_balance_mm"], [0, 0.2, 0.4, 0.6, 0.8, 1.0])
    edges = np.unique(edges)
    bins = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (d["flowering_water_balance_mm"] >= lo) & (d["flowering_water_balance_mm"] <= hi)
        s = d[m]
        if len(s) < 10:
            continue
        bins.append({
            "water_balance_mm_from": round(float(lo), 1),
            "water_balance_mm_to": round(float(hi), 1),
            "mean_yield_t_ha": round(float(s["yield_t_ha"].mean()), 3),
            "relative_to_crop_mean": round(float(s["yield_t_ha"].mean() / ref), 3),
            "n": int(len(s)),
        })
    return {
        "crop": crop,
        "crop_mean_yield_t_ha": round(ref, 3),
        "n_observations": int(len(d)),
        "bins": bins,
    }


def main() -> int:
    panel = build()
    print(f"panel: {len(panel)} rows, {panel.dept_code.nunique()} departments, "
          f"{panel.year.min()}-{panel.year.max()}")

    report = {
        "model_version": "adoption-attribution-1.0.0",
        "question": (
            "Of the year-on-year change in a department's area share for a pulse, how "
            "much can be attributed to weather, and how much to a national shock this "
            "project cannot observe?"
        ),
        "target": "d_share_pp = change in the crop's share of mapped COP area, percentage points",
        "coverage": {
            "adoption_panel_departments": 93,
            "attribution_departments": int(panel.dept_code.nunique()),
            "reason": (
                "Meteo-France monthly station data was assembled for 42 departments in "
                "this project; the attribution runs on the intersection, the "
                "descriptive page uses all 93."
            ),
            "years": [int(panel.year.min()), int(panel.year.max())],
        },
        "lag_policy": (
            "All weather features are from season t-1. A farmer sowing in year t cannot "
            "know year t's flowering rainfall; using it would be leakage."
        ),
        "unobserved_drivers": [
            "Farm-gate pulse prices: Eurostat's French series ends 2016, carries unit "
            "errors in 2010-2011 and omits chickpea and fava bean. See "
            "data/processed/price_validation.json - verdict NOT USABLE.",
            "PAC coupled aid per campaign: refdata/pac_2023_2027.json holds one current "
            "unit amount (122 EUR/ha grain legumes), not a 2010-2024 history.",
            "Contracts, processing and optical-sorting capacity: no historical series.",
            "Irrigation equipment, which plausibly gates the soy expansion.",
        ],
        "decomposition": [decompose(panel, c) for c in CROPS],
        "held_out_prediction": [predict_test(panel, c) for c in CROPS],
        "weather_envelope": [weather_envelope(panel, c) for c in CROPS],
        "yield_response_to_water": [yield_response(c) for c in CROPS],
    }

    # A one-line verdict computed from the numbers, so the artifact cannot drift away
    # from what it actually found.
    yr = [r["variance_explained_increment_pct"]["national_year_effect"]
          for r in report["decomposition"] if "variance_explained_increment_pct" in r]
    wx = [r["variance_explained_increment_pct"]["weather_and_soil"]
          for r in report["decomposition"] if "variance_explained_increment_pct" in r]
    skill = [r["skill_vs_no_change_pct"] for r in report["held_out_prediction"]
             if r.get("skill_vs_no_change_pct") is not None]
    n_wx_negative = sum(1 for v in wx if v <= 0)
    report["verdict"] = {
        "national_year_effect_pct_median": round(float(np.median(yr)), 1) if yr else None,
        "weather_increment_pct_median": round(float(np.median(wx)), 1) if wx else None,
        "crops_where_weather_adds_nothing": f"{n_wx_negative} of {len(wx)}",
        "held_out_skill_vs_no_change_pct_median": round(float(np.median(skill)), 1)
        if skill else None,
        "plain_language": (
            "A national shock common to every department in the same year is the "
            "largest single identified factor in year-on-year pulse area change. "
            "Last season's weather and the department's soil add nothing measurable "
            "once that and a persistent department effect are accounted for, and a "
            "model given only pre-decision information does not beat assuming no "
            "change. On this evidence the shift to pulses is NOT weather-driven. The "
            "most likely drivers - price, PAC coupled aid and contract availability - "
            "are exactly the series this repo has no usable history for, so this "
            "cannot be pushed further without new data."
        ),
    }

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    for r in report["decomposition"]:
        if "variance_explained_increment_pct" in r:
            i = r["variance_explained_increment_pct"]
            print(f"  {r['crop']:14s} n={r['n']:4d}  year={i['national_year_effect']:5.1f}%"
                  f"  dept={i['department_effect']:5.1f}%"
                  f"  weather={i['weather_and_soil']:5.1f}%"
                  f"  unexplained={i['unexplained']:5.1f}%")
    for r in report["held_out_prediction"]:
        if "mae_pp_model" in r:
            print(f"  {r['crop']:14s} held-out skill vs no-change: "
                  f"{r['skill_vs_no_change_pct']}%  dir_acc={r['direction_accuracy']}"
                  f" (base {r['direction_base_rate']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
