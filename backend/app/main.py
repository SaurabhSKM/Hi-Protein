"""FastAPI application for the Protein Sovereignty Decision & Offtake Engine."""
from __future__ import annotations

import contextlib
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

# Aliased: `cache` in this module is already the external-HTTP response cache client.
from functools import cache as memoise

import numpy
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .clients import agribalyse, cache, ign_rpg
from .config import (
    API_PREFIX,
    CORS_ORIGINS,
    DEFAULT_N_SIMULATIONS,
    ML_ARTIFACT_DIR,
    OFFLINE,
    PROJECT_ROOT,
    buyers_ref,
    crops,
    departments,
    load_ref,
    pac,
    pulse_crops,
    soils,
)
from .routers.adoption import router as adoption_router
from .schemas import (
    ClimateHorizon,
    ClimateOutlookResponse,
    ClimateOutlookRow,
    DepartmentOverview,
    DossierResponse,
    FoodDemandResponse,
    ParcelLookupRequest,
    ParcelLookupResponse,
    Provenance,
    RankCandidatesResponse,
    RegionalOverviewResponse,
    RegionFoodBalance,
    SimulateRotationRequest,
    SimulateRotationResponse,
    SorterOptimiseRequest,
)
from .services import (
    breeders,
    climate,
    demand,
    logistics,
    ml,
    offtake,
    orchestrator,
    rotations,
    rpg_codes,
    siting,
    weather,
)

_NOW = lambda: datetime.now(UTC).isoformat(timespec="seconds")  # noqa: E731


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm every lazy loader at startup. The yield model takes about 1.7 s to
    # unpickle; paying that on the first request would make the live demo look slow.
    t0 = time.perf_counter()
    ml.bundle()
    weather.panel()
    # A cold Agribalyse cache must never block startup; the client falls back to
    # its local reference table and says so in the response provenance.
    with contextlib.suppress(Exception):
        agribalyse.warm_cache()

    # Warm the derived caches too, but ONLY what the bake actually covers. Every one
    # of these is a disk read and some array arithmetic when the bake is present, so
    # startup stays well under a second; where the bake is missing the warm-up is
    # skipped deliberately rather than quietly running a 2-minute Monte Carlo here.
    bake = siting.bake_status()
    app.state.bake = bake
    warmed: list[str] = []
    if bake["present"]:
        with contextlib.suppress(Exception):
            siting.classify()
            _regional_overview()
            warmed.append("regional-overview")
        for h in bake["horizons"]:
            with contextlib.suppress(Exception):
                _food_demand(400, h)
                warmed.append(f"food-demand:{h}")
    else:
        print(
            f"WARNING: no baked department profiles at {bake['path']}.\n"
            "  The regional and food views will fall back to computing the Monte Carlo\n"
            "  inside the first request, which takes minutes. Run `make profiles`.",
            flush=True,
        )
    app.state.warmed = warmed
    app.state.warmup_ms = round(1000 * (time.perf_counter() - t0), 1)
    app.state.model_trained = ml.is_trained()
    yield


app = FastAPI(
    title="Hi-Protein - Food Protein Decision & Offtake Engine",
    description=(
        "Answers which French fields can grow the plant proteins people in France will "
        "eat, and whether the farmer earns a living doing it.\n\n"
        "The pivotal number is the probability that a lot clears human-food "
        "specification. Below it the harvest goes to animal feed at roughly a third of "
        "the price, so that probability - driven by July harvest rain, May insect "
        "pressure and whether an optical sorter is within haulage range - is what "
        "decides both the farmer's income and whether the crop feeds anyone.\n\n"
        "Built on real French open data: Agreste SAA departmental yields, Meteo-France "
        "climate series, IGN RPG parcel geometry and ADEME Agribalyse impacts. Every "
        "numeric block carries a provenance field stating whether it is a live "
        "measurement, a model output or an assumption. Demand is served by "
        "/food-demand; the forward climate question by /climate-outlook."
    ),
    version="1.1.0",
    lifespan=lifespan,
)
# The commune surface is 18,157 rows and about 5.4 MB of JSON. It compresses to well
# under a megabyte, and a conference wifi connection is exactly where that matters.
# API responses must never be served from the browser cache.
#
# These are GETs with no cache headers, which leaves the browser free to reuse an old
# payload indefinitely. That cost real time: after the department rotations were
# corrected and the profiles re-baked, the regional map kept rendering the previous
# numbers through repeated reloads, because the JSON was coming from cache while the
# (content-hashed) bundle was correctly fresh. During a live demo that failure mode is
# worse than slow - it shows stale figures with no indication they are stale.
#
# Static assets are deliberately left alone: their filenames are content-hashed, so
# caching them is correct and desirable.
@app.middleware("http")
async def _no_store_api(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if API_PREFIX in path or path.endswith("/health"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(adoption_router, prefix=API_PREFIX)


FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "offline_mode": OFFLINE,
        "model_trained": ml.is_trained(),
        "model_version": ml.model_version(),
        "weather_departments": len(weather.available_departments()),
        "warmup_ms": getattr(app.state, "warmup_ms", None),
        # Which derived caches are hot, and what the profile bake covers. Both are the
        # first thing to check when a view is slow: a missing horizon here is the
        # difference between a dictionary lookup and a live Monte Carlo.
        "warmed": getattr(app.state, "warmed", []),
        "profile_bake": getattr(app.state, "bake", None) or siting.bake_status(),
        "cache": cache.stats(),
        "time": _NOW(),
    }


@app.post(f"{API_PREFIX}/simulate-rotation", response_model=SimulateRotationResponse)
def simulate_rotation(req: SimulateRotationRequest) -> SimulateRotationResponse:
    unknown = [c for c in req.baseline_rotation if c not in crops()]
    if unknown:
        raise HTTPException(422, f"Unknown crop(s) in baseline_rotation: {unknown}")
    if req.candidate_pulse_year2 not in crops():
        raise HTTPException(422, f"Unknown crop '{req.candidate_pulse_year2}'")
    if crops()[req.candidate_pulse_year2].get("family") not in {"pulse", "forage_legume"}:
        raise HTTPException(
            422,
            f"'{req.candidate_pulse_year2}' is not a legume. Candidates: {pulse_crops()}",
        )
    try:
        return orchestrator.run(req)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e)) from e


