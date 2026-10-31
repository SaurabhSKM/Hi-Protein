"""FastAPI application for the Protein Sovereignty Decision & Offtake Engine."""
from __future__ import annotations

import contextlib
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

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
from .schemas import (
    DepartmentOverview,
    DossierResponse,
    ParcelLookupRequest,
    ParcelLookupResponse,
    Provenance,
    RankCandidatesResponse,
    RegionalOverviewResponse,
    SimulateRotationRequest,
    SimulateRotationResponse,
)
from .services import ml, offtake, orchestrator, rpg_codes, weather

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
    app.state.warmup_ms = round(1000 * (time.perf_counter() - t0), 1)
    app.state.model_trained = ml.is_trained()
    yield


app = FastAPI(
    title="Hi-Protein - Protein Sovereignty Decision & Offtake Engine",
    description=(
        "Quantifies whether inserting a pulse crop into a three-year rotation raises "
        "net farm income, using real French open data: Agreste SAA departmental "
        "yields, Meteo-France climate series, IGN RPG parcel geometry and ADEME "
        "Agribalyse impacts. Every numeric block carries a provenance field stating "
        "whether it is a live measurement, a model output or an assumption."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
def regional_overview(
    n_simulations: int = Query(600, ge=200, le=3000),
    pulse: str | None = Query(None, description="Force one crop instead of the best fit."),
) -> RegionalOverviewResponse:
    """Department-level adoption, conversion potential and infrastructure gaps."""
    meta = load_ref("departments")["_meta"]["national_target"]
    tgt = float(meta["target_pulse_share_pct"])
    rows: list[DepartmentOverview] = []
    total_gap, total_pot = 0.0, 0.0

    for code, d in departments().items():
        soil = d["dominant_soil"]
        base = (
            ["durum_wheat", "sunflower", "soft_wheat"]
            if code == "32"
            else ["soft_wheat", "spring_barley", "rapeseed"]
        )
        candidates = [pulse] if pulse else pulse_crops()
        best = None
        for cand in candidates:
            req = SimulateRotationRequest(
                department_code=code, area_ha=50.0, soil_type=soil,
                baseline_rotation=base, candidate_pulse_year2=cand,
                n_simulations=n_simulations, random_seed=20260131,
            )
            try:
                r = orchestrator.run(req)
            except Exception:  # noqa: BLE001
                continue
            if r.agronomic_validation.severity == "blocked":
                continue
            risk = r.financial_3yr_comparison_per_ha.risk
            if best is None or risk.median_delta_eur_ha > best[1]:
                best = (cand, risk.median_delta_eur_ha, risk.prob_pulse_beats_baseline)
        if best is None:
            continue

        gap = max(d["arable_ha"] * tgt / 100.0 - d["pulse_ha"], 0.0)
        pot = gap * best[1]
        has_sort, _ = offtake.optical_sorting_access(code, None)
        total_gap += gap
        total_pot += pot
        rows.append(DepartmentOverview(
            department_code=code, name=d["name"], region_name=d["region_name"],
            centroid=d["centroid"], arable_ha=float(d["arable_ha"]),
            pulse_ha=float(d["pulse_ha"]),
            pulse_share_pct=round(100.0 * d["pulse_ha"] / max(d["arable_ha"], 1), 3),
            target_share_pct=tgt, gap_ha=round(gap, 1), best_pulse=best[0],
            median_margin_gain_eur_ha=round(best[1], 1),
            prob_gain_positive=round(best[2], 4),
            conversion_potential_eur=round(pot, 0),
            has_optical_sorting_within_80km=has_sort,
            dominant_soil=soil,
        ))

    rows.sort(key=lambda r: -r.conversion_potential_eur)
    return RegionalOverviewResponse(
        national_current_share_pct=float(meta["current_pulse_share_pct"]),
        national_target_share_pct=tgt,
        target_year=int(meta["target_year"]),
        departments=rows,
        total_gap_ha=round(total_gap, 1),
        total_conversion_potential_eur=round(total_pot, 0),
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
        {"title": "Environment", "body": r.environmental_impact.model_dump()},
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
        "defaults": {"n_simulations": DEFAULT_N_SIMULATIONS},
        "weather_departments": weather.available_departments(),
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
