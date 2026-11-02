"""Matching a downgraded food-grade lot to a neighbouring livestock holding.

## The fear this is built to kill

A cereal farmer's objection to food-grade pulses is not about average yield. It is
this: a wet July or a bruchid flight turns the whole lot from 840 EUR/t human-grade
lentil into 275 EUR/t commodity feed, and the year is a loss. That single bad outcome
is why land stays in wheat even when the three-year expectation favours the pulse.

The existing engine already had half an answer: a MIXED farm, one that owns herbivores,
does not sell a downgraded lot at the feed spot price - it feeds it, replacing purchased
soybean meal and cereal, which is worth about 298 EUR/t rather than 252. But that only
helps farms that already have livestock, and the farms with the most cereal land mostly
do not.

This module supplies the other half. The downgraded lot does not need to be fed on the
farm that grew it; it needs to be fed within haulage distance of it. France imports
roughly 3.5 Mt of soybean meal a year, much of it South American, and a livestock
holding 20 km away is buying some of it. A high-protein pulse lot that failed a visual
food specification is, to that holding, a perfectly good non-GMO protein source.

## Why both sides of the trade are reported

It would be easy to show only the farmer's side - "your worst case improves by 300
EUR/ha" - and leave the breeder as an implied, costless counterparty. That is the kind
of claim that collapses the moment a jury member who keeps cattle asks what is in it for
them. So the output states, per tonne: what the lot is worth to the breeder, what the
breeder pays, what each side keeps, and how much imported soybean meal stops being
bought. The surplus split is a stated assumption, not a hidden one.

## What it will not claim

Three honest limits, enforced in the arithmetic rather than mentioned in a footnote:

* Inclusion caps. Raw pulses carry anti-nutritional factors, so a holding can only take
  a bounded share of its concentrate as pulse. A lot bigger than the local caps cannot
  all be placed, and `absorbs_whole_lot` says so.
* Distance. Past about 25 km the haulage on a feed-value lot eats the premium, and the
  match is dropped rather than quietly stretched.
* The directory itself is illustrative on identity and real on geography. See
  `refdata/breeders.json` `_meta`.
"""
from __future__ import annotations

from functools import cache
from typing import Any

import numpy as np

from ..config import crop, departments, load_ref
from .logistics import road_km


@cache
def _ref() -> dict:
    return load_ref("breeders")


def directory() -> list[dict]:
    return _ref()["breeders"]


def matching_rules() -> dict:
    return _ref()["matching"]


@cache
def _non_gmo_premium_eur_t() -> float:
    """Certified non-GMO soybean meal premium over standard, EUR/t.

    Read out of `buyers.json`, where this project already quotes it as a contract
    premium, rather than introduced as a new parameter here. If the two ever disagree
    that is a bug in one of them, and sharing the source makes it impossible.
    """
    for b in load_ref("buyers")["buyers"]:
        prem = (b.get("premiums") or {}).get("non_gmo_eur_t")
        if prem:
            return float(prem)
    return 0.0


@cache
def _non_gmo_share() -> float:
    """Measured share of the holding directory that buys certified non-GMO meal.

    Counted from the directory rather than assumed. The field existed from the first
    build and nothing read it, which meant the fallback was costed against standard
    meal for every holding including the ones whose whole reason to want a local pulse
    is avoiding a non-GMO premium.
    """
    rows = directory()
    if not rows:
        return 0.0
    return sum(1 for b in rows if b.get("currently_buys_non_gmo_soy")) / len(rows)


