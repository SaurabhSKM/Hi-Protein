"""Join Agreste SAA yields to Meteo-France phenological windows -> training table."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import features  # noqa: E402
import sources  # noqa: E402

REFDATA = ROOT / "backend" / "app" / "refdata"
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

MODELLED_CROPS = [
    "field_pea", "fava_bean", "green_lentil", "chickpea", "soybean",
    "soft_wheat", "spring_barley", "rapeseed",
]
# Minimum area for a department-year observation to be trustworthy. Agreste rounds
# small areas hard, and a 40 ha departmental lentil "crop" is a few trial plots whose
# reported yield is nearly meaningless.
MIN_AREA_HA = {
    "green_lentil": 150.0, "chickpea": 120.0, "field_pea": 400.0,
    "fava_bean": 300.0, "soybean": 300.0,
    "soft_wheat": 2000.0, "spring_barley": 800.0, "rapeseed": 1500.0,
}


def _soil_lookup() -> dict[str, dict]:
    soils = json.loads((REFDATA / "soils.json").read_text(encoding="utf-8"))
    dept_soil = json.loads((REFDATA / "dept_soils.json").read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for dept, archetype in dept_soil.items():
        if dept.startswith("_"):
            continue
        out[dept] = {**soils[archetype], "soil_type": archetype}
    return out


def winsorise(df: pd.DataFrame, col: str, by: list[str], lo=0.02, hi=0.98) -> pd.DataFrame:
    """Clip extreme reported yields within each crop.

    Agreste publishes a handful of departmental minor-pulse yields that are real but
    operationally meaningless (a 0.1 t/ha lentil "harvest" on 150 ha). Left in, they
    dominate the 15th-percentile quantile model.
    """
    df = df.copy()
    bounds = df.groupby(by)[col].quantile([lo, hi]).unstack()
    bounds.columns = ["lo", "hi"]
    df = df.merge(bounds, left_on=by, right_index=True, how="left")
    df[col] = df[col].clip(df["lo"], df["hi"])
    return df.drop(columns=["lo", "hi"])


def build() -> pd.DataFrame:
    train_depts = (ROOT / "ml" / "train_depts.txt").read_text().split()

    # Departments wanted in the WEATHER panel but deliberately not in training,
    # because they have too little pulse area to contribute a useful label. Including
    # them still pays off twice: the Monte Carlo engine can sample a real local
    # climate for a parcel there instead of falling back to the national pool, and a
    # consumer joining a finer spatial grid to this panel gets full coverage of the
    # demo region. Their yield baseline falls back to the soil archetype, and the API
    # says so in its provenance.
    extra_path = ROOT / "ml" / "weather_only_depts.txt"
    weather_only = extra_path.read_text().split() if extra_path.exists() else []
    weather_depts = sorted(set(train_depts) | set(weather_only))

    soil_by_dept = _soil_lookup()

    print(
        f"building weather panel for {len(weather_depts)} departments "
        f"({len(train_depts)} trained on, {len(weather_only)} weather-only) ..."
    )
    weather = features.build_weather_panel(weather_depts, soil_by_dept)
    weather["soil_type"] = weather["dept_code"].map(
        lambda d: soil_by_dept.get(d, {}).get("soil_type", "clay_loam")
    )
    print(f"  weather panel: {weather.shape}")

    # Department rotation history, straight from the Agreste area series (real
    # "crop history" signal, lagged so it is never contemporary with the yield it
    # helps predict). Merged onto the weather panel, not the training panel
    # directly, so the Monte Carlo bootstrap in weather.py also carries it: each
    # sampled historical (dept, year) season brings its OWN real lagged legume
    # pressure along with its own real rainfall and heat, preserving the joint
    # structure between "what this department was growing" and "what the weather
    # did" in that exact season, the same way the weather features already do.
    print("computing department legume rotation pressure from Agreste SAA ...")
    legume = sources.load_legume_pressure()
    before = len(weather)
    weather = weather.merge(legume, on=["dept_code", "year"], how="left")
    assert len(weather) == before, "legume pressure merge must not change row count"

    # The weather panel reaches back to 1950 so the Monte Carlo bootstrap can sample
    # real historical extremes; Agreste's series starts in 2010. Years before that
    # have no legume-share match, and that gap lands squarely inside the 30-year
    # bootstrap window (sample_seasons draws 1995-2024), so roughly half of every
    # simulation's weather draws would silently carry NaN into these two columns at
    # inference. XGBoost was never trained on NaN here, since the training panel
    # only ever spans 2010-2024, so the fix is not "let the model handle it": it is
    # to fill with the best available estimate before the gap can reach inference.
    # That estimate is the department's own mean over the years Agreste actually
    # covers, which is the same department-legacy proxy already used for the
    # first few years inside the Agreste series itself (see load_legume_pressure).
    for col in ("legume_share_lag1", "legume_share_lag2to4_mean"):
        dept_mean = weather.groupby("dept_code")[col].transform("mean")
        weather[col] = weather[col].fillna(dept_mean)
        weather[col] = weather[col].fillna(weather[col].mean())
    still_missing = weather[["legume_share_lag1", "legume_share_lag2to4_mean"]].isna().sum().sum()
    assert still_missing == 0, f"legume pressure still has {still_missing} NaN after fallback"
    # The backend needs the weather panel on its own: the Monte Carlo engine
    # bootstraps real observed department-years rather than drawing independent
    # Gaussian weather, which would destroy the correlation between a dry flowering
    # and a hot June that actually co-occur.
    weather.to_csv(OUT / "weather_panel.csv", index=False)

    print("loading Agreste SAA yields ...")
    saa = sources.load_saa("dep")
    saa = saa[saa["crop"].isin(MODELLED_CROPS) & saa["dept_code"].isin(train_depts)]
    saa = saa[
        saa.apply(lambda r: r["area_ha"] >= MIN_AREA_HA.get(r["crop"], 200.0), axis=1)
    ]
    print(f"  SAA observations after area filter: {len(saa)}")

    df = saa.merge(weather, on=["dept_code", "year"], how="inner")
    print(f"  joined: {df.shape}")

    df = winsorise(df, "yield_t_ha", ["crop"])

    # The department-crop baseline that normalises the target is deliberately NOT
    # computed here. It must be fitted on training years only, otherwise the test
    # years leak into the denominator of the target. train.py owns that split.
    df["n_obs_dept_crop"] = df.groupby(["crop", "dept_code"])["yield_t_ha"].transform("size")
    df = df[df["n_obs_dept_crop"] >= 5]

    keep = (
        ["dept_code", "year", "crop", "soil_type", "area_ha", "yield_t_ha",
         "n_obs_dept_crop", "n_stations"]
        + features.FEATURE_COLUMNS
    )
    df = df[[c for c in keep if c in df.columns]].dropna(subset=["yield_t_ha"])
    df = df.dropna(subset=[c for c in features.FEATURE_COLUMNS if c in df.columns], how="any")

    out = OUT / "training_panel.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}  rows={len(df)}")
    print(df.groupby("crop").agg(
        n=("yield_t_ha", "size"),
        depts=("dept_code", "nunique"),
        mean_yield=("yield_t_ha", "mean"),
        p15=("yield_t_ha", lambda s: s.quantile(0.15)),
        p85=("yield_t_ha", lambda s: s.quantile(0.85)),
    ).round(2).to_string())
    return df


if __name__ == "__main__":
    build()