@app.post(f"{API_PREFIX}/rank-candidates", response_model=RankCandidatesResponse)
def rank_candidates(req: SimulateRotationRequest) -> RankCandidatesResponse:
    """Rank every eligible pulse for this parcel, not just the one the user guessed."""
    t0 = time.perf_counter()
    try:
        ranked = orchestrator.rank_candidates(req)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    return RankCandidatesResponse(
        department_code=req.department_code,
        soil_type=req.soil_type,
        ranked=ranked,
        compute_ms=round(1000 * (time.perf_counter() - t0), 1),
    )


@app.post(f"{API_PREFIX}/parcel", response_model=ParcelLookupResponse)
def parcel_lookup(req: ParcelLookupRequest) -> ParcelLookupResponse:
    """Resolve a map click to a real RPG parcel and its declared crop history."""
    res = ign_rpg.parcel_history(req.lon, req.lat, req.years)
    rotation = ign_rpg.inferred_rotation(res["history"])
    dept = None
    if res["found"]:
        ids = [h.get("id_parcel") for h in res["history"] if h.get("id_parcel")]
        # RPG does not return a department code, so infer it from the nearest
        # pilot department centroid rather than inventing one.
        best, bestd = None, 1e9
        for code, d in departments().items():
            dd = offtake.haversine_km((req.lon, req.lat), tuple(d["centroid"]))
            if dd < bestd:
                best, bestd = code, dd
        dept = best if bestd < 120 else None
        del ids
    return ParcelLookupResponse(
        found=res["found"],
        department_code=dept,
        geometry=res["geometry"],
        surface_ha=res["surface_ha"],
        history=res["history"],
        inferred_rotation=rotation,
        inferred_soil_type=(departments().get(dept, {}) or {}).get("dominant_soil") if dept else None,
        provenance=Provenance(
            source="IGN API Carto, module RPG v2 (apicarto.ign.fr/api/rpg/v2)",
            mode=res["mode"],
            retrieved_at=res["retrieved_at"],
            caveat=(
                "RPG records the DECLARED main crop per campaign and carries no soil or "
                "yield data. The department and soil archetype are inferred from the "
                "parcel location, so confirm the soil type before relying on the result."
            ),
        ),
    )


@app.get(f"{API_PREFIX}/regional-overview", response_model=RegionalOverviewResponse)
def regional_overview() -> RegionalOverviewResponse:
    """Department-level adoption, conversion potential and infrastructure gaps.

    Reads the baked department profiles rather than running a Monte Carlo per
    department. With six pilot departments running them live cost about four seconds;
    with forty-two it was over two minutes, which is not a dashboard. The profiles are
    the SAME simulation, run by scripts/build_region_profiles.py at higher path counts
    than a live request could afford, and the siting optimiser reads the identical
    numbers - so the map, the table and the optimiser cannot disagree with each other.
    """
    t0 = time.perf_counter()
    # `compute_ms` is restated per request so it reports what THIS call cost rather than
    # the frozen cost of whichever call first populated the cache.
    return _regional_overview().model_copy(
        update={"compute_ms": round(1000 * (time.perf_counter() - t0), 1)}
    )