def substitution_value_eur_t(pulse: str) -> dict[str, Any]:
    """What one tonne of this pulse is worth to a livestock ration, EUR/t.

    Deterministic central value, deliberately: this figure is quoted to a farmer as the
    basis of a contract price, and quoting a contract basis as a distribution invites
    the reader to pick the end they like. The Monte Carlo still draws the realised price
    around it when the fallback is priced into the margin.
    """
    ref = load_ref("feed_substitution")
    sub = ref["substitution"].get(pulse)
    spot = float(crop(pulse)["feed_price_eur_t"]["mean"])
    if not sub:
        return {
            "substitution_value_eur_t": spot,
            "feed_spot_eur_t": spot,
            "a_soymeal": 0.0,
            "a_cereal": 0.0,
            "note": f"No substitution ratios published here for {pulse}; feed spot used.",
        }
    rp = ref["reference_prices_eur_t"]
    wheat = float(rp["feed_wheat"]["mean"])
    base_meal = float(rp["soybean_meal_48"]["mean"])

    # The counterfactual is what the holding ACTUALLY buys, and the holdings this
    # engine matches against are the ones displacing non-GMO South American meal -
    # that is the premise of the whole fallback. Non-GMO meal trades above standard,
    # so costing the substitution at the generic price understated it.
    #
    # The premium is NOT a new invented number: buyers.json already commits this
    # project to `non_gmo_eur_t` for exactly this grade difference, and reusing it
    # keeps the two files consistent instead of carrying two different answers to the
    # same question. `non_gmo_share` is the measured share of the generated holding
    # directory flagged as buying certified non-GMO, so the blended price reflects the
    # mix the matcher actually works with rather than assuming all or none.
    prem = _non_gmo_premium_eur_t()
    share_non_gmo = _non_gmo_share()
    meal = base_meal + prem * share_non_gmo

    v = (
        float(sub["a_soymeal"]) * meal
        + float(sub["a_cereal"]) * wheat
        + float(ref["avoided_logistics_eur_t"])
    )
    return {
        "substitution_value_eur_t": round(v, 1),
        "feed_spot_eur_t": round(spot, 1),
        "a_soymeal": float(sub["a_soymeal"]),
        "a_cereal": float(sub["a_cereal"]),
        "soybean_meal_eur_t": round(meal, 1),
        "soybean_meal_standard_eur_t": base_meal,
        "non_gmo_premium_eur_t": prem,
        "non_gmo_share_of_holdings": round(share_non_gmo, 3),
        "feed_wheat_eur_t": wheat,
        "note": (
            f"One tonne of {pulse} replaces {sub['a_soymeal']} t of 48 percent soybean "
            f"meal and {sub['a_cereal']} t of feed wheat on a combined protein and "
            f"energy basis, plus avoided haulage and trader margin on both. The meal it "
            f"displaces is priced at {meal:.0f} EUR/t: the {base_meal:.0f} EUR/t "
            f"standard reference plus the {prem:.0f} EUR/t certified non-GMO premium "
            f"this project already uses in its buyer book, weighted by the "
            f"{share_non_gmo:.0%} of local holdings on file that buy non-GMO."
        ),
    }


def offered_price_eur_t(pulse: str) -> dict[str, Any]:
    """Contract price a neighbouring holding would pay, and how the surplus splits."""
    v = substitution_value_eur_t(pulse)
    share = float(matching_rules()["farmer_share_of_surplus"])
    spot = v["feed_spot_eur_t"]
    surplus = max(v["substitution_value_eur_t"] - spot, 0.0)
    offered = spot + share * surplus
    return {
        **v,
        "farmer_share_of_surplus": share,
        "offered_price_eur_t": round(offered, 1),
        "uplift_vs_spot_eur_t": round(offered - spot, 1),
        "breeder_margin_eur_t": round(v["substitution_value_eur_t"] - offered, 1),
    }


def _origin(
    dept_code: str, point: tuple[float, float] | None
) -> tuple[float, float] | None:
    if point:
        return point
    d = departments().get(dept_code)
    return tuple(d["centroid"]) if d else None


