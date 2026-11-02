"""The demand side: what people in France eat, against what French farms supply.

Every other service in this engine looks upstream from the farm gate. This one looks
downstream, because the question the project is answering is not "can a pulse grow
here" but "can it grow here AND end up on a French plate AND pay the farmer".

Three things live here:

* **National balance.** Current pulse intake and the intake implied by the public
  nutrition recommendation, against domestic food-tier production. The gap between
  those is the demand-side opportunity, and it is large: France eats roughly three
  times less pulses than the world average while the recommendation is three times
  what it eats.

* **Collective catering.** A contractable floor on demand, derived from the weekly
  vegetarian main that EGalim put into public canteens. Deliberately modest in the
  output - public catering is a reliable floor, not a substitute for retail growth,
  and a pitch that claims otherwise is overstating it.

* **Food-grade supply.** Tonnes of harvest that actually reach human food, which is
  two multiplications away from tonnes grown: the lot-level grading fraction from
  quality.py, and the crop's structural food-market share. A perfectly graded fava
  bean crop still mostly goes to feed, because that is where the demand is.

Nothing here is a model. It is arithmetic over named parameters, so a reader who
disagrees with the 60 g serving can change one number in food_demand.json and watch
every tonnage move.
"""
from __future__ import annotations

from ..config import load_ref

WEEKS_PER_YEAR = 52.0


def ref() -> dict:
    return load_ref("food_demand")


def _intake() -> dict:
    return ref()["intake"]


def recommended_intake_kg_per_capita() -> float:
    """Annual dry-pulse intake implied by the public nutrition recommendation.

    servings per week x weeks x dry weight per serving. Uses the low end of the
    standard portion range, so this is a conservative floor for the recommended level
    rather than a flattering ceiling.
    """
    i = _intake()
    return (
        float(i["recommended_servings_per_week"])
        * WEEKS_PER_YEAR
        * float(i["serving_dry_weight_g"])
        / 1000.0
    )


def _tonnes(kg_per_capita: float, population_millions: float) -> float:
    return kg_per_capita * population_millions * 1e6 / 1000.0


def national() -> dict:
    """The national food-pulse balance, derived rather than stored."""
    r = ref()
    i = _intake()
    pop = float(r["population"]["france_millions"])
    cur_kg = float(i["current_kg_per_capita_year"])
    rec_kg = recommended_intake_kg_per_capita()

    cur_t = _tonnes(cur_kg, pop)
    rec_t = _tonnes(rec_kg, pop)
    prod_t = float(r["domestic_supply"]["legumes_secs_production_t_2022"])

    return {
        "population_millions": pop,
        "current_intake_kg_per_capita_year": round(cur_kg, 2),
        "current_intake_range_kg": i["current_range_kg"],
        "recommended_intake_kg_per_capita_year": round(rec_kg, 2),
        "recommended_servings_per_week": float(i["recommended_servings_per_week"]),
        "serving_dry_weight_g": float(i["serving_dry_weight_g"]),
        "current_demand_t": round(cur_t, 0),
        "recommended_demand_t": round(rec_t, 0),
        "domestic_food_production_t": round(prod_t, 0),
        # What French farms supply of what French people eat TODAY. The official
        # statement for the human-consumption tier is "about one third"; this lands in
        # the same place, which is why these two anchors are used together.
        "self_sufficiency_current_pct": round(100.0 * prod_t / cur_t, 1) if cur_t else None,
        "self_sufficiency_at_recommended_pct": (
            round(100.0 * prod_t / rec_t, 1) if rec_t else None
        ),
        "import_gap_today_t": round(max(cur_t - prod_t, 0.0), 0),
        "gap_at_recommended_intake_t": round(max(rec_t - prod_t, 0.0), 0),
        "area_trend": {
            "legumes_secs_ha_2020": float(r["domestic_supply"]["legumes_secs_area_ha_2020"]),
            "legumes_secs_ha_2022": float(r["domestic_supply"]["legumes_secs_area_ha_2022"]),
            "change_pct": round(
                100.0
                * (
                    float(r["domestic_supply"]["legumes_secs_area_ha_2022"])
                    / float(r["domestic_supply"]["legumes_secs_area_ha_2020"])
                    - 1.0
                ),
                1,
            ),
        },
        "finding": (
            f"France eats about {cur_t:,.0f} t of dry pulses a year and grows about "
            f"{prod_t:,.0f} t of them, so roughly {100.0 * prod_t / cur_t:.0f} percent of "
            "the pulses on French plates are French. At the twice-a-week intake the "
            f"public nutrition recommendation asks for, demand would be about {rec_t:,.0f} "
            "t - and the human-food area fell 23 percent between 2020 and 2022. The "
            "binding constraint on this tier is not that nobody wants the crop."
        ),
        "provenance": {
            "source": (
                "Derived in services/demand.py from refdata/food_demand.json: INSEE "
                "population, PNNS / Sante Publique France pulse recommendation, and "
                "DGPE legumes secs harvest data via the France Strategie evaluation of "
                "France Relance (January 2024)."
            ),
            "mode": "reference_table",
            "caveat": (
                "Current intake is a central estimate in a 1.7 to 2.5 kg band, not a "
                "measured market balance. FranceAgriMer publishes pulse balances; "
                "wiring those in would replace the softest parameter here."
            ),
        },
    }


