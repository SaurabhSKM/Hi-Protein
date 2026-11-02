"""Rebuild refdata/departments.json for every department this project has data for.

Replaces a hand-written table of six departments whose arable and pulse hectares were
openly labelled "order-of-magnitude planning figures" with a generated table of 42,
whose hectares come from the Agreste SAA departmental area series - the same file that
supplies this project's yield labels - and whose centroids come from IGN commune
geometry.

Three consequences worth being explicit about:

1. The regional view stops being a six-point sketch and becomes a 42-department
   surface, every point of which the yield model can actually predict for, because the
   department list IS the list of departments with Meteo-France weather.

2. `arable_ha` uses Agreste's OWN subtotal rows for the whole COP sheet - all cereals
   (row 27), all oilseeds (row 36) and all grain legumes (row 46) - not the eight crops
   this project happens to model. Summing only the modelled crops was tried first and
   is badly wrong in maize and sunflower departments: it put Pyrenees-Atlantiques at
   28,200 ha of arable land and therefore at a 38 percent pulse share, which would have
   shown a maize department as having already beaten the 2030 target. Using Agreste's
   subtotals keeps the denominator complete. It is still not total UAA: silage maize,
   root crops, potatoes and fodder are outside this sheet.

3. `pulse_ha` is Agreste row 46, "total proteagineux et legumes secs cultives pour leur
   graine" - pea, fava bean, lentil, chickpea, bean, lupin and the residual categories.
   It deliberately excludes dehydrated alfalfa and temporary grassland, which were more
   than half the 2020 baseline of the French "protein crop" target and are forage, not
   food. Measuring the food tier separately is the point of the project, so the
   denominator of the 4-percent-to-8-percent story has to be the food tier too. Soybean
   is reported separately as `soybean_ha` because Agreste classes it as an oilseed, and
   folding it into the pulse line would quietly inflate the share in the south-west.

Run: python scripts/build_departments.py
Reads: Agreste SAA zip (data/raw/agreste), data/processed/communes.json
Writes: backend/app/refdata/departments.json
"""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.sources import SAA_DEP_XLSX, download_saa  # noqa: E402

COMMUNES = ROOT / "data" / "processed" / "communes.json"
SOILS = ROOT / "backend" / "app" / "refdata" / "dept_soils.json"
OUT = ROOT / "backend" / "app" / "refdata" / "departments.json"

# Averaged over the three most recent complete campaigns rather than taken from the
# latest year alone: pulse area is volatile (a single bad pea year moves a department
# 30 percent) and a planning figure should not inherit that noise.
AREA_YEARS = (2022, 2023, 2024)

# Agreste's own subtotal rows in the COP sheet, by the stable numeric LIB_SAA prefix.
# Using the published subtotals rather than re-adding the component rows means the
# denominator cannot drift as this project's crop mapping changes.
SAA_TOTAL_CEREALS = "27"   # Total toutes cereales (incl. rice)
SAA_TOTAL_OILSEED = "36"   # Total oleagineux
SAA_TOTAL_LEGUMES = "46"   # Total proteagineux et legumes secs cultives pour leur graine
SAA_SOYBEAN = "33"         # Soja, classed by Agreste as an oilseed


def load_cop_areas() -> pd.DataFrame:
    """Department-year area for Agreste's COP subtotal rows plus soybean.

    Deliberately separate from `ml.sources.load_saa`, which filters down to the eight
    crops the yield model is trained on and drops every subtotal row. The model needs
    component crops; the regional denominator needs the totals.
    """
    zf = zipfile.ZipFile(download_saa())
    raw = pd.read_excel(
        io.BytesIO(zf.read(SAA_DEP_XLSX)), sheet_name="COP", skiprows=5,
        dtype=str, engine="openpyxl",
    )
    raw = raw[raw["LIB_DEP"].notna()].copy()
    raw["dept_code"] = raw["LIB_DEP"].str.split(" - ").str[0].str.strip().str.lstrip("0").str.zfill(2)
    raw["saa_code"] = raw["LIB_SAA"].str.split(" - ").str[0].str.strip()
    wanted = {SAA_TOTAL_CEREALS, SAA_TOTAL_OILSEED, SAA_TOTAL_LEGUMES, SAA_SOYBEAN}
    raw = raw[raw["saa_code"].isin(wanted)]

    surf_cols = [c for c in raw.columns if re.fullmatch(r"SURF_\d{4}", str(c))]
    long = raw.melt(
        id_vars=["dept_code", "saa_code"], value_vars=surf_cols,
        var_name="var", value_name="area_ha",
    )
    long["year"] = long["var"].str[-4:].astype(int)
    long["area_ha"] = pd.to_numeric(long["area_ha"], errors="coerce").fillna(0.0)
    return long.pivot_table(
        index=["dept_code", "year"], columns="saa_code", values="area_ha", aggfunc="first"
    ).fillna(0.0).reset_index()