def match(
    *,
    pulse: str,
    dept_code: str,
    point: tuple[float, float] | None,
    downgraded_lot_t: float,
    max_matches: int = 4,
) -> dict[str, Any]:
    """Nearest holdings that can take a downgraded lot, with both sides priced."""
    rules = matching_rules()
    max_km = float(rules["max_haul_km"])
    pricing = offered_price_eur_t(pulse)
    origin = _origin(dept_code, point)
    if origin is None:
        return {
            "available": False, "matches": [], "pricing": pricing,
            "radius_km": max_km, "nearest_holding_km": None, "n_within_radius": 0,
        }

    herd_ref = _ref()["_meta"]["herd_type_reference"]
    all_km: list[tuple[float, dict]] = []
    for b in directory():
        loc = b.get("location")
        if not loc:
            continue
        all_km.append((road_km(origin, (float(loc[0]), float(loc[1]))), b))
    all_km.sort(key=lambda t: t[0])
    near = [t for t in all_km if t[0] <= max_km]
    # Reported even when it does not qualify, so "no match" is explained rather than
    # merely asserted. A holding 25.1 km away against a 25 km radius is a different
    # situation from the nearest holding being 90 km away, and the user should see which.
    nearest_any_km = round(all_km[0][0], 1) if all_km else None

    lot = max(float(downgraded_lot_t), 0.0)
    matches: list[dict] = []
    placed = 0.0
    for km, b in near[:max_matches]:
        cap = float(b["max_pulse_intake_t"])
        take = min(cap, max(lot - placed, 0.0)) if lot > 0 else cap
        placed += take
        avoided_soy_t = take * pricing["a_soymeal"]
        matches.append({
            "breeder_id": b["breeder_id"],
            "name": b["name"],
            "dept": b["dept"],
            "distance_km": round(km, 1),
            "herd_type": herd_ref.get(b["herd_type"], {}).get("label_fr", b["herd_type"]),
            "ugb": int(b["ugb"]),
            "annual_protein_meal_demand_t": float(b["annual_protein_meal_demand_t"]),
            "max_pulse_intake_t": cap,
            "offered_price_eur_t": pricing["offered_price_eur_t"],
            "feed_spot_price_eur_t": pricing["feed_spot_eur_t"],
            "uplift_vs_spot_eur_t": pricing["uplift_vs_spot_eur_t"],
            "breeder_avoided_soy_t": round(avoided_soy_t, 1),
            "breeder_avoided_soy_cost_eur": round(
                avoided_soy_t * pricing.get("soybean_meal_eur_t", 425.0), 0
            ),
            "absorbs_whole_lot": bool(cap >= lot),
            "note": (
                f"{int(b['ugb'])} UGB buying about "
                f"{b['annual_protein_meal_demand_t']:.0f} t of protein concentrate a year. "
                f"Can take up to {cap:.0f} t of {crop(pulse)['label_fr'].lower()} within "
                "its inclusion limit."
            ),
        })

    return {
        "available": bool(matches),
        "radius_km": max_km,
        "n_within_radius": len(near),
        "nearest_holding_km": nearest_any_km,
        "matches": matches,
        "pricing": pricing,
        "lot_t": round(lot, 1),
        "placed_t": round(min(placed, lot) if lot > 0 else placed, 1),
        "whole_lot_placeable": bool(lot <= 0 or placed >= lot),
    }


def fallback_floor_eur_t(pulse: str, available: bool) -> float | None:
    """The price floor a signed fallback contract puts under the downgraded fraction.

    Returns None when there is no surplus to split, which is not a corner case: CHICKPEA
    has a commodity feed price of about 295 EUR/t against a ration substitution value of
    about 294, so a livestock holding cannot outbid the feed market for it and there is
    no contract worth signing. Returning a floor equal to the spot price would dress
    that up as a contract that does nothing.
    """
    if not available:
        return None
    p = offered_price_eur_t(pulse)
    if p["uplift_vs_spot_eur_t"] < float(matching_rules()["min_viable_uplift_eur_t"]):
        return None
    return float(p["offered_price_eur_t"])


def fallback_is_worth_signing(pulse: str) -> dict[str, Any]:
    """Whether a local breeder can outbid the commodity feed market for this crop."""
    p = offered_price_eur_t(pulse)
    floor_eur = float(matching_rules()["min_viable_uplift_eur_t"])
    worth = p["uplift_vs_spot_eur_t"] >= floor_eur
    return {
        "worth_signing": worth,
        "uplift_vs_spot_eur_t": p["uplift_vs_spot_eur_t"],
        "min_viable_uplift_eur_t": floor_eur,
        "reason": (
            f"A ration values this crop at {p['substitution_value_eur_t']:.0f} EUR/t "
            f"against a feed spot price of {p['feed_spot_eur_t']:.0f} EUR/t, so a local "
            f"contract can pay {p['offered_price_eur_t']:.0f} EUR/t."
            if worth
            else (
                f"A ration values this crop at "
                f"{p['substitution_value_eur_t']:.0f} EUR/t against a feed spot price of "
                f"{p['feed_spot_eur_t']:.0f} EUR/t, so a local holding could only outbid "
                f"the open market by {p['uplift_vs_spot_eur_t']:.1f} EUR/t. That is below "
                f"the {floor_eur:.0f} EUR/t it costs to have a contract at all - "
                f"sampling, haulage terms, administration on both sides - so there is no "
                f"fallback worth signing here. The commodity feed market IS the floor "
                f"for this crop."
            )
        ),
    }


