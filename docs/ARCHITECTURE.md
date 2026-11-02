# Architecture

One FastAPI process, one React bundle, one trained model, and a set of derived data
artifacts that are committed so a fresh clone runs without touching the network.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Browser — React 18 SPA (frontend/)                                     │
│  6 views: Landing, then 5 tabs                                          │
│  Farmer · Food · Region · Land · Method                                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │  fetch, resolved RELATIVE to the page
                                │  (survives being mounted under a prefix)
┌───────────────────────────────▼─────────────────────────────────────────┐
│  FastAPI — backend/app/main.py + routers/                               │
│  18 routes under /api/v1, plus /health                                  │
│  Pydantic v2 request/response contract in schemas.py                    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
      ┌─────────────────────────┼─────────────────────────┐
      ▼                         ▼                         ▼
┌───────────────┐   ┌───────────────────────┐   ┌─────────────────────┐
│ services/     │   │ Committed artifacts   │   │ clients/ → network  │
│ the 20-module │   │ ml/artifacts/         │   │ IGN API Carto (RPG) │
│ domain engine │   │ data/processed/       │   │ ADEME Agribalyse    │
│ orchestrator  │   │ refdata/ (17 JSON)    │   │ → data/cache/       │
└───────────────┘   └───────────────────────┘   └─────────────────────┘
```

The two things worth knowing about this shape:

**One process serves both the API and the bundle.** `make serve` runs uvicorn, which
mounts `frontend/dist` as static files. One port, one origin, no CORS, no dev-server
host check, no proxy rules. That is why the frontend resolves its API URL relative to
`document.baseURI` rather than from a root-absolute `/api/v1` — the same bundle then
works at the domain root, under a `/app` prefix, and behind a workspace tunnel.

**The expensive work is precomputed, not cached at runtime.** There is no Redis and no
request-level memoisation of simulations. `make profiles` runs the per-department Monte
Carlo across all five climate horizons once and writes
`data/processed/region_profiles.json`; the regional and food views then do dictionary
lookups. This is why `/regional-overview` answers in 2 ms rather than the two minutes
it took when it simulated 42 departments per request.

---

## Repository layout

```
backend/app/
  main.py              FastAPI app, the /api/v1 routes plus /health
  schemas.py           frozen request/response contract (Pydantic v2)
  config.py            settings + memoised reference-data loading
  refdata/             17 JSON files: crops, PAC, soils, rules, buyers, carbon,
                       food_demand, climate_projection, logistics, breeders, …
  services/
    agronomy.py        deterministic rule engine
    ml.py              model loading, conformal correction, parcel-level widening
    quality.py         food-grade hazard model (P_human) - the pivotal term
    demand.py          what France eats vs what it grows; the food/feed split
    climate.py         measured phenological sensitivities + TRACC horizons
    nitrogen.py        STICS/AzoFert-bounded carry-over credit
    prices.py          correlated price and cost draws
    weather.py         season bootstrap from real department-years
    finance.py         paired three-year Monte Carlo
    risk.py            70% bands, CVaR at 5%, probability of gain, SERF
    robustness.py      cheap repricing of existing draws for the audit
    carbon.py          Scope 3 substitution accounting
    offtake.py         buyer matching and scoring
    logistics.py       haulage distance as a per-hectare cost
    siting.py          the greedy sorter optimiser, with the HiGHS exact check
    breeders.py        the livestock counterparty for a downgraded lot
    rotations.py       each department's own baseline rotation
    rpg_codes.py       the year-dependent RPG crop vocabulary
    adoption.py        land-change rollups from the baked adoption artifacts
    orchestrator.py    assembles the response
  clients/             IGN RPG, ADEME Agribalyse, disk cache
  routers/adoption.py  the land-change endpoints

ml/
  sources.py           Agreste SAA + Météo-France fetch and tidy
  features.py          phenological window engineering
  build_dataset.py     joins labels to features
  train.py             quantile XGBoost + conformal calibration
  train_adoption.py    why the land moved — a null result, honestly reported
  artifacts/           yield_model.joblib, model_report.json, adoption_report.json
                       ← COMMITTED

frontend/src/
  pages/               LandingView, FarmerView, FoodView, RegionView,
                       LandChangeView, MethodView
  components/          25 components: map, fan chart, food outcome panel, climate
                       ladder, breakdown bars, tables, provenance badge, crop area
                       trend, adoption map, attribution, RPG change
  lib/api.js           the single fetch wrapper; every call goes through it
  lib/landPalette.js   validated chart palette for the land-change view
  lib/labels.js        EN/FR strings