@memoise
def _regional_overview() -> RegionalOverviewResponse:
    """Assembled regional overview, memoised for the life of the process.

    The rollup is cheap next to the Monte Carlo, but it walks the 18,157-row commune
    surface on every call to produce a result that cannot change, and this response is
    what the regional map renders from.
    """
    t0 = time.perf_counter()
    meta = load_ref("departments")["_meta"]["national_target"]
    tgt = float(meta["target_pulse_share_pct"])
    prof = siting.profiles()
    surface = siting.classify()

    # Per-department rollup of the commune surface.
    per_dept: dict[str, dict] = {}
    for c in surface["communes"]:
        agg = per_dept.setdefault(
            c["dept"], {"stranded": 0, "stranded_ha": 0.0, "conv_ha": 0.0, "n": 0}
        )
        agg["n"] += 1
        agg["conv_ha"] += c["convertible_ha"]
        if c["status"] == "stranded":
            agg["stranded"] += 1
            agg["stranded_ha"] += c["convertible_ha"]

    rows: list[DepartmentOverview] = []
    total_gap, total_pot = 0.0, 0.0
    radius = float(logistics.ref()["haulage"]["local_collection_radius_km"])

    for code, d in departments().items():
        p = prof["profiles"].get(code)
        if not p:
            continue
        acc = logistics.access(tuple(d["centroid"]))
        km = acc["road_km"]
        # Counted at the distance this department actually has, not at zero haulage,
        # because that is the number a planner would act on.
        n_pos = sum(
            1 for c in p.get("candidates", [])
            if float(siting.delta_at_km(c, km if km is not None else 0.0)) > 0
        )
        delta_now = float(siting.delta_at_km(p, km if km is not None else 0.0))
        delta_served = float(siting.delta_at_km(p, radius))
        haul = delta_served - delta_now

        gap = max(d["arable_ha"] * tgt / 100.0 - d["pulse_ha"], 0.0)
        pot = gap * delta_now
        agg = per_dept.get(code, {})
        total_gap += gap
        total_pot += pot
        rows.append(DepartmentOverview(
            department_code=code, name=d["name"], region_name=d["region_name"],
            centroid=d["centroid"], arable_ha=float(d["arable_ha"]),
            pulse_ha=float(d["pulse_ha"]),
            pulse_share_pct=round(100.0 * d["pulse_ha"] / max(d["arable_ha"], 1), 3),
            target_share_pct=tgt, gap_ha=round(gap, 1), best_pulse=p["pulse"],
            n_candidates_profitable=n_pos,
            any_candidate_profitable=bool(n_pos > 0),
            median_margin_gain_eur_ha=round(delta_now, 1),
            prob_gain_positive=round(float(p["access"]["prob_gain"]), 4),
            conversion_potential_eur=round(pot, 0),
            has_optical_sorting_within_80km=bool(acc["within_range"]),
            dominant_soil=d["dominant_soil"],
            baseline_rotation=rotations.baseline_rotation(code),
            displaced_year2_crop=rotations.displaced_crop(code),
            baseline_rotation_caveat=rotations.caveat(code),
            sorter_road_km=km,
            haulage_cost_eur_ha=round(haul, 1),
            margin_gain_if_served_eur_ha=round(delta_served, 1),
            is_infrastructure_limited=bool(delta_now < 0 <= delta_served),
            stranded_communes=int(agg.get("stranded", 0)),
            stranded_ha=round(float(agg.get("stranded_ha", 0.0)), 0),
            convertible_ha=round(float(agg.get("conv_ha", 0.0)), 0),
            n_communes=int(agg.get("n", 0)),
        ))

    rows.sort(key=lambda r: -r.conversion_potential_eur)
    return RegionalOverviewResponse(
        national_current_share_pct=float(meta["current_pulse_share_pct"]),
        national_target_share_pct=tgt,
        target_year=int(meta["target_year"]),
        departments=rows,
        total_gap_ha=round(total_gap, 1),
        total_conversion_potential_eur=round(total_pot, 0),
        surface_totals=surface["totals"],
        # The headline is a range, not a point: the stranded figure is driven by a
        # published haulage BAND, and quoting its midpoint to five figures is false
        # precision that will not survive a challenge.
        stranded_band=siting.stranded_band(),
        provenance=Provenance(
            source=(
                "Arable and pulse areas from the Agreste SAA departmental area series "
                f"(mean of 2022-2024). Economics from {prof['_meta']['n_simulations']} "
                "paired Monte Carlo paths per department, baked by "
                "scripts/build_region_profiles.py. Commune geometry from IGN "
                "ADMINEXPRESS."
            ),
            mode="model_output",
            retrieved_at=_NOW(),
            caveat=(
                "One soil archetype and one baseline rotation per department. A real "
                "parcel should be run through /simulate-rotation with its own soil and "
                f"RPG history. Profiles loaded from: {prof['_meta'].get('loaded_from')}."
            ),
        ),
        compute_ms=round(1000 * (time.perf_counter() - t0), 1),
    )


@app.get(f"{API_PREFIX}/stranded-surface")
def stranded_surface(
    department_code: str | None = Query(None),
    region_code: str | None = Query(None),
    status: str | None = Query(
        None, description="Filter to one status: viable, stranded, uneconomic."
    ),
    limit: int = Query(20000, ge=100, le=20000),
) -> dict:
    """Every commune in the demand surface, classified and priced.

    This is the "stranded potential" layer. The distinction that matters is between
    `uneconomic` - a pulse does not pay here even with a sorter next door, so the limit
    is agronomy or market - and `stranded` - a pulse does not pay at the distance this
    land actually has, but would with a unit in range. Only the second is something a
    capital grant can fix, and conflating them is how infrastructure money gets spent in
    the wrong place.
    """
    t0 = time.perf_counter()
    surface = siting.classify()
    rows = surface["communes"]
    if department_code:
        rows = [r for r in rows if r["dept"] == department_code]
    if region_code:
        depts = departments()
        rows = [
            r for r in rows if depts.get(r["dept"], {}).get("region_code") == region_code
        ]
    if status:
        rows = [r for r in rows if r["status"] == status]

    truncated = len(rows) > limit
    return {
        "n_total": surface["n"],
        "n_returned": min(len(rows), limit),
        "truncated": truncated,
        "communes": rows[:limit],
        "totals": surface["totals"],
        "existing_sorting_units": logistics.existing_units(),
        "legend": {
            "viable": "A pulse pays at the sorter distance this land actually has.",
            "stranded": (
                "A pulse does NOT pay at the distance it has, but WOULD with a sorter in "
                "range. Infrastructure-limited land: the only category capital can fix."
            ),
            "uneconomic": (
                "A pulse does not pay even with a sorter next door. The limit is "
                "agronomy or market, not infrastructure."
            ),
            "at_or_above_target": "Already at or past the 8 percent pulse share.",
            "unmodelled": "No viable pulse profile for this department.",
        },
        "provenance": {
            "source": (
                "IGN ADMINEXPRESS commune geometry and cadastral area; Agreste SAA "
                "departmental arable and pulse area; paired Monte Carlo economics per "
                "department."
            ),
            "mode": "model_output",
            "retrieved_at": _NOW(),
            "caveat": (
                "A department's arable hectares are split between its communes in "
                "proportion to cadastral area, because Agreste publishes nothing at "
                "commune level to measure that split against. The allocation is right on "
                "average and wrong for any individual commune - a commune that is mostly "
                "forest is credited with arable land it does not have. TESTED rather than "
                "assumed safe: re-allocating by population, or equally per commune, "
                "leaves the stranded commune count identical and the hectares unlocked "
                "within 1 percent. Only the NAMED commune changes, which is why a siting "
                "result should be read as a catchment rather than an address."
            ),
        },
        "compute_ms": round(1000 * (time.perf_counter() - t0), 1),
    }


