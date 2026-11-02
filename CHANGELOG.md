# Changelog

Notable changes to this project. The reasoning behind each modelling decision lives in
[docs/CHANGES_FROM_BLUEPRINT.md](docs/CHANGES_FROM_BLUEPRINT.md); this file is the
chronology.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added — the regional, food, climate and land layers

- **Regional engine.** `/regional-overview`, `/stranded-surface` and
  `/optimise-sorters`: 18,157 real IGN communes classified by whether a pulse pays
  there, would pay with an optical sorter in range, or would not pay either way — and a
  greedy siting optimiser (with an exact HiGHS verification path) that places up to 26
  new sorters where they unlock the most land.
- **Food demand side.** `/food-demand` and the Food view: what each region's population
  eats in pulse protein against what its gap-to-target hectares could grade for human
  food, plus the per-department divergence between margin and food outcome.
- **Climate horizons.** `/climate-outlook` and a `climate_horizon` option on every
  request, re-running the identical parcel decision at each TRACC warming horizon from
  measured phenological sensitivities.
- **Land-change view.** `/adoption/*`: national pulse area across 93 departments
  2010–2024, a department choropleth, ten RPG campaigns over real Beauce parcels, and an
  attribution panel.
- **The adoption attribution model** (`ml/train_adoption.py`), which returns a **null
  result**: once a national year effect and a persistent department effect are accounted
  for, last season's weather and the department's soil add nothing measurable to
  year-on-year pulse area change in 4 of 5 crops. The same model scored in-sample reports
  69.6%; cross-fitted by year it is negative. The null is the output — see
  [docs/STATUS.md](docs/STATUS.md#the-thing-that-looks-broken-and-isnt).
- **Risk layer surfaced.** 70% bands, CVaR at 5%, probability of gain, breakeven grading
  fraction, and the breakeven contract price — computed before, rendered now.
- **The livestock fallback as a priced counterparty** (`/breeders`): a holding within
  25 km that would take a downgraded lot, valued at what the feed actually replaces
  rather than at the feed spot price.
- **Haulage as a cost, not a flag** (`services/logistics.py`): distance to the nearest
  optical sorter converted to €/ha, and a parcel labelled *stranded* when haulage is the
  only reason it is negative.
- **Per-department baseline rotations** derived from Agreste area series
  (`scripts/build_dept_rotations.py`), replacing a single hard-coded
  `soft_wheat / spring_barley / rapeseed` everywhere.
- **Baked department profiles** (`scripts/build_region_profiles.py`) across all five
  climate horizons, which is what makes the regional and food views interactive.
- **A sensitivity audit** (`make audit`) that perturbs every numeric assumption and
  reports which ones flip a recommendation.
- **A landing page**, EN/FR labels throughout, and 9 new chart and panel components.
- 10 new test modules; the suite is now 299 tests.

### Changed

- **Fallow land became a first-class baseline.** In a live sample of 1,000 Beauce
  parcels, 336 are declared fallow. Converting those displaces no crop margin
  (+€960/ha, against −€274/ha for displacing the rapeseed Eure-et-Loir actually grows),
  and the engine now also warns that fallow counts toward BCAE 8 where a grain legume
  does not.
- **The RPG crop vocabulary is treated as year-dependent.** Taken as published, the
  Beauce's grain-legume share rises 2.00% → 3.39% between 2015 and 2024; like for like it
  is 2.00% → 2.39%, because three pulse codes appear in the 2023 code table and are
  absent from the 2022 one. Two code-table defects were also found and fixed: `PAG`
  (unnamed grain legume) now blocks a following pea or lentil, and `MLT` is Millet rather
  than a legume mix.
- **Deriving the baseline rotation made pulses look worse, not better**, which is the
  point: the displaced crop is usually rapeseed rather than the cheapest cereal in the
  rotation, and two of eight test cases flipped from positive to negative. The previous
  figures were flattering.
- Carbon is reported per kg of protein and under both land-use-change conventions.
- API responses are sent `Cache-Control: no-store`, after re-baked profiles kept
  rendering stale numbers from the browser cache through repeated reloads.
- The app can be mounted under a path prefix (`scripts/serve_under_app.py`) with the
  inner lifespan run explicitly — a mounted sub-application never receives lifespan
  events, which had been silently skipping model warmup and making one cold
  `/regional-overview` call take 128 seconds.

### Added — repository and operations

- `LICENSE` (Apache 2.0) and `NOTICE` with the full open-data attribution that the
  Agreste, Météo-France, IGN and ADEME licences require.
- `Dockerfile` and `.dockerignore`: one image serving the API and the bundle on one
  port, with the trained model and baked profiles inside it. Installs `xgboost-cpu` to
  avoid ~1 GB of CUDA libraries that `xgboost` declares and this project never uses.
- `frontend/vercel.json` for a static frontend deploy.
- GitHub Actions CI (lint, 299 tests, frontend build, assertions on the built bundle),
  issue and PR templates, Dependabot.
- `CONTRIBUTING.md`, `SECURITY.md`, `.env.example`, `.editorconfig`.
- `docs/STATUS.md` — a plain-language tour of every screen and what works today.
- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/RUNNING.md`, `docs/LIMITATIONS.md`,
  `docs/DEPLOYMENT.md`.
- `ruff` pinned in `requirements-dev.txt`, so `make lint` works from a fresh clone.

### Changed — repository

- The 897-line README was split into a scannable front page plus the documents above.
  No prose was discarded; it moved.
- `data/processed/` and `ml/artifacts/` are now **committed** (about 10 MB). A fresh
  clone runs on `make install && make serve` with no data download and no network
  access. `data/raw/` and `data/cache/` stay ignored and are rebuilt by `make data`.

### Known

- `GET /api/v1/climate-outlook` returns 500 rather than 422 when given an invalid
  `soil_type`, because that one parameter is typed as free text. Valid requests and the
  UI are unaffected. See [docs/STATUS.md](docs/STATUS.md#known-defects).

## [0.1.0]

Initial version: the per-parcel rotation engine, the agronomic rule layer, the quantile
yield model with conformal calibration, the food-grade hazard model, the paired
three-year Monte Carlo, and the farmer and method views.
