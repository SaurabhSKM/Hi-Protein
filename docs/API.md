# API reference

19 routes: 18 under `/api/v1`, plus `/health` outside the versioned prefix so a liveness
probe does not have to know the version. Interactive docs are at `/docs` on a running
instance, generated from the Pydantic models — those are authoritative for field names
and bounds. This page is the map.

`POST /api/v1/simulate-rotation` keeps every field name from the blueprint's frozen
Section 6 schema, so a client written against that contract still works. Added blocks
are additive, and `tests/test_api.py` pins this.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/simulate-rotation` | the main engine |
| `POST /api/v1/rank-candidates` | scores every eligible pulse for one parcel |
| `POST /api/v1/parcel` | map click → real RPG parcel and crop history |
| `POST /api/v1/dossier` | printable advisor transition dossier with a pre-sowing checklist |
| `POST /api/v1/optimise-sorters` | sites up to 26 new optical sorters where they unlock the most land |
| `GET /api/v1/regional-overview` | department adoption, conversion value, sorting gaps |
| `GET /api/v1/stranded-surface` | the commune surface: where a pulse pays, would pay with a sorter, or never |
| `GET /api/v1/food-demand` | **what each region eats against what it could grade for food** |
| `GET /api/v1/climate-outlook` | **the same parcel decision at each warming horizon** |
| `GET /api/v1/breeders` | a livestock holding within range that would take a downgraded lot |
| `GET /api/v1/reference` | everything the frontend needs for its forms |
| `GET /api/v1/model-report` | validation metrics and stated limitations |
| `GET /api/v1/yield-trend` | the observed pulse yield decline |
| `GET /api/v1/adoption/overview` | **national pulse area 2010–2024, 93 departments** |
| `GET /api/v1/adoption/departments` | per-department trajectory for one crop |
| `GET /api/v1/adoption/geometry` | department boundaries for the choropleth |
| `GET /api/v1/adoption/attribution` | what explains the shift, and what cannot be explained |
| `GET /api/v1/adoption/rpg-change` | real Beauce parcels across ten RPG campaigns |
| `GET /health` | model version, weather coverage, offline flag, which profiles are baked |

Every response is read-only. No endpoint writes, deletes or triggers a rebuild.

## The main call

```bash
curl -s localhost:5173/api/v1/simulate-rotation \
  -H 'content-type: application/json' -d '{
    "department_code": "28",
    "area_ha": 45.0,
    "soil_type": "deep_loam",
    "baseline_rotation": ["soft_wheat", "spring_barley", "rapeseed"],
    "candidate_pulse_year2": "green_lentil",
    "n_simulations": 2000
  }'
```

`baseline_rotation` is required and must be exactly three crops — there is no default,
because the year-2 baseline crop is the largest single term in the reported difference
and silently assuming one is how the figures came to be optimistic (see
[LIMITATIONS.md](LIMITATIONS.md)). `GET /api/v1/reference` returns the department's own
derived rotation to put in this field, along with the valid `soil_type` and crop values.

`soil_type` is one of `deep_loam`, `clay_loam`, `deep_clay`, `shallow_limestone`,
`sandy`, `boulbene`. Optional fields: `lon`/`lat` (measures haulage from the real parcel
rather than the department centroid), `parcel_id`, `soil_ph`, `has_livestock_ugb_5`,
`irrigated`, `has_cover_crop`, `crop_history` (most recent **last**), `climate_horizon`,
`random_seed`. Unknown fields are rejected rather than ignored: every request model sets
`extra="forbid"`.

The response has 14 top-level blocks — `agronomic_validation`, `ml_predictions_year2`,
`financial_3yr_comparison_per_ha`, `financial_3yr_whole_parcel_eur`,
`environmental_impact`, `matched_offtake_contracts`, `sovereignty`, `food_outcome`,
`climate_context`, `sorter_access`, `breeder_fallback` and the risk figures. Every number
carries a `[LIVE]` / `[REPO]` / `[JUDG]` provenance tag.

## Measured latency

Warm, on the workshop container, 2026-11-02. Taken with the request bodies above.

| Call | Time |
|---|---|
| `GET /reference` | 3 ms |
| `GET /regional-overview` | 2 ms (baked) |
| `GET /food-demand`, 200 paths | 5 ms (baked) |
| `GET /stranded-surface`, dept 28 | 6 ms |
| `GET /breeders` | 6 ms |
| `GET /yield-trend` | 16 ms |
| `GET /adoption/geometry` | 31 ms, 0.8 MB |
| `POST /optimise-sorters`, k=2 | 13 ms |
| `POST /simulate-rotation`, 400 paths | 246 ms |
| `POST /dossier` | 243 ms |
| `POST /parcel`, cached RPG | 779 ms |
| `GET /adoption/overview` | 1.1 s |
| `POST /rank-candidates`, 6 crops | 1.3 s |
| `GET /climate-outlook`, 5 horizons | 1.4 s |

`regional-overview` and `food-demand` are fast only because `make profiles` has baked
the per-department Monte Carlo for all five climate horizons. On a cold bake they run
live and take seconds. `GET /health` reports which horizons are baked under
`profile_bake` and which responses were pre-warmed at startup under `warmed` — check it
first if either tab feels slow.

The yield model takes about 1.7 s to unpickle, so it is warmed during the FastAPI
lifespan rather than on the first request.

## Caching

API responses are sent `Cache-Control: no-store`. This is deliberate and was a real bug:
after the department rotations were corrected and the profiles re-baked, the regional map
kept rendering the previous numbers through repeated reloads, because the JSON came from
the browser cache while the content-hashed bundle was correctly fresh. During a live demo,
stale figures with no indication they are stale are worse than slow.

Static assets are left alone — their filenames are content-hashed, so caching them is
correct.

## Checking it

```bash
make smoke            # exercises every endpoint against a running API, prints a report
```

## Known rough edge

`GET /api/v1/climate-outlook` types `soil_type` as a bare `str` rather than the
`SoilType` literal the POST models use, so an invalid value returns **500** instead of a
422 with the list of valid soils. Valid requests are unaffected. See
[STATUS.md](STATUS.md#known-defects).
