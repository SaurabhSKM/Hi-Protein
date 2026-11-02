"""The zoom-in: real RPG parcels in the Beauce, every campaign 2015-2024.

WHY THIS EXISTS ALONGSIDE THE AGRESTE PANEL
-------------------------------------------
`build_adoption_panel.py` answers "did France move to pulses" at department grain for
93 departments. It cannot answer "where in the Beauce did it happen", because Agreste
publishes no sub-department data. RPG can, and only RPG can: every farmer claiming EU
subsidy declares each parcel's main crop, so the Geoplateforme WFS carries ten
campaigns of real field boundaries (2015-2024 verified present in GetCapabilities;
2010-2014 exist only as an empty `RPG.<year>:rpg_` stub and are NOT served).

One region, all ten campaigns: RPG is roughly 9.5 million polygons per campaign
nationally, and about 155,000 in this bbox.

WHAT THE HECTARES ARE
---------------------
Area is the parcel's own `surf_parc` property - the declared hectares the subsidy is
paid on - verified present on both the 2015 and the 2024 layer. Not re-derived from
polygon geometry, so these are Ministry-declared figures.

WHAT COUNTS AS A GRAIN LEGUME, AND WHY NOT THE PROJECT'S OWN CROP MAP
---------------------------------------------------------------------
The pulse measure here is taken from RPG's OWN crop groups, not from
`rpg_codes.CODE_CULTU_TO_CROP`:

    group 8   Proteagineux            (peas, favas, lupins, protein-cereal mixes)
    group 15  Legumineuses a grains   (lentil, chickpea)
    plus SOJ, which RPG files under group 7, "Autres oleagineux"

Group names and membership were read from `RPG.2023:codes_cultures`, the authoritative
table, and verified to hold in both the 2015 and the 2024 parcel extracts. The
project's crop map is built for the yield model and maps only the codes that model
needs: it sends MPC and PAG to `other_legume`, which a pulse total would then drop,
and it has no key for lupin at all. Using the official groups instead recovered 136 ha
in 2015 and 649 ha in 2024 that the crop map was leaving out. `rpg_codes` still
supplies the human-readable per-code labels.

THE RECLASSIFICATION TEST, AND WHY ALL TEN CAMPAIGNS ARE FETCHED
----------------------------------------------------------------
Comparing 2015 against 2024 alone, group 8 grows by about 6,800 ha and almost exactly
that much appears in two codes absent from the 2015 extract - PHF and PHS, the
human-food pea and bean declarations - while PPR, the animal-feed pea, falls. On two
campaigns those two facts are indistinguishable from a pure relabelling. IGN publishes
code tables only from 2022, so the 2015 code list cannot be consulted to settle it.
Fetching every intermediate campaign does settle it: a relabelling appears as a step
in one year with a mirrored fall in PPR, and genuine adoption appears as a ramp. The
per-code series is written to the artifact so the answer is visible rather than
asserted.

NO PARCEL-TO-PARCEL MATCHING IS ATTEMPTED. RPG `id_parcel` is not stable across
campaigns - the same ground can be re-declared under a different id, merged or split -
so "this field was wheat and is now lentils" cannot be supported by the ids, and
claiming it would be invention. What is reported is each cell's crop MIX over time.

Parcels are binned to a 5 km Lambert-93 grid by CENTROID, so a parcel straddling a
cell edge is counted whole in the cell holding its centroid. Against 25 square
kilometre cells and a median parcel of a few hectares that is immaterial to a share,
and it avoids implying the precision polygon clipping would only appear to add.

Run: .venv/bin/python scripts/build_rpg_change.py [--force]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.services import rpg_codes  # noqa: E402

CACHE = ROOT / "data" / "cache" / "rpg_wfs"
OUT = ROOT / "data" / "processed" / "rpg_change_beauce.json"

WFS = "https://data.geopf.fr/wfs/ows"
UA = {"User-Agent": "hiprotein-hackathon/1.0"}
PAGE = 5000
CHUNK_DEG = 0.2

REGION = "beauce"
BBOX = (1.0, 47.8, 2.6, 48.6)
YEARS = tuple(range(2015, 2025))
CELL_M = 5000.0
L93 = "EPSG:2154"
WGS84 = "EPSG:4326"

# RPG's own groups, read from RPG.2023:codes_cultures and verified against both the
# 2015 and 2024 parcel extracts.
GROUP_PROTEAGINEUX = "8"
GROUP_LEGUMINEUSES_GRAINS = "15"
PULSE_GROUPS = frozenset({GROUP_PROTEAGINEUX, GROUP_LEGUMINEUSES_GRAINS})
# Soy is a protein crop that RPG files as an oilseed, so it is named explicitly rather
# than picked up by a group.
SOY_CODES = frozenset({"SOJ"})
LENTIL_CODES = frozenset({"LEC"})
# Group 16 is "Fourrage", 107 codes of which only some are legumes, so a forage-legume
# total cannot be taken from the group. The named alfalfa, clover, sainfoin and vetch
# codes are used instead.
FORAGE_LEGUME_CODES = frozenset({
    "LUZ", "LUD", "LU5", "TRE", "SAI", "VES", "MLF", "MLC", "MLG",
})

CODES_TABLE_YEAR = 2023      # the most recent campaign that still publishes code_groupe
# Code tables are published only for these campaigns. 2022 and 2023 are both fetched
# because the DIFFERENCE between them is what proves the 2023 vocabulary change.
CODE_TABLE_YEARS = (2022, 2023, 2024)


def fetch_code_table(year: int = CODES_TABLE_YEAR, force: bool = False) -> dict[str, dict]:
    """The authoritative code -> (libelle, code_groupe, libelle_groupe) table.

    Only 2022, 2023 and 2024 publish a code table, and 2024 dropped `code_groupe`, so
    2023 is the newest vintage that carries the group names this script needs.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"rpg_{year}_codes.json"
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": f"RPG.{year}:codes_cultures",
        "COUNT": "1000", "OUTPUTFORMAT": "application/json",
    }
    r = requests.get(WFS, params=params, headers=UA, timeout=300)
    r.raise_for_status()
    table = {
        f["properties"]["code"]: f["properties"]
        for f in r.json().get("features") or []
    }
    path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    return table