@app.post(f"{API_PREFIX}/optimise-sorters")
def optimise_sorters(req: SorterOptimiseRequest) -> dict:
    """Site up to k new optical sorters where they unlock the most convertible land.

    Capacitated facility location. The objective is the convertible-hectare-weighted
    improvement in three-year margin advantage from being served by a nearer sorter; the
    algorithm is greedy marginal gain, which carries a (1 - 1/e) worst-case guarantee
    because that objective is monotone submodular. Pass `verify_milp` to also solve the
    problem exactly with HiGHS and see the realised gap, which has been under one
    percent on every scope tested.
    """
    out = siting.optimise(
        k=req.k,
        min_population=req.min_site_population,
        department=req.department_code,
        region_code=req.region_code,
        verify_milp=req.verify_milp,
    )
    if "error" in out:
        raise HTTPException(status_code=422, detail=out["error"])
    return out


@app.get(f"{API_PREFIX}/breeders")
def nearby_breeders(
    lon: float = Query(..., ge=-5.5, le=9.8),
    lat: float = Query(..., ge=41.0, le=51.5),
    pulse: str = Query("field_pea"),
    downgraded_lot_t: float = Query(50.0, ge=0.0, le=5000.0),
) -> dict:
    """Livestock holdings that would take a downgraded lot from this point.

    Exposed separately from /simulate-rotation so the map can show the counterparties
    without re-running a Monte Carlo, and so the breeder side of the trade can be
    inspected on its own.
    """
    if pulse not in crops():
        raise HTTPException(status_code=422, detail=f"Unknown crop '{pulse}'")
    out = breeders.match(
        pulse=pulse, dept_code="", point=(lon, lat), downgraded_lot_t=downgraded_lot_t,
        max_matches=8,
    )
    out["directory_status"] = load_ref("breeders")["_meta"]["status"]
    out["what_is_real"] = load_ref("breeders")["_meta"]["what_is_real"]
    out["what_is_not_real"] = load_ref("breeders")["_meta"]["what_is_not_real"]
    return out


@app.get(f"{API_PREFIX}/food-demand", response_model=FoodDemandResponse)
def food_demand(
    n_simulations: int = Query(400, ge=200, le=2000),
    climate_horizon: ClimateHorizon = Query("observed"),
) -> FoodDemandResponse:
    """The demand side: can each region grow the pulses its own population eats?

    Supply is a POTENTIAL, not a forecast. It asks: if a department closed its gap to
    the area target, how many tonnes would clear human-food specification? That is the
    question a Region can act on, because the deficit converts straight into hectares,
    sorting capacity, or a contract volume.

    Two supply figures are returned per region and the gap between them is the point.
    One closes the area gap with the pulse that pays the farmer best; the other with
    the pulse that feeds the most people. Where they diverge, the current incentive
    structure is buying area rather than food, and a Region can see exactly how much
    food that costs.
    """
    t0 = time.perf_counter()
    return _food_demand(n_simulations, str(climate_horizon)).model_copy(
        update={"compute_ms": round(1000 * (time.perf_counter() - t0), 1)}
    )


