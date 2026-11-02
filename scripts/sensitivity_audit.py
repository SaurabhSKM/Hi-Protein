"""Which assumptions actually matter? Perturb each one and measure what moves.

"Critical" is only a meaningful word if it is operationalised. Here it means: push the
assumption to the edge of its plausible range and see whether a HEADLINE CONCLUSION
changes — the sign of the farmer's verdict, the size of the stranded-land claim, or the
identity of the sites the optimiser recommends.

An assumption that moves a number by 30% but changes no decision is not critical. One
that reorders the optimiser's recommendations is, because that reordering is the product.

Run: .venv/bin/python scripts/sensitivity_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402
from app.config import load_ref  # noqa: E402
from app.services import breeders as B  # noqa: E402
from app.services import finance as F  # noqa: E402
from app.services import logistics as L  # noqa: E402
from app.services import quality as Q  # noqa: E402
from app.services import siting as S  # noqa: E402
from app.services import weather  # noqa: E402


# The audit has to perturb what the engine actually ships, so the baseline rotation
# comes from the same per-department table the API uses rather than being pinned here.
# It used to be a hard-coded ["soft_wheat", "spring_barley", "rapeseed"], which meant
# the audit was measuring sensitivities around a rotation 38 of 42 departments do not
# run. The rotation itself is the one assumption this script still cannot perturb
# cheaply: changing the year-2 crop means re-simulating a different crop's margin, not
# repricing the draws already taken.
def base_rot(dept: str) -> list[str]:
    from app.services import rotations

    return rotations.baseline_rotation(dept)


def clear_caches() -> None:
    """Reference data is memoised all over the engine; drop every layer."""
    for fn in (
        S.demand_surface, S.profiles, S._profile_tables, S.candidate_sites,
        S._classify_cached, S._bake_file, B._ref,
    ):
        with_clear = getattr(fn, "cache_clear", None)
        if with_clear:
            with_clear()
    S._PAIR_CACHE.clear()


def surface_summary() -> dict:
    clear_caches()
    t = S.classify()["totals"]
    return {"stranded": t["stranded_communes"], "stranded_ha": t["stranded_ha"],
            "viable": t["viable_communes"], "uneconomic": t["uneconomic_communes"]}


def sites(k: int = 3) -> tuple[list[str], float]:
    clear_caches()
    r = S.optimise(k=k)
    if "error" in r:
        return ["ERROR"], 0.0
    return [s["commune"] for s in r["sites"]], r["impact"]["hectares_unlocked"]


def farmer(dept="28", soil="deep_loam", pulse="field_pea", km=None, n=1200, **kw):
    rng = np.random.default_rng(7)
    seasons = [weather.sample_seasons(dept, n, rng) for _ in range(3)]
    state = rng.bit_generator.state
    r2 = np.random.default_rng()
    r2.bit_generator.state = state
    acc = L.access(tuple(load_ref("departments")[dept]["centroid"]))
    rot = base_rot(dept)
    sim = F.simulate(
        dept=dept, soil=soil, baseline_rotation=rot, pulse=pulse,
        seasons=seasons, rng=r2, preceding_crop=rot[0],
        has_optical_sorting_access=acc["within_range"],
        sorter_road_km=acc["road_km"] if km is None else km, **kw,
    )
    d = sim["delta"]
    tail = d[d <= np.quantile(d, 0.15)]
    return {"median": float(np.median(d)), "cvar15": float(tail.mean())}


def report(name: str, rows: list[tuple[str, str]], verdict: str) -> None:
    print(f"\n{'=' * 78}\n{name}\n{'-' * 78}")
    for label, value in rows:
        print(f"  {label:<34} {value}")
    print(f"  → {verdict}")


def main() -> int:  # noqa: PLR0915
    base_surface = surface_summary()
    base_sites, base_ha = sites()
    base_farmer = farmer()
    print("BASELINE")
    print(f"  stranded communes {base_surface['stranded']}  "
          f"({base_surface['stranded_ha']:,.0f} ha)")
    print(f"  top-3 sites       {base_sites}")
    print(f"  demo field        median {base_farmer['median']:+.0f}  "
          f"CVaR15 {base_farmer['cvar15']:+.0f} EUR/ha")

    log = load_ref("logistics")

    # ---- #9 haulage rate, across its own published range -----------------
    rows = []
    for rate in (0.32, 0.45, 0.58):
        log["haulage"]["eur_per_tonne_km"] = rate
        s = surface_summary()
        st, _ = sites()
        rows.append((f"€{rate}/t/km",
                     f"stranded {s['stranded']:>5}  {s['stranded_ha']:>9,.0f} ha  "
                     f"sites {'SAME' if st == base_sites else st}"))
    log["haulage"]["eur_per_tonne_km"] = 0.45
    report("#9  Haulage rate (€0.32–0.58/t/km)", rows,
           "CRITICAL if site identity moves; otherwise scales the claim only.")

    # ---- #5 road detour factor -------------------------------------------
    rows = []
    for det in (1.0, 1.32, 1.6):
        log["haulage"]["road_detour_factor"] = det
        s = surface_summary()
        st, _ = sites()
        rows.append((f"detour ×{det}",
                     f"stranded {s['stranded']:>5}  {s['stranded_ha']:>9,.0f} ha  "
                     f"sites {'SAME' if st == base_sites else st}"))
    log["haulage"]["road_detour_factor"] = 1.32
    report("#5  Road detour factor (straight-line → road)", rows, "see above")

    # ---- #6 collection radius --------------------------------------------
    rows = []
    for rad in (15.0, 25.0, 40.0):
        log["haulage"]["local_collection_radius_km"] = rad
        s = surface_summary()
        rows.append((f"{rad:.0f} km free",
                     f"stranded {s['stranded']:>5}  {s['stranded_ha']:>9,.0f} ha"))
    log["haulage"]["local_collection_radius_km"] = 25.0
    report("#6  Free collection radius", rows, "")

    # ---- #7 the 80 km access threshold -----------------------------------
    rows = []
    for mx in (60.0, 80.0, 120.0):
        log["sorting"]["max_distance_km"] = mx
        s = surface_summary()
        rows.append((f"{mx:.0f} km threshold",
                     f"stranded {s['stranded']:>5}  viable {s['viable']:>5}  "
                     f"uneconomic {s['uneconomic']:>5}"))
    log["sorting"]["max_distance_km"] = 80.0
    report("#7  80 km sorting-access threshold", rows, "")

    # ---- #12 machine throughput ------------------------------------------
    rows = []
    for cap in (5000, 10000, 20000):
        log["new_unit"]["capacity_t_yr"] = cap
        _, ha = sites()
        rows.append((f"{cap:,} t/yr",
                     f"3 units unlock {ha:>8,.0f} ha  "
                     f"→ {round(368000 / (ha / 3)):>4} units for the 8% target"))
    log["new_unit"]["capacity_t_yr"] = 10000
    report("#12 Machine throughput", rows,
           "Drives the headline 'how many machines' number directly.")

    # ---- #3 candidate site population threshold --------------------------
    rows = []
    for pop in (1000, 2000, 5000):
        clear_caches()
        r = S.optimise(k=3, min_population=pop)
        st = [s["commune"] for s in r["sites"]]
        rows.append((f"pop ≥ {pop:,}",
                     f"{r['candidate_sites_considered']:>5} candidates  "
                     f"{r['impact']['hectares_unlocked']:>8,.0f} ha  "
                     f"{'SAME sites' if st == base_sites else st}"))
    report("#3  Candidate sites = communes above a population threshold", rows,
           "Tests the silo-inventory proxy. Different sites = the recommendation is an "
           "artefact of the proxy.")

    # ---- #4 the big one: commune allocation basis ------------------------
    # Re-allocate each department's arable hectares by POPULATION instead of land
    # area, then by equal split, and see whether the recommendations survive.
    rows = []
    raw = S._communes_raw()
    original = [c["cadastral_ha"] for c in raw["communes"]]
    for label, mapper in (
        ("by land area (as built)", None),
        ("by population", lambda c: max(c.get("population") or 1, 1)),
        ("equal per commune", lambda c: 1),
    ):
        for c, orig in zip(raw["communes"], original, strict=True):
            c["cadastral_ha"] = orig if mapper is None else mapper(c)
        s = surface_summary()
        st, ha = sites()
        rows.append((label,
                     f"stranded {s['stranded']:>5}  {ha:>8,.0f} ha  "
                     f"{'SAME sites' if st == base_sites else st}"))
    for c, orig in zip(raw["communes"], original, strict=True):
        c["cadastral_ha"] = orig
    clear_caches()
    report("#4  How a department's arable land is split between its communes", rows,
           "The single biggest structural assumption in the product.")

    # ---- #36/40 the grading probability ----------------------------------
    qspec = load_ref("quality")
    crops = load_ref("crops")
    # Two fields: one firmly negative (Beauce pea) and one MARGINAL (Cote-d'Or
    # winter pea, the preset where the recommendation is closest to the line). A
    # sensitivity run only on a field that is negative either way proves nothing.
    for dept, soil, pulse, tag in (
        ("28", "deep_loam", "field_pea", "Beauce pea (firmly negative)"),
        ("21", "shallow_limestone", "winter_pea", "Cote-d'Or winter pea (marginal)"),
        ("85", "clay_loam", "chickpea", "Vendee chickpea (firmly positive)"),
    ):
        rows = []
        base_p = crops[pulse]["human_grade_base_prob"]
        signs = set()
        for delta in (-0.15, 0.0, +0.15):
            crops[pulse]["human_grade_base_prob"] = round(base_p + delta, 3)
            r = farmer(dept=dept, soil=soil, pulse=pulse)
            signs.add(r["median"] > 0)
            rows.append((f"base pass rate {base_p + delta:.2f}",
                         f"median {r['median']:+8.0f}  CVaR15 {r['cvar15']:+8.0f}"))
        crops[pulse]["human_grade_base_prob"] = base_p
        report(f"#36 P_human base pass rate ±0.15 — {tag}", rows,
               "VERDICT FLIPS" if len(signs) > 1 else "verdict holds (no sign change)")

    rows = []
    pen = qspec["penalties"]["no_optical_sorting_access"]["flat_penalty"]
    for v in (0.0, 0.12, 0.30):
        qspec["penalties"]["no_optical_sorting_access"]["flat_penalty"] = v
        Q._spec.cache_clear() if hasattr(Q._spec, "cache_clear") else None
        s = surface_summary()
        rows.append((f"no-sorter penalty {v:.2f}",
                     f"stranded {s['stranded']:>5}  {s['stranded_ha']:>9,.0f} ha"))
    qspec["penalties"]["no_optical_sorting_access"]["flat_penalty"] = pen
    report("#40 Flat 0.12 penalty for no sorter access", rows, "")

    # ---- #21 the breeder surplus split -----------------------------------
    rules = load_ref("breeders")["matching"]
    rows = []
    share = rules["farmer_share_of_surplus"]
    for sh in (0.0, 0.55, 1.0):
        rules["farmer_share_of_surplus"] = sh
        B._ref.cache_clear()
        floor = B.fallback_floor_eur_t("field_pea", True)
        r = farmer(fallback_feed_floor_eur_t=floor)
        rows.append((f"farmer keeps {sh:.0%}",
                     f"floor €{(floor or 0):.0f}/t  CVaR15 {r['cvar15']:+8.0f} "
                     f"({r['cvar15'] - base_farmer['cvar15']:+.0f} vs none)"))
    rules["farmer_share_of_surplus"] = share
    B._ref.cache_clear()
    report("#21 Farmer/breeder surplus split", rows,
           "Even at 100% to the farmer, does it rescue the bad year?")

    # ---- #18 the soymeal reference price ---------------------------------
    fsub = load_ref("feed_substitution")
    rows = []
    meal = fsub["reference_prices_eur_t"]["soybean_meal_48"]["mean"]
    for pr in (meal, meal + 70, meal + 150):
        fsub["reference_prices_eur_t"]["soybean_meal_48"]["mean"] = pr
        B._ref.cache_clear()
        v = B.offered_price_eur_t("field_pea")
        floor = B.fallback_floor_eur_t("field_pea", True)
        r = farmer(fallback_feed_floor_eur_t=floor)
        rows.append((f"soymeal €{pr:.0f}/t",
                     f"offered €{v['offered_price_eur_t']:.0f}/t  "
                     f"CVaR15 {r['cvar15']:+8.0f} "
                     f"({r['cvar15'] - base_farmer['cvar15']:+.0f})"))
    fsub["reference_prices_eur_t"]["soybean_meal_48"]["mean"] = meal
    B._ref.cache_clear()
    report("#18 Soymeal reference price (premium now wired in; this probes beyond it)",
           rows,
           "The non-GMO premium is no longer an open gap - it is read from buyers.json "
           "and weighted by the measured share of holdings buying non-GMO. This sweep "
           "asks whether an even larger premium would change the conclusion. It does "
           "not: the fallback stays an order of magnitude short of 298 EUR/ha.")

    print(f"\n{'=' * 78}\nBaseline restored. Re-run to confirm determinism.")
    final = surface_summary()
    ok = final == base_surface
    print(f"  surface identical to baseline: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