def _chunks(bbox, step):
    w, s, e, n = bbox
    out, lat = [], s
    while lat < n - 1e-9:
        lon = w
        while lon < e - 1e-9:
            out.append((lon, lat, min(lon + step, e), min(lat + step, n)))
            lon += step
        lat += step
    return out


def _fetch_chunk(year: int, bbox) -> gpd.GeoDataFrame:
    feats: list[dict] = []
    start = 0
    while True:
        params = {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": f"RPG.{year}:parcelles_graphiques",
            "SRSNAME": WGS84,
            # Axis order: this server wants lon,lat for EPSG:4326 and returns zero
            # features for lat,lon without raising. Verified on both campaigns.
            "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:4326",
            "COUNT": PAGE, "STARTINDEX": start,
            "OUTPUTFORMAT": "application/json",
        }
        r = requests.get(WFS, params=params, headers=UA, timeout=300)
        r.raise_for_status()
        page = r.json().get("features") or []
        feats.extend(page)
        if len(page) < PAGE:
            break
        start += PAGE
    if not feats:
        return gpd.GeoDataFrame(
            {"code_cultu": [], "surf_parc": [], "geometry": []},
            geometry="geometry", crs=WGS84,
        )
    return gpd.GeoDataFrame.from_features(feats, crs=WGS84)