@memoise
def _food_demand(n_simulations: int, climate_horizon: str) -> FoodDemandResponse:
    """Assembled food-demand response, memoised per (paths, horizon).

    Every input is either reference data or a baked profile, so the answer cannot
    change while the process runs. Caching the assembled response - not just the
    profiles underneath it - is what makes switching horizons in the food view
    instant on the second visit rather than merely tolerable.
    """
    t0 = time.perf_counter()
    tgt = float(load_ref("departments")["_meta"]["national_target"]["target_pulse_share_pct"])
    by_region: dict[str, dict] = {}
    # Baked simulations, for EVERY horizon rather than only the observed one. The bake
    # used to cover `observed` alone, so picking any projected horizon dropped the whole
    # endpoint onto the live path - 42 departments x 6 pulses, about 71 seconds, on
    # every request - which is why the food view appeared broken rather than slow.
    prof = siting.profiles(climate_horizon)
    baked = prof["profiles"]
    # Departments the bake found to have NO agronomically viable pulse. Without this,
    # "absent from the bake" means both "no legume grows here" and "never baked", so
    # the loop below re-simulated Tarn and Tarn-et-Garonne on every single request only
    # to rediscover that their soil is too acid - about 3 seconds, every time, discarded.
    unviable = siting.unviable_departments(climate_horizon)

    for code, d in departments().items():
        region = d.get("region_code")
        if not region or demand.region_requirement(region) is None:
            continue
        soil = d["dominant_soil"]
        # Per-department, from that department's own Agreste area shares. The year-2
        # crop is the one the pulse displaces and dominates the margin difference.
        base = rotations.baseline_rotation(code)
        gap_ha = max(d["arable_ha"] * tgt / 100.0 - d["pulse_ha"], 0.0)

        best_margin: tuple[str, float, float] | None = None
        best_food: tuple[str, float, float] | None = None

        if code in unviable and code not in baked:
            continue
        if code in baked:
            for c in baked[code]["candidates"]:
                cand = c["pulse"]
                margin = float(c["access"]["delta0_eur_ha"])
                # Tonnes per hectare that reach a human plate: the graded food fraction
                # times the crop's structural share of the food market. A perfectly
                # graded fava bean crop still mostly goes to feed, because that is where
                # the demand is.
                food_t_ha = float(c["access"]["food_t_per_ha"]) * demand.food_market_share(cand)
                if best_margin is None or margin > best_margin[1]:
                    best_margin = (cand, margin, food_t_ha)
                if best_food is None or food_t_ha > best_food[2]:
                    best_food = (cand, margin, food_t_ha)
        else:
            for cand in pulse_crops():
                req = SimulateRotationRequest(
                    department_code=code, area_ha=50.0, soil_type=soil,
                    baseline_rotation=base, candidate_pulse_year2=cand,
                    n_simulations=n_simulations, random_seed=20260131,
                    climate_horizon=climate_horizon,
                )
                try:
                    r = orchestrator.run(req)
                except Exception:  # noqa: BLE001
                    continue
                if r.agronomic_validation.severity == "blocked" or r.food_outcome is None:
                    continue
                margin = r.financial_3yr_comparison_per_ha.risk.median_delta_eur_ha
                # Per-hectare food tonnage, so the 50 ha probe scales to the real gap.
                food_t_ha = r.food_outcome.food_grade_tonnes_median / req.area_ha
                if best_margin is None or margin > best_margin[1]:
                    best_margin = (cand, margin, food_t_ha)
                if best_food is None or food_t_ha > best_food[2]:
                    best_food = (cand, margin, food_t_ha)
        if best_margin is None or best_food is None:
            continue

        has_sort, _ = offtake.optical_sorting_access(code, None)
        slot = by_region.setdefault(
            region, {"margin_t": 0.0, "food_t": 0.0, "depts": [], "sorting": True}
        )
        slot["margin_t"] += gap_ha * best_margin[2]
        slot["food_t"] += gap_ha * best_food[2]
        slot["sorting"] = slot["sorting"] and has_sort
        # Is the food-optimal pick resting on this department's own yield history, or
        # on one borrowed from elsewhere? The farmer tab warns about borrowed baselines
        # and this view did not, which meant the same weak number was flagged in one
        # place and presented as solid in another. Chickpea wins this column in 39 of
        # 40 departments, and in 22 of them its baseline is borrowed - so the warning
        # is not a corner case here, it is most of the column.
        food_src = ml.baseline_source_for(best_food[0], code, soil)
        slot["depts"].append({
            "department_code": code, "name": d["name"], "gap_ha": round(gap_ha, 1),
            "best_margin_pulse": best_margin[0],
            "best_margin_eur_ha": round(best_margin[1], 1),
            "food_t_if_margin_optimised": round(gap_ha * best_margin[2], 0),
            "best_food_pulse": best_food[0],
            "best_food_margin_eur_ha": round(best_food[1], 1),
            "food_t_if_food_optimised": round(gap_ha * best_food[2], 0),
            "best_food_baseline_source": food_src,
            "best_food_baseline_is_local": ml.baseline_is_local(food_src),
            "best_food_baseline_caveat": ml.baseline_caveat(best_food[0], food_src),
            "has_optical_sorting_within_80km": has_sort,
        })

    rows: list[RegionFoodBalance] = []
    for region, slot in by_region.items():
        b = demand.balance(region, slot["food_t"])
        if b is None:
            continue
        rows.append(RegionFoodBalance(
            region_code=b["region_code"], region_name=b["region_name"],
            population_millions=b["population_millions"],
            current_demand_t=b["current_demand_t"],
            recommended_demand_t=b["recommended_demand_t"],
            suppliable_food_grade_t=b["suppliable_food_grade_t"],
            coverage_of_current_demand_pct=b["coverage_of_current_demand_pct"],
            coverage_of_recommended_demand_pct=b["coverage_of_recommended_demand_pct"],
            deficit_vs_current_t=b["deficit_vs_current_t"],
            deficit_vs_recommended_t=b["deficit_vs_recommended_t"],
            collective_catering_t=b["catering"]["all_collective_catering_t"],
            school_catering_t=b["catering"]["school_catering_t"],
            covers_collective_catering=b["covers_collective_catering"],
            catering_coverage_pct=b["catering_coverage_pct"],
            departments=slot["depts"],
            best_pulse=(slot["depts"][0]["best_food_pulse"] if slot["depts"] else None),
            has_optical_sorting=slot["sorting"],
        ))
    rows.sort(key=lambda r: -(r.deficit_vs_current_t))

    nat = demand.national()
    tot_food = sum(r.suppliable_food_grade_t for r in rows)
    tot_margin = sum(s["margin_t"] for s in by_region.values())
    tot_cur = sum(r.current_demand_t for r in rows)
    tot_rec = sum(r.recommended_demand_t for r in rows)
    lost = max(tot_food - tot_margin, 0.0)

    return FoodDemandResponse(
        national=nat,
        regions=rows,
        climate_horizon=climate_horizon,
        supply_basis=(
            "Gap-to-target hectares in each pilot department, grown with the best-fit "
            "pulse at the engine's own modelled yield, multiplied by the sampled "
            "human-grade fraction and the crop's human-food market share. A potential "
            "under the area target, not a production forecast."
        ),
        total_suppliable_food_grade_t=round(tot_food, 0),
        total_current_demand_t=round(tot_cur, 0),
        total_recommended_demand_t=round(tot_rec, 0),
        finding=(
            "Across these regions, closing the area gap with the pulse that pays best "
            f"would grade about {tot_margin:,.0f} t for human food; closing it with the "
            f"pulse that FEEDS best would grade about {tot_food:,.0f} t - a difference of "
            f"{lost:,.0f} t, which is food the current incentive structure leaves on the "
            f"table. Either way it is set against {tot_cur:,.0f} t these regions eat today "
            f"and {tot_rec:,.0f} t they would eat at the recommended intake. Nationally, "
            f"French farms supply {nat['self_sufficiency_current_pct']:.0f}% of the dry "
            "pulses on French plates."
        ),
        provenance=Provenance(
            source=(
                "Demand from INSEE population and the PNNS pulse recommendation "
                "(refdata/food_demand.json); supply from this engine's yield and grading "
                "models over department gap-to-target areas. Department economics read "
                f"from the {prof['_meta'].get('loaded_from')} profile cache at "
                f"{prof['_meta'].get('n_simulations')} paths per department."
            ),
            mode="model_output",
            retrieved_at=_NOW(),
            caveat=(
                "Current intake is a central estimate in a 1.7-2.5 kg per capita band, "
                "not a measured market balance. Regional catering volumes are the "
                "national meal count scaled by population, because meal counts are only "
                "published nationally. Supply assumes the area target is met and that "
                "rotation return intervals allow it, which the eligibility question "
                "(not yet computed at scale) may not support."
            ),
        ),
        compute_ms=round(1000 * (time.perf_counter() - t0), 1),
    )