# Department -> (official name, region code, region name). Region codes follow the
# convention already established in buyers.json and food_demand.json: a NUTS2
# identifier used as the stand-in for the current 13-region administrative map. That
# is an inherited inconsistency, not a new one - NUTS2 for France is still the pre-2016
# 22-region split - and it is kept because buyers' region_focus lists are written in it.
DEPT_META = {
    "01": ("Ain", "FRK2", "Auvergne-Rhone-Alpes"),
    "02": ("Aisne", "FRE1", "Hauts-de-France"),
    "10": ("Aube", "FRF2", "Grand Est"),
    "11": ("Aude", "FRJ2", "Occitanie"),
    "14": ("Calvados", "FRD1", "Normandie"),
    "16": ("Charente", "FRI1", "Nouvelle-Aquitaine"),
    "17": ("Charente-Maritime", "FRI1", "Nouvelle-Aquitaine"),
    "18": ("Cher", "FRB0", "Centre-Val de Loire"),
    "21": ("Cote-d'Or", "FRC1", "Bourgogne-Franche-Comte"),
    "27": ("Eure", "FRD1", "Normandie"),
    "28": ("Eure-et-Loir", "FRB0", "Centre-Val de Loire"),
    "31": ("Haute-Garonne", "FRJ2", "Occitanie"),
    "32": ("Gers", "FRJ2", "Occitanie"),
    "36": ("Indre", "FRB0", "Centre-Val de Loire"),
    "37": ("Indre-et-Loire", "FRB0", "Centre-Val de Loire"),
    "38": ("Isere", "FRK2", "Auvergne-Rhone-Alpes"),
    "39": ("Jura", "FRC1", "Bourgogne-Franche-Comte"),
    "40": ("Landes", "FRI1", "Nouvelle-Aquitaine"),
    "41": ("Loir-et-Cher", "FRB0", "Centre-Val de Loire"),
    "45": ("Loiret", "FRB0", "Centre-Val de Loire"),
    "47": ("Lot-et-Garonne", "FRI1", "Nouvelle-Aquitaine"),
    "51": ("Marne", "FRF2", "Grand Est"),
    "52": ("Haute-Marne", "FRF2", "Grand Est"),
    "54": ("Meurthe-et-Moselle", "FRF2", "Grand Est"),
    "55": ("Meuse", "FRF2", "Grand Est"),
    "58": ("Nievre", "FRC1", "Bourgogne-Franche-Comte"),
    "60": ("Oise", "FRE1", "Hauts-de-France"),
    "64": ("Pyrenees-Atlantiques", "FRI1", "Nouvelle-Aquitaine"),
    "65": ("Hautes-Pyrenees", "FRJ2", "Occitanie"),
    "68": ("Haut-Rhin", "FRF2", "Grand Est"),
    "70": ("Haute-Saone", "FRC1", "Bourgogne-Franche-Comte"),
    "71": ("Saone-et-Loire", "FRC1", "Bourgogne-Franche-Comte"),
    "77": ("Seine-et-Marne", "FR10", "Ile-de-France"),
    "78": ("Yvelines", "FR10", "Ile-de-France"),
    "79": ("Deux-Sevres", "FRI1", "Nouvelle-Aquitaine"),
    "80": ("Somme", "FRE1", "Hauts-de-France"),
    "81": ("Tarn", "FRJ2", "Occitanie"),
    "82": ("Tarn-et-Garonne", "FRJ2", "Occitanie"),
    "85": ("Vendee", "FRG0", "Pays de la Loire"),
    "86": ("Vienne", "FRI1", "Nouvelle-Aquitaine"),
    "89": ("Yonne", "FRC1", "Bourgogne-Franche-Comte"),
    "91": ("Essonne", "FR10", "Ile-de-France"),
}

# Notes only for the departments the demo opens on. A generated note for all 42 would
# be filler, and an empty note is more honest than an invented one.
NOTES = {
    "28": "Beauce. High-potential deep loam, intensive wheat-barley-rapeseed rotations.",
    "21": "Plateaux calcaires. Shallow stony soils, strong existing lentil tradition.",
    "32": "Coteaux de Gascogne. Clay-loam hillsides, durum wheat and sunflower base.",
    "45": "Mixed Beauce and Sologne margins.",
    "51": "Champagne cretacee. Established protein pea area.",
    "86": "Groies. Drought-prone shallow soils favouring chickpea and lentil over pea.",
}


