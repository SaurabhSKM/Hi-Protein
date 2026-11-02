"""Which cereal rotation a pulse is compared against, per department.

The year-2 crop of the baseline rotation is the one a candidate pulse DISPLACES, and
its margin is the largest single term in the three-year difference this engine reports
- larger than the nitrogen credit, the break-crop response and the PAC coupled aid put
together. Three code paths used to hard-code that crop:

    siting.py          the regional map and the siting optimiser
    main.py            /food-demand
    main.py            /climate-outlook

and so did the baked department profiles, which are built by the first of those. None
of them exposed the choice, and none of them was reachable from the UI: on those tabs
the comparator was fixed and invisible. The farmer tab is different - it has three
crop selectors - but all four of its presets carried the same hard-coded list.

`scripts/build_dept_rotations.py` replaces the constant with each department's own
Agreste area shares and writes `refdata/dept_rotations.json`. This module reads it.

WHY THE DERIVED ROTATION IS NOT JUST THE DEPARTMENT'S TOP THREE CROPS
---------------------------------------------------------------------
The engine can only price a crop it has a yield baseline for, and only soft wheat,
spring barley and rapeseed (plus the pulses and soybean) have Agreste departmental
yield histories in this project. Winter barley, durum wheat, grain maize and sunflower
resolve through `ml.baseline_yield` to a hand-written national constant carrying NO
departmental signal. Using the real second crop would therefore swap a
department-calibrated baseline for a flat number, and the resulting spread between
departments would be an artefact of the fallback rather than agronomy.

So the comparator is the best-EVIDENCED alternative rather than the most widely grown
one, and where those differ the record says so. `caveat()` turns that into a sentence
the API can show. Closing the gap properly means ingesting the missing Agreste yield
series, which is a data task; this module makes the gap visible in the meantime.
"""
from __future__ import annotations

from functools import cache
from typing import Any

from ..config import load_ref

# What every one of those call sites used before this module existed. Retained so a
# missing or partial artifact degrades to the previously published behaviour instead of
# raising, and so `provenance()` can always say what it would otherwise have used.
LEGACY_ROTATION: list[str] = ["soft_wheat", "spring_barley", "rapeseed"]
LEGACY_SOUTHWEST: list[str] = ["durum_wheat", "sunflower", "soft_wheat"]
LEGACY_SOUTHWEST_REGIONS = frozenset({"FRJ2", "FRI1"})


@cache
def _table() -> dict[str, Any]:
    try:
        raw = load_ref("dept_rotations")
    except FileNotFoundError:
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@cache
def table_meta() -> dict[str, Any]:
    try:
        return load_ref("dept_rotations").get("_meta", {})
    except FileNotFoundError:
        return {}


def _label(crop_key: str) -> str:
    """French crop label, matching how every other caveat in the API names a crop."""
    from ..config import crops

    return crops().get(crop_key, {}).get("label_fr", crop_key)


def _legacy_for(dept_code: str) -> list[str]:
    from ..config import departments

    d = departments().get(dept_code, {})
    if d.get("region_code") in LEGACY_SOUTHWEST_REGIONS:
        return list(LEGACY_SOUTHWEST)
    return list(LEGACY_ROTATION)


def baseline_rotation(dept_code: str) -> list[str]:
    """The three-year cereal rotation to compare a pulse against in this department.

    Year 2 is the displaced crop. Falls back to the previously hard-coded list when the
    generated table is absent, so the API answers with its old behaviour rather than a
    500 if `scripts/build_dept_rotations.py` has not been run.
    """
    rec = _table().get(dept_code)
    if not rec or not rec.get("rotation"):
        return _legacy_for(dept_code)
    rot = list(rec["rotation"])
    return rot if len(rot) == 3 else _legacy_for(dept_code)


def displaced_crop(dept_code: str) -> str:
    """The year-2 crop, i.e. the one the pulse replaces."""
    return baseline_rotation(dept_code)[1]


# Below this, the derived rotation describes a minority of the department's arable
# area and the engine is modelling a rotation most of that department does not run.
# The eight departments concerned are durum wheat, grain maize and sunflower country.
LOW_COVERAGE_PCT = 50.0


def _family_word(crop_key: str) -> str:
    """"cereal" or "oilseed", so a caveat never miscalls rapeseed a cereal."""
    from ..config import crop as _crop

    fam = _crop(crop_key).get("family")
    return "oilseed" if fam == "oilseed" else "cereal"