def catering(population_millions: float | None = None) -> dict:
    """Legume tonnage implied by the weekly vegetarian main in public canteens.

    Scaled by population when a region is asked for, because meal counts are published
    nationally and a regional split would be invented. Transparent scaling beats a
    fabricated regional statistic.
    """
    r = ref()
    c = r["collective_catering"]
    i = _intake()
    nat_pop = float(r["population"]["france_millions"])
    pop = float(population_millions if population_millions is not None else nat_pop)
    share = pop / nat_pop

    serving_kg = float(i["serving_dry_weight_g"]) / 1000.0
    veg_share = float(c["vegetarian_main_per_week"]) / float(c["weekday_meals_per_week"])
    legume_share = float(c["legume_share_of_vegetarian_mains"])

    def _t(meals_billions: float) -> float:
        meals = meals_billions * 1e9 * share
        return meals * veg_share * legume_share * serving_kg / 1000.0

    total_t = _t(float(c["meals_per_year_total_billions"]))
    school_t = _t(float(c["meals_per_year_school_billions"]))
    return {
        "population_millions": round(pop, 3),
        "share_of_national": round(share, 4),
        "all_collective_catering_t": round(total_t, 0),
        "school_catering_t": round(school_t, 0),
        "vegetarian_main_share_of_weekday_meals": round(veg_share, 3),
        "legume_share_of_vegetarian_mains": legume_share,
        "policy_basis": c["policy_basis"],
        "interpretation": c["interpretation"],
    }


def food_market_share(crop_key: str) -> float:
    """Fraction of this crop's French volume that reaches human food at all.

    Distinct from the lot grading probability, and both apply. P_human asks whether
    THIS lot clears retail specification; this asks whether a human-food outlet exists
    for the crop in the first place. Multiplying them is what stops a well-graded fava
    bean harvest being reported as food the country eats.
    """
    m = ref()["crop_food_market"].get(crop_key)
    if not m:
        return 0.0
    return float(m["food_market_share"])


def crop_food_note(crop_key: str) -> str | None:
    m = ref()["crop_food_market"].get(crop_key)
    return m.get("note") if m else None


def food_grade_tonnes(
    crop_key: str, yield_t_ha: float, human_fraction: float, area_ha: float
) -> float:
    """Tonnes of this harvest that end up as food for people."""
    return (
        max(float(yield_t_ha), 0.0)
        * float(area_ha)
        * max(min(float(human_fraction), 1.0), 0.0)
        * food_market_share(crop_key)
    )


def split_food_feed(crop_key, yield_t_ha, human_fraction, area_ha):
    """Split a harvest into food-for-people and feed, draw by draw.

    Returned as three arrays rather than three medians because medians do not add: the
    median of the food tonnage plus the median of the feed tonnage is NOT the median
    harvest, and reporting them as if it were would quietly invent or lose mass. The
    identity `food + feed == harvest` holds exactly per draw, which is the property
    worth guaranteeing and the one the tests pin.
    """
    import numpy as np

    y = np.clip(np.asarray(yield_t_ha, dtype=float), 0.0, None)
    harvest = y * float(area_ha)
    frac = np.clip(
        np.asarray(human_fraction, dtype=float) * food_market_share(crop_key), 0.0, 1.0
    )
    food = harvest * frac
    return harvest, food, harvest - food


def people_fed(food_tonnes: float, *, at_recommended: bool = False) -> float:
    """How many people's annual pulse consumption this tonnage covers.

    Reported at both intakes on purpose. At today's intake the number flatters the
    parcel, because today's intake is low; at the recommended intake it is three times
    smaller and three times more useful as a planning figure.
    """
    kg = (
        recommended_intake_kg_per_capita()
        if at_recommended
        else float(_intake()["current_kg_per_capita_year"])
    )
    if kg <= 0:
        return 0.0
    return float(food_tonnes) * 1000.0 / kg


def region_requirement(region_code: str) -> dict | None:
    """What this region's population eats, and would eat at the recommendation."""
    r = ref()
    reg = r["population"]["regions"].get(region_code)
    if not reg:
        return None
    pop = float(reg["population_millions"])
    cur_kg = float(_intake()["current_kg_per_capita_year"])
    rec_kg = recommended_intake_kg_per_capita()
    return {
        "region_code": region_code,
        "region_name": reg["name"],
        "population_millions": pop,
        "current_demand_t": round(_tonnes(cur_kg, pop), 0),
        "recommended_demand_t": round(_tonnes(rec_kg, pop), 0),
        "catering": catering(pop),
    }


def balance(region_code: str, suppliable_food_t: float) -> dict | None:
    """Put a region's modelled food-grade supply next to what it eats.

    The ratio is the number a Region can act on: below 100 percent it is importing the
    pulses its own population eats, and the deficit in tonnes converts directly into
    hectares, a sorting-capacity question, or a contract volume.
    """
    req = region_requirement(region_code)
    if req is None:
        return None
    cur = float(req["current_demand_t"])
    rec = float(req["recommended_demand_t"])
    s = max(float(suppliable_food_t), 0.0)
    cat = float(req["catering"]["all_collective_catering_t"])
    return {
        **req,
        "suppliable_food_grade_t": round(s, 0),
        "coverage_of_current_demand_pct": round(100.0 * s / cur, 1) if cur else None,
        "coverage_of_recommended_demand_pct": round(100.0 * s / rec, 1) if rec else None,
        "deficit_vs_current_t": round(max(cur - s, 0.0), 0),
        "deficit_vs_recommended_t": round(max(rec - s, 0.0), 0),
        "covers_collective_catering": bool(s >= cat),
        "catering_coverage_pct": round(100.0 * s / cat, 1) if cat else None,
    }