def main() -> int:
    if not COMMUNES.exists():
        print(f"Missing {COMMUNES}. Run scripts/build_communes.py first.")
        return 1

    communes = json.loads(COMMUNES.read_text(encoding="utf-8"))["communes"]
    soils = {k: v for k, v in json.loads(SOILS.read_text(encoding="utf-8")).items()
             if not k.startswith("_")}

    cdf = pd.DataFrame(communes)
    # Cadastral-area-weighted department centroid. Weighting matters: an unweighted
    # mean of commune centroids is pulled towards whichever part of the department
    # happens to be carved into many small communes, which is usually the towns.
    cdf["wlon"] = cdf["lon"] * cdf["cadastral_ha"]
    cdf["wlat"] = cdf["lat"] * cdf["cadastral_ha"]
    cent = cdf.groupby("dept").agg(
        wlon=("wlon", "sum"), wlat=("wlat", "sum"), w=("cadastral_ha", "sum"),
        n_communes=("insee", "count"),
    )
    cent["lon"] = cent["wlon"] / cent["w"]
    cent["lat"] = cent["wlat"] / cent["w"]

    cop = load_cop_areas()
    recent = cop[cop["year"].isin(AREA_YEARS)].copy()
    recent["arable"] = (
        recent[SAA_TOTAL_CEREALS] + recent[SAA_TOTAL_OILSEED] + recent[SAA_TOTAL_LEGUMES]
    )
    agg = recent.groupby("dept_code").mean(numeric_only=True)
    arable = agg["arable"]
    pulse = agg[SAA_TOTAL_LEGUMES]
    soy = agg[SAA_SOYBEAN]

    out: dict = {
        "_meta": {
            "description": (
                "Every department this project has Meteo-France weather for, with its "
                "region, dominant arable soil archetype, mapped arable area and current "
                "food-tier pulse area. Generated by scripts/build_departments.py."
            ),
            "generated": True,
            "generator": "scripts/build_departments.py",
            "area_source": (
                "Agreste SAA departmental area series, mean of campaigns "
                f"{AREA_YEARS[0]}-{AREA_YEARS[-1]}."
            ),
            "arable_ha_definition": (
                "Agreste COP subtotals summed: all cereals (LIB_SAA 27) + all oilseeds "
                "(36) + all grain legumes (46). Uses the published subtotals, not a "
                "re-addition of the crops this project models, so the denominator cannot "
                "drift with the crop mapping. Still not total UAA: silage maize, root "
                "crops, potatoes and fodder sit outside this sheet."
            ),
            "pulse_ha_definition": (
                "Agreste LIB_SAA row 46, total proteagineux et legumes secs cultives pour "
                "leur graine: pea, fava bean, lentil, chickpea, dry bean, lupin and "
                "residual categories. Excludes dehydrated alfalfa and temporary grassland, "
                "which were more than half the 2020 baseline of the French protein-crop "
                "target and are forage, not food. Soybean is reported separately in "
                "soybean_ha because Agreste classes it as an oilseed."
            ),
            "centroid_source": (
                "Cadastral-area-weighted mean of IGN ADMINEXPRESS commune centroids."
            ),
            "removed_fields_note": (
                "No per-department irrigation share is emitted. An earlier version wrote "
                "42 hand-written percentages here with no source; nothing consumed them, "
                "and an undefendable number in reference data is worse than none. "
                "Irrigation enters the engine where it is actually evidenced, in "
                "refdata/irrigation.json, which decomposes Agreste's blended irrigated "
                "and rain-fed yields using national irrigated-area shares per crop."
            ),
            "national_target": {
                "current_pulse_share_pct": 4.0,
                "target_pulse_share_pct": 8.0,
                "target_year": 2030,
            },
        }
    }

    missing_area = []
    for code, (name, rcode, rname) in sorted(DEPT_META.items()):
        if code not in cent.index:
            print(f"  skip {code}: no commune geometry")
            continue
        a = float(arable.get(code, 0.0))
        p = float(pulse.get(code, 0.0))
        if a <= 0:
            missing_area.append(code)
            continue
        out[code] = {
            "name": name,
            "region_code": rcode,
            "region_name": rname,
            "centroid": [round(float(cent.loc[code, "lon"]), 3),
                         round(float(cent.loc[code, "lat"]), 3)],
            "dominant_soil": soils.get(code, "clay_loam"),
            "arable_ha": int(round(a, -2)),
            "pulse_ha": int(round(p)),
            "soybean_ha": int(round(float(soy.get(code, 0.0)))),
            "pulse_share_pct": round(100.0 * p / a, 3),
            "n_communes": int(cent.loc[code, "n_communes"]),
            "notes": NOTES.get(code),
        }

    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n = len([k for k in out if not k.startswith("_")])
    tot_a = sum(v["arable_ha"] for k, v in out.items() if not k.startswith("_"))
    tot_p = sum(v["pulse_ha"] for k, v in out.items() if not k.startswith("_"))
    print(f"Wrote {n} departments to {OUT}")
    print(f"  mapped arable {tot_a:,} ha   food-tier pulse {tot_p:,} ha "
          f"({100.0 * tot_p / tot_a:.2f}%)")
    if missing_area:
        print(f"  no Agreste area, omitted: {missing_area}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