@app.get(f"{API_PREFIX}/climate-outlook", response_model=ClimateOutlookResponse)
def climate_outlook(
    department_code: str = Query("28"),
    crop_key: str = Query("green_lentil", alias="crop"),
    soil_type: str = Query("deep_loam"),
    n_simulations: int = Query(800, ge=200, le=3000),
) -> ClimateOutlookResponse:
    """The same parcel decision, re-run at each forward climate horizon.

    This is the 'tomorrow' clause made answerable. The engine's bootstrap answers for
    next spring; a sorting line or a 2030 area target has to survive 2050. Each row
    reruns the identical request with the season set shifted to that horizon's warming,
    so the rows differ only by climate.
    """
    t0 = time.perf_counter()
    if crop_key not in crops():
        raise HTTPException(422, f"Unknown crop '{crop_key}'")
    base = rotations.baseline_rotation(department_code)
    rows: list[ClimateOutlookRow] = []
    for h in climate.horizon_keys():
        req = SimulateRotationRequest(
            department_code=department_code, area_ha=1.0, soil_type=soil_type,
            baseline_rotation=base, candidate_pulse_year2=crop_key,
            n_simulations=n_simulations, random_seed=20260131, climate_horizon=h,
        )
        try:
            r = orchestrator.run(req)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"Horizon '{h}': {e}") from e
        # Re-sample the season set for this horizon purely to report the drivers the
        # reader needs in order to believe the row.
        s = weather.sample_seasons(
            department_code, n_simulations, numpy.random.default_rng(20260131),
            climate_horizon=h,
        )
        risk = r.financial_3yr_comparison_per_ha.risk
        fo = r.food_outcome
        cc = r.climate_context
        rows.append(ClimateOutlookRow(
            horizon=h,
            label_en=cc.label_en if cc else None,
            warming_level_c=cc.warming_level_c if cc else None,
            total_shift_applied_c=cc.total_shift_applied_c if cc else 0.0,
            yield_median_t_ha=r.ml_predictions_year2.yield_median_t_ha,
            prob_human_grade=r.ml_predictions_year2.prob_human_grade,
            human_grade_fraction_median=r.ml_predictions_year2.human_grade_fraction_median,
            food_grade_tonnes_per_ha=round(fo.food_grade_tonnes_median, 3) if fo else 0.0,
            median_delta_eur_ha=risk.median_delta_eur_ha,
            prob_gain_positive=risk.prob_pulse_beats_baseline,
            may_days_above_20c=round(float(s["may_days_above_20c"].mean()), 2),
            jun_heat_days_30c=round(float(s["jun_heat_days_30c"].mean()), 2),
            harvest_rain_mm=round(float(s["harvest_rain_mm"].mean()), 1),
            drought_stress_index=round(float(s["drought_stress_index"].mean()), 3),
        ))

    rep = climate.report()
    obs = next((r for r in rows if r.horizon == "observed"), None)
    far = next((r for r in rows if r.horizon == "tracc_2050"), None)
    finding = "Insufficient horizons computed to state a trend."
    if obs and far:
        d_food = (
            100.0 * (far.food_grade_tonnes_per_ha / obs.food_grade_tonnes_per_ha - 1.0)
            if obs.food_grade_tonnes_per_ha > 1e-9 else 0.0
        )
        finding = (
            f"Between the raw observed bootstrap and TRACC +2.7 C, May days above 20 C - "
            f"the bruchid egg-laying driver - rise from {obs.may_days_above_20c:.1f} to "
            f"{far.may_days_above_20c:.1f}, while harvest rain barely moves "
            f"({obs.harvest_rain_mm:.0f} to {far.harvest_rain_mm:.0f} mm) because it has "
            f"no measurable temperature response in the observed record. The food-grade "
            f"tonnage per hectare changes by {d_food:+.0f}% and the median margin by "
            f"{far.median_delta_eur_ha - obs.median_delta_eur_ha:+.0f} EUR/ha. So warming "
            "attacks this crop's FOOD fraction through insect pressure rather than through "
            "wetter harvests - which points at variety and pest tolerance, not drying."
        )
    return ClimateOutlookResponse(
        department_code=department_code, crop=crop_key, soil_type=soil_type,
        rows=rows, sensitivities=rep["sensitivities"], method=rep["method"],
        caveat=rep["caveat"], window_catchup_c=rep["window_catchup_c"],
        finding=finding,
        provenance=Provenance(
            source=rep["warming_source"],
            mode="model_output",
            retrieved_at=_NOW(),
            caveat=(
                rep["caveat"]
                + " The yield and grading relationships themselves were calibrated on the "
                "observed record; applying them at +2.7 C or +4 C extrapolates beyond "
                "their calibration range."
            ),
        ),
        compute_ms=round(1000 * (time.perf_counter() - t0), 1),
    )


