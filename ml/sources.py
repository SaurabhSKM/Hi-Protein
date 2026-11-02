"""Fetch and tidy the two offline training sources.

Agreste SAA  -> department x crop x year area and yield (the label).
Meteo-France -> department x year phenological weather windows (the features).

Both are real French open data and both are cached on disk after first download.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROC_DIR = PROJECT_ROOT / "data" / "processed"
AGRESTE_DIR = RAW_DIR / "agreste"
METEO_DIR = RAW_DIR / "meteo"
for _d in (AGRESTE_DIR, METEO_DIR, PROC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "hiprotein-hackathon/1.0 (+agronomic research prototype)"}

# --------------------------------------------------------------------------- #
# Agreste SAA - Series longues depuis 2010
# --------------------------------------------------------------------------- #
SAA_ZIP_URL = (
    "https://agreste.agriculture.gouv.fr/agreste-web/download/publication/publie/"
    "SAA-SeriesLongues/SAA-SeriesLongues-2010-2025_DonneesProvisoires-"
    "DepartementalesRegionales.zip"
)
SAA_DEP_XLSX = "SAA_2010-2025_provisoires_donnees_departementales.xlsx"
SAA_REG_XLSX = "SAA_2010-2025_provisoires_donnees_regionales.xlsx"

# LIB_SAA numeric prefix -> internal crop key. The prefix is the stable identifier;
# the French labels carry accents and have been reworded between vintages.
SAA_CROP_CODES = {
    "01": "soft_wheat",
    "06": "durum_wheat",
    "08": "winter_barley",
    "09": "spring_barley",
    "29": "rapeseed",
    "32": "sunflower",
    "33": "soybean",
    "38": "fava_bean",
    "40": "green_lentil",
    "41": "field_pea",
    "43": "chickpea",
    "17": "grain_maize",
}


def download_saa(force: bool = False) -> Path:
    dest = AGRESTE_DIR / "saa_serieslongues.zip"
    if dest.exists() and not force and dest.stat().st_size > 1_000_000:
        return dest
    r = requests.get(SAA_ZIP_URL, headers=UA, timeout=300)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def load_saa(
    level: str = "dep", force: bool = False, require_yield: bool = True
) -> pd.DataFrame:
    """Tidy Agreste SAA into (dept_code, year, crop, area_ha, yield_t_ha, prod_t).

    `require_yield=True` (the default, and what the yield model trains on) keeps only
    rows that carry a published yield, which necessarily means area > 0.

    `require_yield=False` is for the ADOPTION question, where the zero is the signal.
    A department that grew no lentils in 2010 and 400 ha in 2019 only has the first
    half of that transition if `area_ha == 0` rows survive; filtering them out leaves
    the series starting at 400 and makes the arrival invisible. Rows where `area_ha`
    is blank are still dropped either way - a missing publication is not a zero.
    """
    zf = zipfile.ZipFile(download_saa(force=force))
    name, geo_col = (
        (SAA_DEP_XLSX, "LIB_DEP") if level == "dep" else (SAA_REG_XLSX, "LIB_REG2")
    )
    raw = pd.read_excel(
        io.BytesIO(zf.read(name)), sheet_name="COP", skiprows=5, dtype=str, engine="openpyxl"
    )
    raw = raw[raw[geo_col].notna()].copy()
    raw["geo_code"] = raw[geo_col].str.split(" - ").str[0].str.strip()
    raw["geo_name"] = raw[geo_col].str.split(" - ", n=1).str[1].str.strip()
    raw["saa_code"] = raw["LIB_SAA"].str.split(" - ").str[0].str.strip()
    raw["crop"] = raw["saa_code"].map(SAA_CROP_CODES)
    raw = raw[raw["crop"].notna()]
    # Agreste's own per-series quality flag, carried through verbatim rather than
    # interpreted: the workbook defines the codes only by reference to a methodology
    # page that currently 404s, so this module does not claim to know what 1, 2, 3 and
    # NC mean. It is kept so a consumer can report the mix instead of implying every
    # published figure is equally firm. Values observed: 1, 2, 3, NC, blank.
    raw["quality_status"] = raw.get("STATUT_QUALITE", pd.Series(index=raw.index)).fillna("")

    value_cols = [c for c in raw.columns if re.fullmatch(r"(SURF|REND|PROD)_\d{4}", str(c))]
    long = raw.melt(
        id_vars=["geo_code", "geo_name", "crop", "quality_status"],
        value_vars=value_cols,
        var_name="var",
        value_name="value",
    )
    long[["measure", "year"]] = long["var"].str.split("_", expand=True)
    long["year"] = long["year"].astype(int)
    # Agreste stores every number as text in this workbook.
    long["value"] = pd.to_numeric(long["value"], errors="coerce")

    wide = (
        long.pivot_table(
            index=["geo_code", "geo_name", "crop", "quality_status", "year"],
            columns="measure",
            values="value",
            aggfunc="first",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    wide = wide.rename(columns={"SURF": "area_ha", "PROD": "prod_q"})
    wide["yield_t_ha"] = wide["REND"] / 10.0  # published in quintal/ha
    wide["prod_t"] = wide["prod_q"] / 10.0
    wide = wide.drop(columns=["REND", "prod_q"])
    # area_ha == 0 is exactly equivalent to "not grown, yield blank" in this file.
    if require_yield:
        wide = wide[(wide["area_ha"].fillna(0) > 0) & wide["yield_t_ha"].notna()]
    else:
        wide = wide[wide["area_ha"].notna()]
    # 2025 is flagged provisional in the workbook header.
    wide = wide[wide["year"] <= 2024]
    wide["dept_code"] = wide["geo_code"].str.lstrip("0").str.zfill(2)
    return wide.sort_values(["dept_code", "crop", "year"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Legume rotation pressure, derived from the SAA area series itself.
# --------------------------------------------------------------------------- #
# The crop family IGN RPG records as "proteagineux / legumineuses a graines" in its
# per-PARCEL history. Agreste has no parcel-level equivalent, so this is the closest
# honest proxy the TRAINING data can support: the department's own historical legume
# footprint, not an individual farmer's rotation.
LEGUME_CROPS = ("field_pea", "fava_bean", "green_lentil", "chickpea", "soybean")


def load_legume_pressure(force: bool = False) -> pd.DataFrame:
    """Department-year legume area share, lagged, from the Agreste SAA series.

    This exists to put the "crop history" concept IGN RPG captures at parcel level
    into the TRAINED yield model, using a signal the training data can actually
    support. Agreste records no parcel-level rotation history, so a department's
    own area-share time series is used as a macro-scale proxy for the regional
    disease-pressure and soil-legacy dynamics that an individual field's rotation
    history drives at the parcel scale. Live IGN RPG history stays the authority for
    the parcel-specific hard agronomic gate (Terres Inovia return intervals in
    agronomy.py); this is a complementary, continuous, LEARNED signal at the grain
    the Agreste labels actually live at.

    Only LAGGED values enter the model (year-1, and the year-2..year-4 average).
    The current year's own legume share is deliberately excluded: it is contemporary
    with the yield label being predicted and has no claim to have caused it.
    """
    saa = load_saa("dep", force=force)
    # Total area across every crop this project maps in the COP sheet, as the
    # denominator. It understates true arable area (oats, triticale, rye and a few
    # others are published but not mapped), but it is applied identically everywhere,
    # so the ratio stays a consistent, comparable proxy across departments and years.
    total = saa.groupby(["dept_code", "year"])["area_ha"].sum().rename("total_area_ha")
    legume = (
        saa[saa["crop"].isin(LEGUME_CROPS)]
        .groupby(["dept_code", "year"])["area_ha"]
        .sum()
        .rename("legume_area_ha")
    )
    panel = pd.concat([total, legume], axis=1).fillna({"legume_area_ha": 0.0}).reset_index()
    panel["legume_share"] = (panel["legume_area_ha"] / panel["total_area_ha"]).clip(0.0, 1.0)

    # Reindex every department onto the FULL observed year range before shifting, so
    # a department missing a single year (none do in practice, since wheat alone is
    # grown nearly everywhere, but this makes that an explicit guarantee rather than
    # an assumption) cannot silently pull a non-adjacent year into its "lag 1".
    years = range(int(panel["year"].min()), int(panel["year"].max()) + 1)
    full_index = pd.MultiIndex.from_product(
        [sorted(panel["dept_code"].unique()), years], names=["dept_code", "year"]
    )
    dense = (
        panel.set_index(["dept_code", "year"])["legume_share"]
        .reindex(full_index)
        .reset_index()
        .sort_values(["dept_code", "year"])
    )

    g = dense.groupby("dept_code")["legume_share"]
    lag1 = g.shift(1)
    lag2, lag3, lag4 = g.shift(2), g.shift(3), g.shift(4)
    lag2to4_mean = pd.concat([lag2, lag3, lag4], axis=1).mean(axis=1, skipna=True)

    dense["legume_share_lag1"] = lag1
    dense["legume_share_lag2to4_mean"] = lag2to4_mean

    # A department's own long-run mean legume share is the least-wrong fill for the
    # handful of early-series rows (2010-2011) that have no 1-4 years of prior
    # Agreste history to look back on. Falling back to NaN would drop those rows
    # from training for a reason that has nothing to do with weather or soil.
    dept_mean = dense.groupby("dept_code")["legume_share"].transform("mean")
    dense["legume_share_lag1"] = dense["legume_share_lag1"].fillna(dept_mean)
    dense["legume_share_lag2to4_mean"] = dense["legume_share_lag2to4_mean"].fillna(dept_mean)

    # Drop back to only the (dept, year) rows that actually existed in Agreste; the
    # reindex above exists purely to make the shift arithmetic safe, not to invent
    # observations.
    out = panel[["dept_code", "year"]].merge(
        dense[["dept_code", "year", "legume_share_lag1", "legume_share_lag2to4_mean"]],
        on=["dept_code", "year"], how="left",
    )
    return out


# --------------------------------------------------------------------------- #
# Meteo-France - donnees climatologiques de base, mensuelles
# --------------------------------------------------------------------------- #
METEO_BASE = (
    "https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/MENS/"
    "MENSQ_{dept}_previous-1950-2024.csv.gz"
)
METEO_LATEST = (
    "https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/MENS/"
    "MENSQ_{dept}_latest-2025-2026.csv.gz"
)

# Columns we actually need. RR = monthly rainfall mm, ETP = monthly reference
# evapotranspiration mm, NBJTX30 = days with Tmax >= 30 C, NBJGELEE = frost days,
# NBJTXI20 = days with Tmax BELOW 20 C (Meteo-France uses I = inferieur, S = superieur).
METEO_COLS = [
    "NUM_POSTE", "NOM_USUEL", "LAT", "LON", "ALTI", "AAAAMM",
    "RR", "ETP", "TX", "TN", "TM", "NBJTX30", "NBJTX25", "NBJGELEE", "NBJTXI20",
]

DAYS_IN_MONTH = {1: 31, 2: 28.25, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31,
                 9: 30, 10: 31, 11: 30, 12: 31}


def download_meteo(dept: str, force: bool = False) -> Path:
    dept3 = dept.zfill(2)
    dest = METEO_DIR / f"mensq_{dept3}.csv.gz"
    if dest.exists() and not force and dest.stat().st_size > 10_000:
        return dest
    url = METEO_BASE.format(dept=dept3)
    r = requests.get(url, headers=UA, timeout=300)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def load_meteo_monthly(dept: str, force: bool = False) -> pd.DataFrame:
    path = download_meteo(dept, force=force)
    df = pd.read_csv(path, sep=";", compression="gzip", low_memory=False)
    keep = [c for c in METEO_COLS if c in df.columns]
    df = df[keep].copy()
    df["AAAAMM"] = df["AAAAMM"].astype(str).str.replace(".0", "", regex=False)
    df["year"] = df["AAAAMM"].str[:4].astype(int)
    df["month"] = df["AAAAMM"].str[4:6].astype(int)
    for c in ("RR", "ETP", "TX", "TN", "TM", "NBJTX30", "NBJTX25", "NBJGELEE", "NBJTXI20", "ALTI"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Exclude mountain stations: they are not where arable pulses are grown and they
    # drag a department's heat-stress signal down.
    if "ALTI" in df.columns:
        df = df[df["ALTI"].fillna(0) < 700]
    df["dept_code"] = dept.zfill(2)
    return df