def headline(
    *,
    available: bool,
    cvar_without: float | None,
    cvar_with: float | None,
    crop_label: str,
    nearest_km: float | None = None,
    radius_km: float = 25.0,
) -> str:
    """One sentence an advisor can read aloud, which is what this block is for."""
    if not available:
        if nearest_km is not None:
            return (
                f"Nearest livestock holding is {nearest_km:.0f} km away, outside the "
                f"{radius_km:.0f} km radius at which a feed-value lot still pays its own "
                "haulage. The downgraded fraction stays exposed to the commodity feed "
                "market."
            )
        return (
            "No livestock holding found inside the haulage radius, so the downgraded "
            "fraction stays exposed to the commodity feed market."
        )
    if cvar_without is None or cvar_with is None:
        return (
            f"A neighbouring holding will take a downgraded {crop_label} lot above the "
            "feed spot price, putting a floor under the bad year."
        )
    gain = cvar_with - cvar_without
    if cvar_without < 0 <= cvar_with:
        return (
            f"Without a fallback contract the one-in-seven bad year loses "
            f"{abs(cvar_without):,.0f} EUR/ha against staying in cereals. With a local "
            f"breeder contract that same year GAINS {cvar_with:,.0f} EUR/ha. The crop "
            "stops being a gamble and the breeder stops importing soy."
        )
    return (
        f"A local breeder contract lifts the one-in-seven bad year by "
        f"{gain:,.0f} EUR/ha, from {cvar_without:,.0f} to {cvar_with:,.0f} EUR/ha."
    )


def region_import_substitution(dept_code: str, placed_t: float, pulse: str) -> dict:
    """Imported soybean meal displaced, scaled to the lot actually placed locally."""
    p = offered_price_eur_t(pulse)
    soy_t = placed_t * p["a_soymeal"]
    return {
        "pulse_t_placed_locally": round(placed_t, 1),
        "imported_soybean_meal_displaced_t": round(soy_t, 1),
        "import_value_displaced_eur": round(soy_t * p.get("soybean_meal_eur_t", 425.0), 0),
        "note": (
            "Displaced on a combined crude-protein and metabolisable-energy equivalence "
            "basis, not tonne for tonne: soybean meal is 46 percent protein and a pulse "
            "is 20-26 percent, so a tonne of pulse does not replace a tonne of meal."
        ),
    }


def summarise_for_api(
    *,
    pulse: str,
    dept_code: str,
    point: tuple[float, float] | None,
    downgraded_lot_t: float,
    sim_without: dict | None = None,
    sim_with: dict | None = None,
    crop_label: str = "",
) -> dict[str, Any]:
    """Assemble the response block, including the before/after risk comparison."""
    m = match(
        pulse=pulse, dept_code=dept_code, point=point, downgraded_lot_t=downgraded_lot_t
    )

    def cvar(sim: dict | None) -> float | None:
        if not sim:
            return None
        d = sim["delta"]
        tail = d[d <= np.quantile(d, 0.15)]
        return round(float(tail.mean()), 1) if tail.size else None

    def med(sim: dict | None) -> float | None:
        return round(float(np.median(sim["delta"])), 1) if sim else None

    c_without, c_with = cvar(sim_without), cvar(sim_with)
    return {
        "available": m["available"],
        "search_radius_km": m["radius_km"],
        "nearest_holding_km": m.get("nearest_holding_km"),
        "holdings_within_radius": m.get("n_within_radius", 0),
        "downgraded_lot_t_median": round(float(downgraded_lot_t), 1),
        "matches": m["matches"],
        "best_offered_price_eur_t": (
            m["pricing"]["offered_price_eur_t"] if m["available"] else None
        ),
        "feed_spot_price_eur_t": m["pricing"]["feed_spot_eur_t"],
        "worth_signing": fallback_is_worth_signing(pulse),
        "cvar_without_fallback_eur_ha": c_without,
        "cvar_with_fallback_eur_ha": c_with,
        "cvar_improvement_eur_ha": (
            round(c_with - c_without, 1)
            if (c_with is not None and c_without is not None) else None
        ),
        "median_without_fallback_eur_ha": med(sim_without),
        "median_with_fallback_eur_ha": med(sim_with),
        "headline": headline(
            available=m["available"], cvar_without=c_without, cvar_with=c_with,
            crop_label=crop_label or pulse,
            nearest_km=m.get("nearest_holding_km"), radius_km=m["radius_km"],
        ),
        "import_substitution": region_import_substitution(
            dept_code, m.get("placed_t", 0.0), pulse
        ),
        "pricing": m["pricing"],
    }