@app.post(f"{API_PREFIX}/dossier", response_model=DossierResponse)
def dossier(req: SimulateRotationRequest) -> DossierResponse:
    """Printable advisor transition dossier for a farm visit."""
    r = orchestrator.run(req)
    v, m, f = r.agronomic_validation, r.ml_predictions_year2, r.financial_3yr_comparison_per_ha
    rules = load_ref("rotation_rules")
    window = rules["sowing_windows"].get(req.candidate_pulse_year2, {})
    spec = rules["quality_specs"].get(req.candidate_pulse_year2, {})

    checklist = [
        {"item": "Return interval respected",
         "status": "pass" if not v.blocking_reasons else "fail",
         "detail": f"{v.return_interval_years} years required; "
                   f"{v.observed_gap_years if v.observed_gap_years is not None else 'no host found'} observed."},
        {"item": "Soil pH and hydromorphy suitable",
         "status": "pass" if v.severity != "blocked" else "fail",
         "detail": "; ".join(v.blocking_reasons) or "Within tolerance for this crop."},
        {"item": "Soil Aphanomyces test",
         "status": "action_required" if v.disease_group == "aphanomyces" else "not_applicable",
         "detail": "Order a pot test before sowing. No rule table substitutes for it."},
        {"item": "Sowing window planned", "status": "info",
         "detail": v.sowing_window or "See crop guidance."},
        {"item": "Inoculant ordered", "status": "action_required",
         "detail": "Rhizobium inoculation is advisable on plots with no recent legume history."},
        {"item": "Offtake contract signed",
         "status": "action_required" if r.matched_offtake_contracts else "info",
         "detail": (
             f"Best match: {r.matched_offtake_contracts[0].buyer_name} at "
             f"{r.matched_offtake_contracts[0].contract_price_eur_t} EUR/t with a "
             f"{r.matched_offtake_contracts[0].fallback_feed_price_eur_t} EUR/t floor."
             if r.matched_offtake_contracts else "No buyer matched for this crop and region."
         )},
        {"item": "Nitrogen plan updated for year 3", "status": "action_required",
         "detail": (
             f"Deduct {f.breakdown_year2_year3_gains.nitrogen_saved_year3_eur:.0f} EUR/ha "
             "of nitrogen from the following crop's fertiliser plan. In a zone "
             "vulnerable this deduction is a regulatory requirement, not an option."
         )},
        {"item": "Harvest equipment checked", "status": "action_required",
         "detail": "Low cutting height and a flexible cutter bar are needed for lentil and chickpea; check stone risk."},
        # Added because the food outcome is the point, and on this checklist it is an
        # action: without sorting in haulage range, the food-grade share is capped
        # whatever the agronomy does.
        {"item": "Route to a human-food outlet confirmed",
         "status": "action_required" if (r.food_outcome and r.food_outcome.food_market_share > 0.5)
                   else "info",
         "detail": (
             f"{r.food_outcome.food_market_share:.0%} of this crop's French volume has a "
             f"human-food outlet, and {r.food_outcome.human_grade_fraction_median:.0%} of a "
             f"lot is expected to clear specification - about "
             f"{r.food_outcome.food_grade_tonnes_median:.1f} t here, feeding "
             f"{r.food_outcome.people_fed_at_recommended_intake:,.0f} people for a year at "
             f"the recommended intake. The food-versus-feed gap is "
             f"{r.food_outcome.food_grade_price_premium_eur_t:.0f} EUR/t, so confirm sorting "
             "access and a food buyer before sowing."
             if r.food_outcome else "Food outcome not computed."
         )},
    ]

    sections = [
        {"title": "Decision summary", "body": {
            "crop": r.crop_label_fr, "area_ha": r.area_ha,
            "median_gain_eur_ha": f.risk.median_delta_eur_ha,
            "probability_of_gain": f.risk.prob_pulse_beats_baseline,
            "worst_case_1_in_7_eur_ha": f.risk.delta_q15_eur_ha,
            "recommendation": (
                "Do not proceed until the blocking condition is resolved."
                if v.severity == "blocked"
                else "Proceed, with a contracted floor price."
                if f.risk.prob_pulse_beats_baseline >= 0.6
                else "Marginal. Proceed only with a contracted floor price and on your best-suited plot."
            ),
        }},
        {"title": "Agronomic screening", "body": {
            "severity": v.severity, "note": v.terres_inovia_note,
            "blocking": v.blocking_reasons, "warnings": v.warnings,
            "preceding_crop": v.preceding_crop,
            "preceding_crop_suitability": v.preceding_crop_suitability,
        }},
        {"title": "Yield and quality expectation", "body": {
            "yield_q15_t_ha": m.yield_q15_t_ha, "yield_median_t_ha": m.yield_median_t_ha,
            "yield_q85_t_ha": m.yield_q85_t_ha,
            "probability_human_grade": m.prob_human_grade,
            "breakeven_human_grade_fraction": f.risk.breakeven_human_grade_fraction,
            "model_version": m.model_version,
            "quality_specification": spec,
            "sowing_window": window,
        }},
        {"title": "Three-year economics per hectare", "body": {
            "baseline_median_eur": f.baseline_3yr_net_margin_eur,
            "pulse_median_eur": f.pulse_rotation_median_eur,
            "breakdown": f.breakdown_year2_year3_gains.model_dump(),
            "risk": f.risk.model_dump(),
        }},
        # Placed before the environment block on purpose: on a farm visit the
        # question "where does this crop actually go" comes before the carbon.
        {"title": "Where this harvest goes", "body": (
            r.food_outcome.model_dump() if r.food_outcome else {"note": "not computed"}
        )},
        {"title": "Climate assumed", "body": (
            r.climate_context.model_dump() if r.climate_context else {"note": "observed"}
        )},
        {"title": "Environment, feed-substitution tier", "body": {
            **r.environmental_impact.model_dump(),
            "counterfactual": (
                "Imported Brazilian soybean meal. This prices the fraction that does NOT "
                "clear food specification. The food-grade fraction's own counterfactual "
                "is an imported pulse and is reported in the section above."
            ),
        }},
        {"title": "Assumptions", "body": r.assumptions},
    ]

    return DossierResponse(
        parcel_id=req.parcel_id, generated_at=_NOW(),
        department=req.department_code, crop=r.crop_label_fr,
        sections=sections, agronomic_checklist=checklist,
        financial_summary=f.model_dump(),
        disclaimer=(
            "Decision-support prototype built at a hackathon. Figures are gross "
            "margins from public statistics and a model whose stated limitations are "
            "in /api/v1/model-report. PAC unit amounts are provisional. Buyer prices "
            "are illustrative demo data and are not commercial offers. This document "
            "does not replace advice from a Chamber of Agriculture or cooperative "
            "agronomist, nor a soil Aphanomyces test."
        ),
    )