def load_year(year: int, force: bool = False) -> pd.DataFrame:
    """Every parcel in the bbox as (code_cultu, code_group, surf_parc, centroid).

    Polygons are reduced to a centroid at fetch time and discarded, so each campaign
    caches as a few megabytes rather than a few hundred.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{REGION}_{year}_parcels.parquet"
    if cache.exists() and not force:
        return pd.read_parquet(cache)

    chunks = _chunks(BBOX, CHUNK_DEG)
    frames, t0 = [], time.perf_counter()
    for i, bb in enumerate(chunks, 1):
        gdf = _fetch_chunk(year, bb)
        if len(gdf):
            cent = gdf.to_crs(L93).geometry.centroid
            frames.append(pd.DataFrame({
                "id_parcel": gdf.get("id_parcel").astype("string")
                if "id_parcel" in gdf.columns else pd.NA,
                "code_cultu": gdf.get("code_cultu").astype("string"),
                "code_group": gdf.get("code_group").astype("string")
                if "code_group" in gdf.columns else pd.NA,
                "surf_parc": pd.to_numeric(gdf.get("surf_parc"), errors="coerce"),
                "x_l93": cent.x.to_numpy(),
                "y_l93": cent.y.to_numpy(),
            }))
        if i == len(chunks):
            tot = sum(len(f) for f in frames)
            print(f"    {year}: {i}/{len(chunks)} chunks, {tot} parcels, "
                  f"{time.perf_counter() - t0:.0f}s")

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["id_parcel", "code_cultu", "code_group", "surf_parc", "x_l93", "y_l93"]
    )
    # Chunk edges return the same parcel twice when a polygon straddles them.
    if len(df):
        df = df.drop_duplicates(subset="id_parcel")
    df.to_parquet(cache, index=False)
    return df


def classify(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["surf_parc"] = d["surf_parc"].fillna(0.0)
    grp = d["code_group"].astype("string").fillna("")
    code = d["code_cultu"].astype("string").fillna("")
    d["is_pulse"] = grp.isin(PULSE_GROUPS) | code.isin(SOY_CODES)
    d["is_lentil"] = code.isin(LENTIL_CODES)
    d["is_soy"] = code.isin(SOY_CODES)
    d["is_food_pulse"] = grp.eq(GROUP_LEGUMINEUSES_GRAINS)
    d["is_forage_legume"] = code.isin(FORAGE_LEGUME_CODES)
    d["is_fallow"] = [rpg_codes.is_fallow(c) for c in code]
    return d


FLAGS = ("is_pulse", "is_lentil", "is_soy", "is_food_pulse", "is_forage_legume",
         "is_fallow")


def totals_for(d: pd.DataFrame) -> dict:
    declared = float(d["surf_parc"].sum())
    out = {
        "n_parcels": int(len(d)),
        "declared_ha": round(declared, 1),
    }
    for f in FLAGS:
        name = f[3:]
        ha = float(d.loc[d[f], "surf_parc"].sum())
        out[f"{name}_ha"] = round(ha, 1)
        out[f"{name}_share_pct"] = round(100 * ha / declared, 4) if declared else None
    out["group8_proteagineux_ha"] = round(
        float(d.loc[d["code_group"].astype("string").fillna("")
                    .eq(GROUP_PROTEAGINEUX), "surf_parc"].sum()), 1)
    out["group15_legumineuses_ha"] = round(
        float(d.loc[d["code_group"].astype("string").fillna("")
                    .eq(GROUP_LEGUMINEUSES_GRAINS), "surf_parc"].sum()), 1)
    return out


def cells_for(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    x["col"] = (x["x_l93"] // CELL_M).astype("int64")
    x["row"] = (x["y_l93"] // CELL_M).astype("int64")
    g = x.groupby(["row", "col"])
    agg = pd.DataFrame({
        "declared_ha": g["surf_parc"].sum(),
        "pulse_ha": g.apply(lambda s: s.loc[s["is_pulse"], "surf_parc"].sum(),
                            include_groups=False),
        "lentil_ha": g.apply(lambda s: s.loc[s["is_lentil"], "surf_parc"].sum(),
                             include_groups=False),
        "fallow_ha": g.apply(lambda s: s.loc[s["is_fallow"], "surf_parc"].sum(),
                             include_groups=False),
        "n_parcels": g.size(),
    })
    return agg


def vocabulary_change(tables: dict[int, dict], per_code: dict) -> dict:
    """Prove, or fail to prove, that a jump in pulse area is a code-list change.

    Three codes - PHF, PHS and FVP - are zero in this region for every campaign from
    2015 to 2022 and then appear at thousands of hectares in 2023. Adoption does not
    behave like that; a vocabulary change does. The code tables settle it: all three
    are ABSENT from RPG.2022:codes_cultures and PRESENT in RPG.2023:codes_cultures,
    so they could not have been declared before 2023 whatever farmers were growing.

    This function recomputes the comparison without those codes, which is the only
    like-for-like reading of the series across the 2023 boundary.
    """
    added_2023 = sorted(set(tables[2023]) - set(tables[2022]))
    suspects = []
    for row in per_code:
        code = row["code_cultu"]
        first = row["first_year_present"]
        if code in added_2023 and first is not None and first >= 2023:
            suspects.append({
                "code_cultu": code,
                "label": row["label"],
                "first_year_present_in_region": first,
                "absent_from_2022_code_table": True,
                "ha_in_first_year": row["ha_by_year"][str(first)],
            })
    return {
        "codes_added_in_2023_vocabulary": added_2023,
        "n_codes_added_in_2023": len(added_2023),
        "code_table_sizes": {str(y): len(tables[y]) for y in sorted(tables)},
        "pulse_codes_introduced_in_2023": suspects,
        "evidence": (
            "Each code listed above is absent from RPG.2022:codes_cultures, present in "
            "RPG.2023:codes_cultures, and records zero hectares in this region for "
            "every campaign up to 2022. It could not be declared before 2023."
        ),
        "consequence": (
            "Pulse area across the 2023 boundary is NOT comparable as published. The "
            "like-for-like figures are either 2015 to 2022, or the 2023 and 2024 "
            "totals with these codes removed - both are given in "
            "totals_by_year as *_like_for_like fields."
        ),
    }


def main() -> int:
    force = "--force" in sys.argv
    tables = {y: fetch_code_table(y, force=force) for y in CODE_TABLE_YEARS}
    table = tables[CODES_TABLE_YEAR]
    print("code tables: " + ", ".join(f"{y}={len(tables[y])}" for y in CODE_TABLE_YEARS))

    frames: dict[int, pd.DataFrame] = {}
    for y in YEARS:
        frames[y] = classify(load_year(y, force=force))

    # ---- per-campaign totals -------------------------------------------------
    totals = {str(y): totals_for(frames[y]) for y in YEARS}

    # ---- per-code series, so reclassification is visible ---------------------
    per_code: dict[str, dict[str, float]] = {}
    for y in YEARS:
        d = frames[y]
        legumes = d[d["is_pulse"]]
        for code, ha in legumes.groupby("code_cultu")["surf_parc"].sum().items():
            per_code.setdefault(str(code), {})[str(y)] = round(float(ha), 1)
    code_series = []
    for code, series in sorted(per_code.items(), key=lambda kv: -max(kv[1].values())):
        meta = table.get(code, {})
        code_series.append({
            "code_cultu": code,
            "label": meta.get("libelle") or rpg_codes.label_for(code),
            "code_groupe": meta.get("code_groupe"),
            "libelle_groupe": meta.get("libelle_groupe"),
            "ha_by_year": {str(y): series.get(str(y), 0.0) for y in YEARS},
            "first_year_present": min(
                (int(k) for k, v in series.items() if v > 0), default=None
            ),
        })

    # ---- the 2023 vocabulary break, and the like-for-like series -------------
    vocab = vocabulary_change(tables, code_series)
    new_codes = {s["code_cultu"] for s in vocab["pulse_codes_introduced_in_2023"]}
    for y in YEARS:
        d = frames[y]
        drop = d["code_cultu"].astype("string").fillna("").isin(new_codes)
        ha = float(d.loc[d["is_pulse"] & ~drop, "surf_parc"].sum())
        declared = float(d["surf_parc"].sum())
        t = totals[str(y)]
        t["pulse_ha_like_for_like"] = round(ha, 1)
        t["pulse_share_pct_like_for_like"] = (
            round(100 * ha / declared, 4) if declared else None
        )

    # ---- per-cell, first and last campaign, for the map ----------------------
    first, last = YEARS[0], YEARS[-1]
    a, b = cells_for(frames[first]), cells_for(frames[last])
    idx = a.index.union(b.index)
    a, b = a.reindex(idx).fillna(0.0), b.reindex(idx).fillna(0.0)
    pts = gpd.GeoSeries(
        gpd.points_from_xy(
            [(c + 0.5) * CELL_M for _, c in idx], [(r + 0.5) * CELL_M for r, _ in idx]
        ),
        crs=L93,
    ).to_crs(WGS84)

    cells = []
    # strict=True: pts is built from idx, so a length mismatch would mean the point
    # geometry no longer lines up with the cells it is meant to label.
    for (row, col), lon, lat in zip(idx, pts.x, pts.y, strict=True):
        d0 = float(a.loc[(row, col), "declared_ha"])
        d1 = float(b.loc[(row, col), "declared_ha"])
        p0 = float(a.loc[(row, col), "pulse_ha"])
        p1 = float(b.loc[(row, col), "pulse_ha"])
        rec = {
            "lon": round(float(lon), 4), "lat": round(float(lat), 4),
            f"declared_ha_{first}": round(d0, 1), f"declared_ha_{last}": round(d1, 1),
            f"pulse_ha_{first}": round(p0, 1), f"pulse_ha_{last}": round(p1, 1),
            f"lentil_ha_{first}": round(float(a.loc[(row, col), "lentil_ha"]), 1),
            f"lentil_ha_{last}": round(float(b.loc[(row, col), "lentil_ha"]), 1),
            f"fallow_ha_{first}": round(float(a.loc[(row, col), "fallow_ha"]), 1),
            f"fallow_ha_{last}": round(float(b.loc[(row, col), "fallow_ha"]), 1),
            f"n_parcels_{last}": int(b.loc[(row, col), "n_parcels"]),
        }
        # A cell with almost no declared farmland yields a meaningless share, so the
        # share is left null rather than computed on a handful of hectares.
        MIN_HA = 50.0
        rec[f"pulse_share_{first}"] = round(p0 / d0, 5) if d0 >= MIN_HA else None
        rec[f"pulse_share_{last}"] = round(p1 / d1, 5) if d1 >= MIN_HA else None
        rec["pulse_share_change_pp"] = (
            round(100 * (rec[f"pulse_share_{last}"] - rec[f"pulse_share_{first}"]), 3)
            if rec[f"pulse_share_{first}"] is not None
            and rec[f"pulse_share_{last}"] is not None else None
        )
        cells.append(rec)

    # ---- codes with no label in the authoritative table ----------------------
    unlabelled = {}
    for y in YEARS:
        d = frames[y]
        codes = set(d["code_cultu"].dropna().astype(str))
        miss = sorted(c for c in codes if c not in table)
        ha = float(d[d["code_cultu"].isin(miss)]["surf_parc"].sum())
        unlabelled[str(y)] = {
            "n_codes": len(miss), "codes": miss,
            "declared_ha": round(ha, 1),
            "share_of_declared_ha_pct": round(
                100 * ha / max(float(d["surf_parc"].sum()), 1e-9), 3),
        }

    payload = {
        "_meta": {
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "generator": "scripts/build_rpg_change.py",
            "region": REGION,
            "bbox_wgs84": list(BBOX),
            "years": list(YEARS),
            "source": (
                "IGN Registre Parcellaire Graphique, RPG.<year>:parcelles_graphiques "
                "for 2015-2024, via data.geopf.fr WFS 2.0.0"
            ),
            "code_table_source": f"RPG.{CODES_TABLE_YEAR}:codes_cultures ({len(table)} codes)",
            "years_available_note": (
                "GetCapabilities advertises parcelles_graphiques for 2015-2024 only; "
                "2010-2014 appear as an empty RPG.<year>:rpg_ stub. Code tables exist "
                f"for 2022-2024 and only up to {CODES_TABLE_YEAR} carry code_groupe."
            ),
            "area_basis": (
                "Declared hectares from each parcel's surf_parc property, the area the "
                "subsidy is paid on. Not re-derived from polygon geometry."
            ),
            "pulse_definition": (
                "RPG groups 8 (Proteagineux) and 15 (Legumineuses a grains), plus code "
                "SOJ which RPG files under group 7 (Autres oleagineux). Group "
                "membership read from the authoritative code table and verified "
                "present in both the 2015 and 2024 extracts."
            ),
            "why_not_project_crop_map": (
                "rpg_codes.CODE_CULTU_TO_CROP is built for the yield model: it sends "
                "MPC and PAG to other_legume and has no lupin key, so a pulse total "
                "taken from it understates by 136 ha in 2015 and 649 ha in 2024."
            ),
            "cell_size_m": CELL_M,
            "cell_assignment": (
                "Parcels assigned whole to the 5 km Lambert-93 cell containing their "
                "centroid; no clipping at cell edges. Cells under 50 declared ha get a "
                "null share rather than one computed on a handful of hectares."
            ),
            "no_parcel_matching": (
                "RPG id_parcel is not stable between campaigns, so no field-level "
                "before/after claim is made. Only each cell's crop mix is compared."
            ),
            "codes_without_authoritative_label": unlabelled,
        },
        "vocabulary_change_2023": vocab,
        "totals_by_year": totals,
        "pulse_code_series": code_series,
        "cells": cells,
        "cells_compare_years": [first, last],
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    print(f"\nwrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB, {len(cells)} cells)\n")
    print(f"{'year':>6} {'parcels':>9} {'declared ha':>12} {'pulse ha':>9} "
          f"{'pulse %':>8} {'like4like %':>12} {'lentil ha':>10} {'fallow %':>9}")
    for y in YEARS:
        t = totals[str(y)]
        print(f"{y:>6} {t['n_parcels']:>9,} {t['declared_ha']:>12,.0f} "
              f"{t['pulse_ha']:>9,.0f} {t['pulse_share_pct']:>8.2f} "
              f"{t['pulse_share_pct_like_for_like']:>12.2f} "
              f"{t['lentil_ha']:>10,.0f} {t['fallow_share_pct']:>9.2f}")
    print(f"\n2023 vocabulary change: {vocab['n_codes_added_in_2023']} codes added, "
          f"of which these pulse codes appear here for the first time:")
    for s in vocab["pulse_codes_introduced_in_2023"]:
        print(f"  {s['code_cultu']}  {s['ha_in_first_year']:>8,.0f} ha in "
              f"{s['first_year_present_in_region']}  {str(s['label'])[:48]}")
    print("\npulse codes by campaign (declared ha):")
    for row in code_series[:10]:
        series = " ".join(f"{row['ha_by_year'][str(y)]:>7,.0f}" for y in YEARS)
        print(f"  {row['code_cultu']:<4} {series}  {str(row['label'])[:42]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