scripts/
  build_communes.py        18,157 IGN commune geometries
  build_departments.py     the 42-department area table
  build_dept_rotations.py  each department's baseline rotation, from Agreste areas
  build_region_profiles.py bakes the per-department Monte Carlo (the big one)
  build_adoption_panel.py  the 93-department land-change panel
  build_rpg_change.py      ten RPG campaigns over real Beauce parcels
  build_breeders.py        the livestock holding directory
  sensitivity_audit.py     perturb every assumption, report what flips a decision
  validate_prices.py       the Eurostat price check that returned NOT USABLE
  smoke.py                 end-to-end endpoint check
  serve.sh / serve_under_app.py   the two ways to run it

data/
  raw/        downloaded source files          ← gitignored, `make data`
  cache/      open-data API responses          ← gitignored, warms itself
  processed/  derived panels and baked profiles ← COMMITTED

tests/                 299 tests: rules, nitrogen, finance invariants, ML, RPG codes,
                       API contract, food/feed mass identity, climate projection,
                       land-change data integrity, the RPG vocabulary break, and
                       assertions on the built bundle
docs/                  this directory
```

About 5,500 lines of Python in `backend/` and `ml/`, 1,700 more in `tests/` and
`scripts/`, 5,500 of JSX, 1,550 of reference JSON.

---

## The data lifecycle

Four tiers, and which tier a file is in decides whether it is committed.

| Tier | Where | Committed? | Rebuilt by | Size |
|---|---|---|---|---|
| **Source downloads** | `data/raw/` | No | `make data` | ~60 MB |
| **Open-data API cache** | `data/cache/` | No | warms itself on use | ~49 MB |
| **Derived artifacts** | `data/processed/`, `ml/artifacts/` | **Yes** | `make train`, `make regions`, `make profiles` | ~10 MB |
| **Authored reference data** | `backend/app/refdata/` | **Yes** | hand-maintained | ~1.5 MB |

Committing the derived tier is a deliberate choice. It is 10 MB, and it is the
difference between a repo that runs on `git clone && make install && make serve` and one
that first needs working access to four open-data APIs plus about six minutes of
rebuild. A reviewer, a judge, a CI runner and a container build all want the former.
Nothing is lost: every file in that tier is regenerated from source by a make target.

### The rebuild order, and the one trap in it

```
make data      →  data/raw/, data/processed/training_panel.csv, weather_panel.csv
make train     →  ml/artifacts/yield_model.joblib + model_report.json
make regions   →  communes.json, departments, dept rotations, breeders,
                  then region_profiles.json
```

**After any change to the margin engine, re-run `make profiles`.** The farmer view
simulates live; the regional and food views read the bake. They read the same numbers
precisely so that they cannot disagree — and if the bake is stale, they quietly will.
`make rotations` re-derives the baseline rotations alone, which changes which crop a
pulse is compared against, so it needs a `make profiles` after it.

`make profiles` takes about six minutes for all five climate horizons.
`make profiles-fast` does the observed horizon only in about seventy seconds, which is
enough to check a margin-engine change but leaves the food view's projected horizons
computing live.

### Offline mode

With `data/cache/` warm, `HIPROTEIN_OFFLINE=1` (or `make offline`) serves entirely from
local cache with no network access at all, and produces byte-identical simulation
results. It exists because the demo runs on conference wifi, and
`tests/test_frontend_build.py` asserts that the built page loads nothing from a CDN so
that this stays true.

---

## Where to start reading

| If you want to understand… | Read |
|---|---|
| what a visitor sees, in plain language | [STATUS.md](STATUS.md) |
| what the engine computes and why | [ENGINE.md](ENGINE.md) |
| the request/response contract | [API.md](API.md) |
| where every number comes from | [DATA_SOURCES.md](DATA_SOURCES.md) |
| why a modelling choice departs from the brief | [CHANGES_FROM_BLUEPRINT.md](CHANGES_FROM_BLUEPRINT.md) |
| how the parameters check out against the literature | [LITERATURE_AND_CALIBRATION.md](LITERATURE_AND_CALIBRATION.md) |
| what is weak about it | [LIMITATIONS.md](LIMITATIONS.md) |
| how to deploy it off AWS | [DEPLOYMENT.md](DEPLOYMENT.md) |

The single most useful file for a newcomer to the code is
`backend/app/services/orchestrator.py`: it is the one place where the whole response is
assembled, so reading it top to bottom names every service in the order it runs.