@app.get(f"{API_PREFIX}/reference")
def reference() -> dict:
    """Everything the frontend needs to build its forms and legends in one call."""
    return {
        "crops": crops(),
        "pulse_crops": pulse_crops(),
        "soils": soils(),
        "departments": departments(),
        "national_target": load_ref("departments")["_meta"]["national_target"],
        "buyers": buyers_ref()["buyers"],
        "optical_sorting_units": buyers_ref()["optical_sorting_units"],
        "pac": pac(),
        "rpg_code_labels": rpg_codes.CODE_CULTU_LABELS,
        "defaults": {"n_simulations": DEFAULT_N_SIMULATIONS, "climate_horizon": "observed"},
        "weather_departments": weather.available_departments(),
        # The food and climate layers, so the frontend can build its selectors and
        # legends without a second round trip.
        "climate_horizons": [climate.horizon_detail(k) for k in climate.horizon_keys()],
        "food_demand_national": demand.national(),
        "crop_food_market": load_ref("food_demand")["crop_food_market"],
        "psn_area_target": load_ref("food_demand")["self_sufficiency_targets"]["psn_area_target"],
    }


@app.get(f"{API_PREFIX}/model-report")
def model_report() -> dict:
    """Validation metrics and the model's own stated limitations."""
    p = ML_ARTIFACT_DIR / "model_report.json"
    if not p.exists():
        raise HTTPException(503, "No trained model. Run ml/build_dataset.py then ml/train.py.")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get(f"{API_PREFIX}/yield-trend")
def yield_trend() -> dict:
    """Observed decline in pulse yields, straight from the Agreste training panel.

    Surfaced as an endpoint because it is the strongest single argument in the pitch
    AND the strongest caution: pulse yields really have fallen while cereals held flat,
    which is both why farmers hesitate and why the economics are tighter than the
    headline prices suggest.
    """
    import pandas as pd

    from .config import DATA_DIR

    p = DATA_DIR / "processed" / "training_panel.csv"
    if not p.exists():
        raise HTTPException(503, "Training panel not built. Run ml/build_dataset.py.")
    df = pd.read_csv(p, dtype={"dept_code": str})
    early = df[df.year.between(2010, 2016)].groupby("crop").yield_t_ha.mean()
    late = df[df.year.between(2018, 2024)].groupby("crop").yield_t_ha.mean()
    out = []
    for c in sorted(set(early.index) & set(late.index)):
        early_mean, late_mean = float(early[c]), float(late[c])
        out.append({
            "crop": c,
            "label_fr": crops().get(c, {}).get("label_fr", c),
            "is_legume": bool(crops().get(c, {}).get("is_legume", False)),
            "mean_2010_2016_t_ha": round(early_mean, 3),
            "mean_2018_2024_t_ha": round(late_mean, 3),
            "change_pct": round(100.0 * (late_mean / early_mean - 1.0), 2),
        })
    out.sort(key=lambda r: r["change_pct"])
    return {
        "source": "Agreste SAA departmental yields, 40 departments, 2010-2024",
        "periods": {"early": [2010, 2016], "recent": [2018, 2024]},
        "n_departments": int(df.dept_code.nunique()),
        "crops": out,
        "finding": (
            "Across these departments, mean pulse yields fell 12 to 27 percent between "
            "2010-2016 and 2018-2024 while soft wheat and spring barley stayed flat. "
            "Pulse economics are therefore tighter than reference yields imply, and any "
            "model trained on the earlier period over-predicts the present."
        ),
    }


# --------------------------------------------------------------------------- #
# Static frontend, mounted last so every API route above wins the path match.
# --------------------------------------------------------------------------- #
if FRONTEND_DIST.is_dir() and (FRONTEND_DIST / "index.html").is_file():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # The SPA shell must never be cached. Its <script> tag names a content-hashed
    # bundle, and a rebuild deletes the old hash, so a stale index.html asks for an
    # asset that now 404s and the app renders as a blank page. StaticFiles sends only
    # an ETag, which leaves a CDN free to serve the old shell off its own default TTL
    # without revalidating. Declared before the mount below so it wins the path match.
    @app.get("/", include_in_schema=False)
    def _spa_shell() -> FileResponse:
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"cache-control": "no-store, must-revalidate"},
        )

    # html=True serves index.html for the mount root, which is all this SPA needs
    # since its tabs are component state rather than routes. The hashed files under
    # /assets carry their version in the filename, so caching those is safe.
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def _no_frontend() -> dict:
        return {
            "message": (
                "API is running but no frontend build was found. Run `make build` to "
                "produce frontend/dist, then reload this page. The API itself is "
                "available under /api/v1 and documented at /docs."
            ),
            "expected_at": str(FRONTEND_DIST),
            "docs": "/docs",
            "health": "/health",
        }
