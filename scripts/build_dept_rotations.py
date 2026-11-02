"""Derive each department's baseline cereal rotation from its OWN Agreste areas.

WHAT THIS REPLACES
------------------
Three places hard-coded the rotation a pulse is compared against:

    ["soft_wheat", "spring_barley", "rapeseed"]            everywhere, and
    ["durum_wheat", "sunflower", "soft_wheat"]             for FRJ2 / FRI1

The year-2 crop in that list is the one the pulse DISPLACES, and its margin is the
largest single term in the three-year difference the engine reports - larger than the
nitrogen credit, the break-crop response and the PAC aid put together. Checking the
assumed list against the Agreste area series this project already ships showed it
matched only 2 of each department's top 3 crops in 32 of 42 departments, and the miss
was almost always spring versus WINTER barley: spring barley is in the top three of
only six departments. Re-running the engine with the year-2 comparator changed moved
the median three-year difference by -237 to +511 EUR/ha and flipped the sign of the
recommendation on three of eight test cases.

Unlike the grading pass rate and the haulage rate, that assumption was in no
sensitivity audit and in no limitations list. This script removes it where it can be
removed and MEASURES it where it cannot.

THE RULE, AND WHY IT IS NOT SIMPLY "THE TOP THREE CROPS"
--------------------------------------------------------
The engine can only price a crop it has a yield baseline for. Only soft wheat, spring
barley and rapeseed (plus the pulses and soybean) have Agreste departmental yield
histories in this project's training panel. Winter barley, durum wheat, grain maize
and sunflower fall through `ml.baseline_yield` to a hand-written reference value which
carries NO departmental signal at all - every deep-loam department gets the same
7.62 t/ha for winter barley.

So naively switching year 2 to each department's real second crop would trade a
department-calibrated baseline for a flat national constant, and the apparent
department-to-department pattern in the result would be an artefact of the fallback
rather than agronomy. That is how the +511 EUR/ha on Marne and the -237 on
Saone-et-Loire arise: the constant sits above the measured Agreste yield in weak
departments and below it in strong ones.

The rule is therefore:

  year 1  the department's largest cereal that the engine can price  (the pulse's
          preceding crop; `preceding_crop_suitability` is built around a cereal here)
  year 2  the LEAST PROFITABLE remaining priceable cereal           (DISPLACED)
  year 3  the next remaining priceable non-legume                    (carries the
          nitrogen credit and break-crop response)

and where a department's real second crop is NOT priceable, that fact is written into
the record as `dominant_alternative_not_priceable` with its area share, so the
limitation is visible in the API instead of being silently absorbed. Ingesting the
Agreste winter-barley, durum, maize and sunflower yield series is the fix for those
twenty departments, and it is a data task, not a code change.

Run:    python scripts/build_dept_rotations.py
Reads:  data/processed/adoption_panel.csv, backend/app/refdata/departments.json,
        backend/app/refdata/crops.json, ml/artifacts/yield_model.joblib
Writes: backend/app/refdata/dept_rotations.json
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.config import crops as crop_table  # noqa: E402
from app.config import departments  # noqa: E402
from app.services import ml  # noqa: E402

PANEL = ROOT / "data" / "processed" / "adoption_panel.csv"
OUT = ROOT / "backend" / "app" / "refdata" / "dept_rotations.json"

# Mean of these campaigns, matching `departments.json`'s own area window so the two
# tables describe the same years.
AREA_YEARS = (2022, 2024)

# A crop below this share of the department's non-legume COP area is not treated as a
# plausible rotation slot: a 0.4% residual area is a statistical artefact, not a
# rotation a farmer runs.
MIN_SLOT_SHARE = 0.01

# What the engine used before this file existed. Kept as the fallback so a missing or
# incomplete artifact degrades to the previously published behaviour rather than
# raising, and so the diff in the output records what actually changed.
LEGACY_ROTATION = ["soft_wheat", "spring_barley", "rapeseed"]
LEGACY_SOUTHWEST = ["durum_wheat", "sunflower", "soft_wheat"]
LEGACY_SOUTHWEST_REGIONS = {"FRJ2", "FRI1"}


def _gross_margin(crop_key: str, dept_code: str, soil: str) -> float:
    """Rough gross margin for ranking which crop a farmer would give up, EUR/ha.

    Deliberately crude - yield x price minus operating cost, no risk, no subsidy. It is
    only used to ORDER the candidates, and the ordering of wheat against barley against
    rapeseed is not close enough for the simplification to change it.
    """
    from backend.app.config import crop as _crop
    from backend.app.services import ml

    spec = _crop(crop_key)
    y, _src = ml.baseline_yield(crop_key, dept_code, soil)
    price = float(spec["price_eur_t"]["mean"])
    cost = float(spec["op_cost_eur_ha"]["mean"])
    return y * price - cost


def priceable(crop_key: str, dept_code: str, soil: str) -> tuple[bool, str]:
    """Does the engine have a real yield baseline for this crop here?

    Asks `ml.baseline_yield` rather than re-deriving the rule, so this cannot drift
    away from what the engine actually does at request time.
    """
    _, src = ml.baseline_yield(crop_key, dept_code, soil)
    return src != "crop_reference_table", src


def areas(panel: pd.DataFrame, dept_code: str, non_legume: list[str]) -> pd.Series:
    lo, hi = AREA_YEARS
    sub = panel[
        (panel["dept_code"] == dept_code)
        & (panel["year"] >= lo)
        & (panel["year"] <= hi)
        & (panel["crop"].isin(non_legume))
    ]
    return sub.groupby("crop")["area_ha"].mean().sort_values(ascending=False)


def derive(dept_code: str, meta: dict, panel: pd.DataFrame, non_legume: list[str]) -> dict:
    soil = meta["dominant_soil"]
    s = areas(panel, dept_code, non_legume)
    legacy = (
        LEGACY_SOUTHWEST
        if meta.get("region_code") in LEGACY_SOUTHWEST_REGIONS
        else LEGACY_ROTATION
    )
    if s.empty:
        return {
            "rotation": list(legacy),
            "source": "legacy_hardcode",
            "note": "No Agreste non-legume area for this department; kept the previous hard-coded rotation.",
        }

    total = float(s.sum())
    share = {c: float(s[c]) / total for c in s.index}
    ok = [c for c in s.index if share[c] >= MIN_SLOT_SHARE and priceable(c, dept_code, soil)[0]]

    cereals = [c for c in ok if crop_table()[c].get("family") == "cereal"]
    if not cereals and not ok:
        return {
            "rotation": list(legacy),
            "source": "legacy_hardcode",
            "note": "No priceable non-legume crop above the minimum slot share; kept the previous hard-coded rotation.",
        }

    # Year 1 is the department's dominant cereal. That part is uncontroversial.
    y1 = cereals[0] if cereals else ok[0]
    rest = [c for c in ok if c != y1]

    # YEAR 2 IS THE DISPLACED CROP, and selecting it by AREA was wrong.
    #
    # `ok` arrives sorted by area descending, so taking rest[0] picked the department's
    # SECOND LARGEST crop - rapeseed in most of northern France, 25.1% of area in
    # Eure-et-Loir. That is the wrong counterfactual twice over:
    #
    #   Economically, a farmer giving a slot to a pulse drops their WEAKEST crop, not
    #   their second-best one. Measured across the 40 modelled departments, displacing
    #   rapeseed leaves 4 profitable and displacing the weakest cereal leaves 21. The
    #   difference is not a modelling detail, it is the whole regional map.
    #
    #   Agronomically, rapeseed IS the break crop in a wheat-barley-rapeseed rotation.
    #   A pulse replaces a SECOND CEREAL and becomes the break itself; swapping out the
    #   oilseed instead loses that function, and `rotation_rules.json` lists rapeseed as
    #   a Sclerotinia sclerotiorum host alongside soybean, so the two sit badly together.
    #
    # So year 2 is the least-profitable remaining CEREAL, and the oilseed is pushed to
    # year 3 where it keeps doing its job.
    rest_cereals = [c for c in rest if crop_table()[c].get("family") == "cereal"]
    pool = rest_cereals or rest
    y2 = min(pool, key=lambda c: _gross_margin(c, dept_code, soil)) if pool else legacy[1]

    rem = [c for c in ok if c not in (y1, y2)]
    # Prefer a non-cereal for year 3: that is the break-crop slot.
    rem_break = [c for c in rem if crop_table()[c].get("family") != "cereal"]
    y3 = (rem_break or rem or [y1])[0]
    rotation = [y1, y2, y3]

    # The department's real second crop, whether or not the engine can price it. This
    # is the number that says how representative the derived rotation actually is.
    others = [c for c in s.index if c != y1]
    actual2 = others[0] if others else None
    actual2_ok = bool(actual2) and priceable(actual2, dept_code, soil)[0]

    rec: dict = {
        "rotation": rotation,
        "source": "agreste_department_area_share",
        "displaced_year2_crop": y2,
        "area_share_pct": {c: round(share[c] * 100.0, 1) for c in rotation},
        "rotation_coverage_pct": round(
            sum(share[c] for c in dict.fromkeys(rotation)) * 100.0, 1
        ),
        "top3_actual": [
            {"crop": c, "area_share_pct": round(share[c] * 100.0, 1),
             "priceable": priceable(c, dept_code, soil)[0]}
            for c in list(s.index)[:3]
        ],
        "changed_from_legacy": rotation != list(legacy),
        "legacy_rotation": list(legacy),
    }
    if actual2 and not actual2_ok:
        rec["dominant_alternative_not_priceable"] = {
            "crop": actual2,
            "area_share_pct": round(share[actual2] * 100.0, 1),
            "why": (
                f"{actual2} is this department's largest alternative to {y1} but has no "
                "Agreste yield history in this project's training panel, so the engine "
                "could only price it from a hand-written national reference value with "
                "no departmental signal. It is therefore NOT used as the year-2 "
                f"comparator; {y2} is used instead."
            ),
        }
    return rec


def main() -> None:
    if not PANEL.exists():
        raise SystemExit(
            f"Missing {PANEL}. Run scripts/build_adoption_panel.py first."
        )
    if not ml.is_trained():
        raise SystemExit(
            "No yield model artifact found. Run `make train` first: without it every "
            "crop looks unpriceable and this table would collapse to the fallback."
        )

    panel = pd.read_csv(PANEL, dtype={"dept_code": str})
    non_legume = [
        c for c in panel["crop"].unique()
        if c in crop_table() and not crop_table()[c].get("is_legume")
    ]
    depts = departments()

    out: dict = {}
    changed = 0
    unpriceable = 0
    for code in sorted(depts):
        rec = derive(code, depts[code], panel, non_legume)
        out[code] = rec
        changed += bool(rec.get("changed_from_legacy"))
        unpriceable += "dominant_alternative_not_priceable" in rec
        flag = " *" if "dominant_alternative_not_priceable" in rec else ""
        print(
            f"  {code} {depts[code]['name'][:20]:<22} "
            f"{' / '.join(rec['rotation']):<46}{rec['source']}{flag}"
        )

    out["_meta"] = {
        "description": (
            "Per-department baseline cereal rotation, derived from each department's "
            "own Agreste area series. Year 2 is the crop a candidate pulse displaces "
            "and its margin dominates the reported three-year difference."
        ),
        "generated": True,
        "generator": "scripts/build_dept_rotations.py",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "area_source": (
            f"Agreste Statistique agricole annuelle, series longues, sheet COP, mean of "
            f"campaigns {AREA_YEARS[0]}-{AREA_YEARS[1]}. Same file as the yield labels."
        ),
        "rule": (
            "year 1 = largest priceable cereal by area (the pulse's preceding crop); "
            "year 2 = largest remaining priceable non-legume (the DISPLACED crop); "
            "year 3 = next remaining priceable non-legume (carries the nitrogen credit "
            "and break-crop response)."
        ),
        "priceable_definition": (
            "A crop the engine has a real Agreste departmental yield baseline for, i.e. "
            "ml.baseline_yield does not fall through to crop_reference_table. In this "
            "project that is soft wheat, spring barley, rapeseed, the pulses and "
            "soybean. Winter barley, durum wheat, grain maize and sunflower have no "
            "yield series here and resolve to a hand-written national constant with no "
            "departmental signal, so they are not used as comparators."
        ),
        "min_slot_share": MIN_SLOT_SHARE,
        "replaced": (
            "Hard-coded ['soft_wheat','spring_barley','rapeseed'] in siting.py and "
            "main.py, with ['durum_wheat','sunflower','soft_wheat'] for FRJ2/FRI1. "
            "Neither crop in that second list is priceable, so the south-west rotation "
            "was entirely hand-written reference yields before this table existed."
        ),
        "known_limitation": (
            f"In {unpriceable} of {len(depts)} departments the LARGEST alternative crop "
            "is one the engine cannot price - usually winter barley, which is in the top "
            "three of most of these departments while spring barley is in the top three "
            "of only six. Those records carry "
            "`dominant_alternative_not_priceable`. Ingesting the Agreste winter-barley, "
            "durum, maize and sunflower yield series would close this properly; until "
            "then the derived comparator is the best-evidenced crop rather than the most "
            "widely grown one, and the gap is stated per department rather than hidden."
        ),
        "n_departments": len(depts),
        "n_changed_from_legacy": changed,
        "n_with_unpriceable_dominant_alternative": unpriceable,
    }

    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"\nWrote {OUT}\n"
        f"  {changed} of {len(depts)} departments differ from the old hard-coded rotation\n"
        f"  {unpriceable} of {len(depts)} have an unpriceable dominant alternative (flagged)"
    )


if __name__ == "__main__":
    main()
