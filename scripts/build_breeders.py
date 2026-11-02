"""Build the neighbouring-livestock-holding directory the fallback contract matches against.

## What is real here, and what is not

The fear this addresses is specific: a farmer will not sow a food-grade pulse if a wet
July turns the whole lot into animal feed at a loss. The answer the product gives is
that a downgraded high-protein lot is worth far more to a livestock holding 20 km away
than it is on the commodity feed market, because that holding is otherwise buying
imported South American soybean meal. To show that, the engine needs somewhere to send
the lot.

There is no open national register of livestock holdings with locations and herd sizes.
So:

* REAL: the LOCATIONS. Every holding sits on an actual IGN commune centroid in one of
  the 42 departments this project covers, so every distance the matcher reports is a
  real distance between real places.
* REAL, as a proxy: HOW MANY holdings each department gets. It is scaled by the share
  of each department's cadastral area that is NOT in the Agreste COP sheet - cereals,
  oilseeds and grain legumes. Land that is neither arable COP nor town is overwhelmingly
  grass and forage in these departments, so a department with a low COP share is a
  livestock department. Both halves of that ratio are measured.
* ILLUSTRATIVE: the individual holdings. Names are generated, and herd type and herd
  size are drawn from published French averages for that herd type with a fixed seed.
  No real farm is being described.

That is the same standard `buyers.json` is held to, and the UI labels it the same way.
A cooperative deploying this would drop in its own livestock member list, and nothing
about the matching logic would change.

Run: python scripts/build_breeders.py
Reads: data/processed/communes.json, Agreste SAA (via build_departments helpers)
Writes: backend/app/refdata/breeders.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_departments import (  # noqa: E402
    AREA_YEARS,
    SAA_TOTAL_CEREALS,
    SAA_TOTAL_LEGUMES,
    SAA_TOTAL_OILSEED,
    load_cop_areas,
)

COMMUNES = ROOT / "data" / "processed" / "communes.json"
OUT = ROOT / "backend" / "app" / "refdata" / "breeders.json"

SEED = 20260131

# Published French reference figures per herd type. `meal_t_per_ugb_yr` is purchased
# protein-concentrate demand, which is what a pulse actually displaces - not total
# ration, most of which is home-grown forage.
HERD_TYPES = {
    "dairy_cattle": {
        "label_fr": "Bovins lait",
        "ugb_mean": 78, "ugb_sd": 34, "ugb_min": 25,
        "meal_t_per_ugb_yr": 0.34,
        "max_pulse_share_of_concentrate": 0.30,
        "note": "Ruminant. Tolerates raw pulses well; the binding limit is ration protein balance, not anti-nutritional factors.",
    },
    "beef_cattle": {
        "label_fr": "Bovins viande",
        "ugb_mean": 92, "ugb_sd": 41, "ugb_min": 30,
        "meal_t_per_ugb_yr": 0.19,
        "max_pulse_share_of_concentrate": 0.35,
        "note": "Ruminant, lowest concentrate demand per head, so a large herd is needed to absorb a lot.",
    },
    "sheep": {
        "label_fr": "Ovins",
        "ugb_mean": 44, "ugb_sd": 22, "ugb_min": 15,
        "meal_t_per_ugb_yr": 0.14,
        "max_pulse_share_of_concentrate": 0.30,
        "note": "Ruminant. Small absolute demand; useful for small downgraded lots.",
    },
    "pigs": {
        "label_fr": "Porcins",
        "ugb_mean": 61, "ugb_sd": 28, "ugb_min": 20,
        "meal_t_per_ugb_yr": 0.58,
        "max_pulse_share_of_concentrate": 0.22,
        "note": "Monogastric, high concentrate demand but capped share: raw pulses carry anti-nutritional factors and need inclusion limits.",
    },
    "poultry": {
        "label_fr": "Volailles",
        "ugb_mean": 38, "ugb_sd": 18, "ugb_min": 12,
        "meal_t_per_ugb_yr": 0.95,
        "max_pulse_share_of_concentrate": 0.15,
        "note": "Monogastric, highest concentrate demand per UGB and the tightest inclusion limit. Also the biggest non-GMO soy buyer, so the substitution is most valuable here.",
    },
}

# Herd-type mix by department, as weights. Coarse regional orientation: dairy and beef
# in the north-east and the Massif margins, poultry and pigs in the south-west and the
# west where the non-GMO soy trade actually sits.
MIX_BY_REGION = {
    "FRE1": {"dairy_cattle": 0.40, "beef_cattle": 0.25, "pigs": 0.20, "poultry": 0.10, "sheep": 0.05},
    "FRD1": {"dairy_cattle": 0.55, "beef_cattle": 0.25, "pigs": 0.10, "poultry": 0.05, "sheep": 0.05},
    "FR10": {"dairy_cattle": 0.30, "beef_cattle": 0.35, "sheep": 0.20, "poultry": 0.10, "pigs": 0.05},
    "FRB0": {"dairy_cattle": 0.25, "beef_cattle": 0.35, "sheep": 0.20, "poultry": 0.15, "pigs": 0.05},
    "FRC1": {"dairy_cattle": 0.35, "beef_cattle": 0.40, "sheep": 0.10, "poultry": 0.10, "pigs": 0.05},
    "FRF2": {"dairy_cattle": 0.45, "beef_cattle": 0.30, "sheep": 0.10, "poultry": 0.10, "pigs": 0.05},
    "FRG0": {"dairy_cattle": 0.35, "beef_cattle": 0.25, "poultry": 0.25, "pigs": 0.10, "sheep": 0.05},
    "FRI1": {"dairy_cattle": 0.20, "beef_cattle": 0.30, "poultry": 0.30, "pigs": 0.10, "sheep": 0.10},
    "FRJ2": {"dairy_cattle": 0.15, "beef_cattle": 0.25, "poultry": 0.30, "sheep": 0.25, "pigs": 0.05},
    "FRK2": {"dairy_cattle": 0.40, "beef_cattle": 0.30, "sheep": 0.15, "poultry": 0.10, "pigs": 0.05},
}
DEFAULT_MIX = {"dairy_cattle": 0.35, "beef_cattle": 0.30, "sheep": 0.15, "poultry": 0.15, "pigs": 0.05}

# One holding per this many hectares of non-COP cadastral land, tuned to put roughly
# 1,200 holdings across the 42 departments: enough that a clicked parcel almost always
# has a neighbour inside the 25 km radius, few enough that the file stays readable.
HA_PER_HOLDING = 11000.0
MAX_PER_DEPT = 60
MIN_PER_DEPT = 4

NAME_PREFIX = ["GAEC", "EARL", "SCEA", "Ferme", "Elevage"]


def main() -> int:
    if not COMMUNES.exists():
        print(f"Missing {COMMUNES}. Run scripts/build_communes.py first.")
        return 1

    depts_ref = json.loads(
        (ROOT / "backend" / "app" / "refdata" / "departments.json").read_text(encoding="utf-8")
    )
    communes = json.loads(COMMUNES.read_text(encoding="utf-8"))["communes"]

    cop = load_cop_areas()
    recent = cop[cop["year"].isin(AREA_YEARS)].copy()
    recent["cop"] = (
        recent[SAA_TOTAL_CEREALS] + recent[SAA_TOTAL_OILSEED] + recent[SAA_TOTAL_LEGUMES]
    )
    cop_by_dept = recent.groupby("dept_code")["cop"].mean().to_dict()

    rng = np.random.default_rng(SEED)
    by_dept: dict[str, list[dict]] = {}
    for c in communes:
        by_dept.setdefault(c["dept"], []).append(c)

    rows: list[dict] = []
    for dept in sorted(by_dept):
        if dept not in depts_ref:
            continue
        pool = by_dept[dept]
        cadastral = float(sum(c["cadastral_ha"] for c in pool))
        non_cop = max(cadastral - float(cop_by_dept.get(dept, 0.0)), 0.0)
        n = int(np.clip(round(non_cop / HA_PER_HOLDING), MIN_PER_DEPT, MAX_PER_DEPT))

        # Rural communes only: small population, and above-median land area for the
        # department, which is where livestock holdings actually are.
        med_ha = float(np.median([c["cadastral_ha"] for c in pool]))
        rural = [
            c for c in pool
            if 80 <= (c.get("population") or 0) <= 2500 and c["cadastral_ha"] >= med_ha
        ] or pool
        pick = rng.choice(len(rural), size=min(n, len(rural)), replace=False)

        mix = MIX_BY_REGION.get(depts_ref[dept].get("region_code"), DEFAULT_MIX)
        types = list(mix)
        probs = np.array([mix[t] for t in types], dtype=float)
        probs = probs / probs.sum()

        for seq, pi in enumerate(sorted(pick.tolist()), 1):
            c = rural[pi]
            herd = str(rng.choice(types, p=probs))
            spec = HERD_TYPES[herd]
            ugb = int(max(spec["ugb_min"], round(rng.normal(spec["ugb_mean"], spec["ugb_sd"]))))
            meal_t = ugb * spec["meal_t_per_ugb_yr"]
            rows.append({
                "breeder_id": f"B-{dept}-{seq:03d}",
                "name": f"{NAME_PREFIX[seq % len(NAME_PREFIX)]} de {c['name']}",
                "dept": dept,
                "commune": c["name"],
                "insee": c["insee"],
                "location": [c["lon"], c["lat"]],
                "herd_type": herd,
                "ugb": ugb,
                "annual_protein_meal_demand_t": round(meal_t, 1),
                "max_pulse_intake_t": round(meal_t * spec["max_pulse_share_of_concentrate"], 1),
                "currently_buys_non_gmo_soy": bool(rng.random() < 0.55),
            })

    payload = {
        "_meta": {
            "description": (
                "Neighbouring livestock holdings a downgraded food-grade pulse lot can be "
                "placed with, as a direct local replacement for imported South American "
                "soybean meal. This is the counterparty side of the fallback contract that "
                "turns the farmer's worst case from a loss into a floor."
            ),
            "status": "ILLUSTRATIVE DIRECTORY, REAL GEOGRAPHY",
            "what_is_real": (
                "Locations are actual IGN ADMINEXPRESS commune centroids, so every "
                "distance reported by the matcher is a real distance between real places. "
                "The NUMBER of holdings per department is scaled by the share of that "
                "department's cadastral area that is not in the Agreste COP sheet, which "
                "is a measured proxy for its grass and forage area."
            ),
            "what_is_not_real": (
                "Individual holdings are generated. Names are constructed, and herd type "
                "and herd size are drawn from published French per-herd-type averages with "
                "a fixed seed. No real farm is described. A cooperative deploying this "
                "would substitute its own livestock member list; the matching logic is "
                "unchanged by that substitution."
            ),
            "seed": SEED,
            "n_holdings": len(rows),
            "herd_type_reference": HERD_TYPES,
            "concentrate_definition": (
                "annual_protein_meal_demand_t is PURCHASED protein concentrate, which is "
                "what a pulse displaces. It is not total ration: most of a ruminant ration "
                "is home-grown forage and is not addressable."
            ),
            "max_pulse_intake_note": (
                "Capped by herd type. Raw pulses carry anti-nutritional factors - trypsin "
                "inhibitors, tannins, vicine in fava bean - so monogastric inclusion is "
                "limited to 15-22 percent of concentrate and ruminants to about 30-35 "
                "percent. A lot larger than the cap cannot all be placed with one holding, "
                "and the matcher says so instead of pretending otherwise."
            ),
        },
        "matching": {
            "max_haul_km": 25.0,
            "max_haul_km_note": (
                "Beyond roughly 25 km of road distance the haulage on a low-value feed lot "
                "eats the premium the breeder is paying over the commodity feed price, and "
                "the trade stops making sense for either party."
            ),
            "farmer_share_of_surplus": 0.55,
            "farmer_share_note": (
                "The pulse is worth more to the breeder than the feed spot price, because "
                "it replaces purchased soybean meal AND purchased cereal and avoids haulage "
                "and trader margin on both. That surplus has to be split. 0.55 to the "
                "farmer is a negotiating assumption, stated so it can be argued with: the "
                "engine reports both parties' side of the trade so neither is hidden."
            ),
        },
        "breeders": rows,
    }

    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    from collections import Counter

    print(f"Wrote {len(rows)} holdings to {OUT}")
    print("  by herd type:", dict(Counter(r["herd_type"] for r in rows)))
    print(f"  departments: {len({r['dept'] for r in rows})}")
    print(f"  total addressable pulse intake: {sum(r['max_pulse_intake_t'] for r in rows):,.0f} t/yr")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