def _forced_oilseed_note(dept_code: str, y2: str) -> str | None:
    """Disclosure for the departments with only ONE priceable cereal.

    Year 2 is meant to be the weakest spare CEREAL, because a pulse replaces a cereal
    and becomes the break crop itself. In six departments - 01, 40, 47, 64, 65, 68 -
    spring barley falls below the minimum slot share, so the only remaining priceable
    crop is rapeseed and the pulse ends up measured against the break crop. That makes
    the comparison harsher than it should be and it also sits badly agronomically, since
    `rotation_rules.json` lists rapeseed as a Sclerotinia sclerotiorum host alongside
    soybean. Saying so beats letting a reader find a suspiciously negative department.
    """
    from ..config import crop as _crop

    if _crop(y2).get("family") != "oilseed":
        return None
    return (
        f"This department has only one cereal with a measured Agreste yield history, so "
        f"the pulse is compared against {_label(y2)} - its break crop - rather than "
        f"against a spare cereal. That is a harsher comparison than elsewhere: an "
        f"oilseed break crop earns more than the weak second cereal a pulse would "
        f"normally replace, and agronomically a pulse is meant to BECOME the break crop "
        f"rather than displace it. Read a negative result here as partly an artefact of "
        f"the missing yield series, not only as poor economics."
    )


def caveat(dept_code: str) -> str | None:
    """Plain-language warning when the comparator is not the most widely grown crop.

    Returns None when the engine can price the department's largest alternative crop,
    because then there is nothing to warn about.

    NOTE: year 2 is selected as the LEAST PROFITABLE priceable cereal, not the largest
    by area. An earlier version of both the selection and this message used area, which
    put rapeseed in the displaced slot across northern France. That is the wrong
    counterfactual - a farmer giving a slot to a pulse drops their weakest crop, not
    their second-best one, and rapeseed is itself the break crop a pulse is supposed to
    become. See scripts/build_dept_rotations.py for the full argument.
    """
    rec = _table().get(dept_code)
    if not rec:
        return (
            "No per-department rotation table was found, so the baseline rotation is "
            "the project's old hard-coded default rather than this department's own "
            "Agreste area shares. Run scripts/build_dept_rotations.py."
        )
    gap = rec.get("dominant_alternative_not_priceable")
    y2 = rec["displaced_year2_crop"]
    forced = _forced_oilseed_note(dept_code, y2)
    if not gap:
        # Nothing to say about evidence, but a forced oilseed comparator still needs
        # disclosing: the pulse is being measured against the department's break crop
        # rather than against a spare cereal, because there is no second priceable
        # cereal here.
        return forced
    msg = (
        f"The pulse here is compared against {_label(y2)} "
        f"({rec['area_share_pct'].get(y2, 0):.0f}% of this department's non-legume "
        f"arable area): the lowest-margin {_family_word(y2)} the engine has a measured "
        f"Agreste "
        f"yield history for, on the reasoning that a farmer giving a rotation slot to a "
        f"pulse drops their weakest crop rather than their best. The department's "
        f"largest alternative is {_label(gap['crop'])} at "
        f"{gap['area_share_pct']:.0f}%, which has no yield series in this project, so "
        "using it would mean a hand-written national constant with no departmental "
        "signal. The comparison is therefore against the best-evidenced weak "
        "alternative, not the most widely grown crop."
    )
    if forced:
        msg += " " + forced
    cov = rec.get("rotation_coverage_pct")
    if cov is not None and cov < LOW_COVERAGE_PCT:
        msg += (
            f" Note also that the whole derived rotation covers only {cov:.0f}% of this "
            "department's non-legume arable area, so it is a minority rotation here - "
            "this is durum wheat, grain maize and sunflower country, and none of those "
            "has a yield series in this project. Treat the figures as indicative of a "
            "wheat-and-rapeseed field in this climate rather than of the department."
        )
    return msg


def provenance(dept_code: str) -> dict[str, Any]:
    """Everything an API response needs to state how the comparator was chosen."""
    rec = _table().get(dept_code)
    rot = baseline_rotation(dept_code)
    out: dict[str, Any] = {
        "baseline_rotation": rot,
        "displaced_year2_crop": rot[1],
        "source": (rec or {}).get("source", "legacy_hardcode"),
        "rule": table_meta().get("rule"),
        "area_source": table_meta().get("area_source"),
    }
    if rec:
        for k in ("area_share_pct", "rotation_coverage_pct", "top3_actual",
                  "changed_from_legacy", "legacy_rotation"):
            if k in rec:
                out[k] = rec[k]
    else:
        out["legacy_rotation"] = _legacy_for(dept_code)
    if (c := caveat(dept_code)) is not None:
        out["caveat"] = c
    return out
