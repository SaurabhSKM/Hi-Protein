# Hi-Protein — Protein Sovereignty Decision & Offtake Engine

Track 3, Hack the Fork Paris 2026. A two-sided engine that answers one question with
numbers a farmer can act on: **does inserting a pulse crop into a three-year rotation
raise net farm income, and how badly can it go wrong?**

Built on real French open data. Agreste departmental yields, Météo-France climate
series, IGN RPG parcel geometry and ADEME Agribalyse impacts are all genuinely
fetched and parsed, not mocked. Buyer contract terms are the one deliberate
exception and are labelled as demo data everywhere they appear.

---

## Quickstart

```bash
make install          # python venv + npm
make data             # downloads Agreste + Météo-France, builds the training panel
make train            # trains and conformalises the quantile yield models
make test             # 95 tests
make build            # builds the frontend bundle
make serve            # the whole app on http://localhost:5173
```

`make serve` runs the API and serves the built frontend from the same process, so
there is one port, one origin, no CORS and no dev-server host check. Override the
port with `make serve PORT=8080`.

**In the workshop container, use `make app` instead.** An nginx sits in front with
only two routes: `/` goes to the code editor on 8080, and `/app` goes to this app on
8081 with the prefix forwarded intact. Serving on any other port is unreachable from
outside, because `/ports/<n>/` style paths match nginx's `location /` and land on the
editor, which answers 400. `make app` mounts the application under `/app` so
Starlette strips the prefix and every route inside keeps working unchanged.

Then open `https://<your-host>/app/`. **The trailing slash matters**: the bundle
resolves its asset and API URLs relative to the directory it was loaded from, which
is why `vite.config.js` sets `base: './'`. Without the slash you get a 307 to the
correct URL, so it works either way in a browser.

For frontend work you want hot reload instead, which needs two processes:

```bash
make api              # terminal 1: API only, with reload
make web              # terminal 2: Vite dev server, proxies /api to it
```

`make data` pulls about 59 MB and takes a few minutes on a good connection. Both
downloads are cached, so re-runs are fast. Once the cache is warm:

```bash
make offline          # serves entirely from local cache, no network at all
```

Offline mode produces byte-identical simulation results. It exists because the demo
runs on conference wifi.

**Running in a cloud workspace?** Use `make serve`. It avoids the problem entirely.

If you do use `make web`, Vite refuses requests whose `Host` header it does not
recognise, which is a DNS-rebinding guard that fires whenever the dev server is
reached through a proxy rather than on localhost. The symptom is a bare
`Blocked request. This host ... is not allowed.` page. `vite.config.js` already
allows the common tunnel domains (CloudFront, Codespaces, Gitpod, ngrok, Cloudflare).
For anything else:

```bash
VITE_ALLOWED_HOSTS=my-host.example.com make web   # or a comma-separated list
VITE_ALLOWED_HOSTS=true make web                  # disable the check entirely
```

If hot reload sits reconnecting behind an HTTPS proxy, set `VITE_HMR_HOST` to the
public hostname as well. That only affects live reloading, not the app.

---

## What the engine actually computes

The headline number is not "the pulse rotation earns X". It is **the distribution of
the difference between two rotations**:

```
baseline:  year 1 cereal  →  year 2 cereal  →  year 3 cereal
pulse:     year 1 cereal  →  year 2 PULSE   →  year 3 cereal + N credit + break-crop gain
```

Both arms are simulated over the same bootstrapped Météo-France seasons, with the
same standardised residual shocks (common random numbers). Only year 2 changes.
That is what makes the difference estimable rather than noisy, and it is the single
biggest methodological departure from the original blueprint — see
[docs/CHANGES_FROM_BLUEPRINT.md](docs/CHANGES_FROM_BLUEPRINT.md).

Per request the engine returns:

| Block | Contents |
|---|---|
| `agronomic_validation` | Terres Inovia return intervals by disease **group**, soil pH, hydromorphy, preceding-crop suitability, sowing window |
| `ml_predictions_year2` | Conformalised yield quantiles, food-grade probability, expected protein |
| `financial_3yr_comparison_per_ha` | Both arms with 70% bands, an itemised breakdown, and six risk metrics |
| `environmental_impact` | CO₂e avoided per tonne **and per kg of crude protein**, under both land-use-change conventions |
| `matched_offtake_contracts` | Buyers scored on expected revenue after their own quality grid |
| `sovereignty` | This parcel's contribution to the 4% → 8% national target |

Every one of those blocks carries a `provenance` field stating whether the numbers
are a live measurement, a cached measurement, a reference table, a model output or
an assumption. The UI renders it as a badge. A farmer committing 45 hectares is
entitled to know which is which.

### Where the blueprint's three secondary data layers actually connect

Parcel geometry, costs/prices/subsidies, and carbon/LCA are all real, live-fetched,
and were wired into the finance and rule engines from the first build. What this
revision adds is making all three reach the TRAINED model and the carbon claim
itself, not just the deterministic layers downstream of it:

- **IGN RPG parcel history** drives a real, lagged, trained feature of the yield
  model (`legume_share_lag1`, `legume_share_lag2to4_mean`), built from the Agreste
  area series because Agreste - the training data - has no parcel-level rotation
  history to learn from. The live RPG fetch still does what it always did: gate the
  Aphanomyces return interval for the ONE parcel asking.
- **Carbon** is now computed across the full Monte Carlo sample
  (`co2e_saved_tons_q15/median/q85`), not from one point yield.
- **Costs, prices and subsidies** feed the new `carbon_abatement_cost_eur_per_tonne`,
  which prices a tonne of CO₂e avoided in the same EUR the farmer actually sees.

Full argument, with the empirical checks that justified each piece, in item 20 of
[docs/CHANGES_FROM_BLUEPRINT.md](docs/CHANGES_FROM_BLUEPRINT.md).

---

## Repository layout

```
backend/app/
  main.py              FastAPI app, 8 API endpoints plus /health
  schemas.py           frozen request/response contract (Pydantic v2)
  config.py            settings + memoised reference-data loading
  refdata/             12 JSON files: crops, PAC, soils, rules, buyers, carbon, …
  services/
    agronomy.py        deterministic rule engine
    ml.py              model loading, conformal correction, parcel-level widening
    quality.py         food-grade hazard model (P_human)
    nitrogen.py        STICS/AzoFert-bounded carry-over credit
    prices.py          correlated price and cost draws
    weather.py         season bootstrap from real department-years
    finance.py         paired three-year Monte Carlo
    carbon.py          Scope 3 substitution accounting
    offtake.py         buyer matching and scoring
    orchestrator.py    assembles the response
  clients/             IGN RPG, ADEME Agribalyse, disk cache
ml/
  sources.py           Agreste SAA + Météo-France fetch and tidy
  features.py          phenological window engineering
  build_dataset.py     joins labels to features
  train.py             quantile XGBoost + conformal calibration
frontend/src/
  pages/               FarmerView, RegionView, MethodView
  components/          map, fan chart, breakdown bars, tables, provenance badge
tests/                 95 tests: rules, nitrogen, finance invariants, ML, RPG codes, API contract
scripts/smoke.py       end-to-end endpoint check
```

About 5,000 lines of Python, 1,300 of JSX, 1,300 of reference JSON.

---

## The model

**Labels.** Agreste *Statistique Agricole Annuelle*, long series 2010–2024,
department level. 3,435 observations across 40 departments and 8 crops after
filtering out departmental areas too small for the reported yield to mean anything.

**Features.** Météo-France monthly climate data per department, aggregated into
phenological windows rather than annual averages: flowering water balance
(May–June rain minus reference evapotranspiration), June days above 30 °C, May days
above 20 °C (bruchid egg-laying), July harvest rain, April frost days, winter
recharge. Normalised by soil plant-available water capacity, because −80 mm on deep
loam is an inconvenience and the same −80 mm on shallow limestone is a crop failure.
Plus two lagged rotation-history features, `legume_share_lag1` and
`legume_share_lag2to4_mean`, built from the Agreste area series itself (a
department's own trailing legume footprint) — the closest honest proxy for IGN
RPG-style crop history that department-level training labels can support. Real gain
in the trained model, and the sign is mechanistically sensible: higher recent
regional legume share correlates with LOWER pulse yield the next year for every
pulse crop, strongest for lentil and chickpea — the same Aphanomyces disease-pressure
mechanism the deterministic rule engine already enforces per parcel, now also
learned, continuously, at the department scale the training data actually supports.

**Target.** The yield *ratio* against a department-crop baseline, so the model learns
the weather response instead of re-learning that Beauce out-yields Burgundy. The
baseline is fitted on the training block only; computing it over all years would put
test-season yields into the denominator of the test target.

**Validation.** A forward time split, never random K-fold. One growing season appears
in many departments at once and weather is spatially correlated, so random folds leak
and report skill the model does not have on a future season.

| Block | Years | Rows |
|---|---|---|
| Fit | 2010–2016 | 1,422 |
| Calibrate | 2017–2021 | 1,248 |
| Test | 2022–2024 | 765 |

**Calibration is the point.** Raw quantile regression was badly miscalibrated on the
held-out block: its nominal 70% interval covered 38% of outcomes, because 2022–2024
sit well below what 2010–2016 weather-yield relationships imply. Conformalised
quantile regression with **one-sided** corrections fixes it.

| | Raw | Deployed |
|---|---|---|
| 70% interval coverage (target 0.70) | 0.384 | **0.728** |
| 15th-percentile coverage (target 0.15) | 0.481 | **0.140** |
| 85th-percentile coverage (target 0.85) | 0.865 | **0.868** |
| Median bias, ratio units | −0.086 | **−0.040** |

The pooled corrections are revealing: the lower bound needed widening by 0.205 ratio
units, the upper by 0.011. The miscoverage was almost entirely on the downside — the
raw model was systematically too optimistic about bad years, which is the one
direction that matters for a planting decision.

**Skill of the deployed model against a climatological constant**, measured by
pinball loss on the test block:

| Quantile | Skill |
|---|---|
| 15th percentile | +38% |
| Median | +14% |
| 85th percentile | −4% |

Read that honestly. The downside estimate has real skill. The median has modest
skill. The upside bound is no better than climatology. Conformal calibration buys
*honest coverage*, not sharpness, and on a block materially hotter and drier than the
fit period a correctly wide interval beats a narrow one that is wrong 60% of the time.

Held-out median error by crop runs from 9% for soft wheat to 34% for green lentil.
Minor pulses are harder because Agreste rounds their departmental yields coarsely and
there are fewer departments growing them. `/api/v1/model-report` returns all of this,
including the model's own stated limitations, and the Method tab renders it.

### A finding worth the pitch

Straight from the Agreste panel, across these 40 departments:

| Crop | 2010–2016 | 2018–2024 | Change |
|---|---|---|---|
| Green lentil | 1.66 | 1.22 | **−27%** |
| Fava bean | 2.82 | 2.38 | −16% |
| Chickpea | 1.88 | 1.62 | −14% |
| Field pea | 3.45 | 3.02 | −12% |
| Soybean | 2.71 | 2.39 | −12% |
| Rapeseed | 3.22 | 3.05 | −5% |
| Spring barley | 5.45 | 5.39 | −1% |
| Soft wheat | 6.58 | 6.52 | −1% |

Mean yields in t/ha. Pulse yields have fallen sharply in the recent climate while
cereals held flat. That is simultaneously the reason farmers hesitate, the reason the
4% → 8% target is hard, and a caution that pulse economics are tighter than reference
yields imply. Served at `/api/v1/yield-trend`.

---

## Data sources

Every URL below was verified working while building this. Details, exact column
names and parse recipes are in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

| Layer | Source | Mode |
|---|---|---|
| Yields and areas, department × crop × year | Agreste SAA long series 2010–2025 (XLSX in a ZIP) | offline, cached |
| Climate | Météo-France *données climatologiques de base*, monthly, per department | offline, cached |
| Parcel geometry and declared crop history | IGN API Carto RPG v2 | live, cached |
| RPG crop code vocabulary, per campaign | IGN Geoplateforme WFS `RPG.<year>:codes_cultures` | verified offline |
| Carbon and LCA | ADEME Agribalyse v3.1, **agriculture stage only** | live, cached |
| Subsidies | PAC 2023–2027 coupled protein aid and eco-scheme | reference table |
| Prices, costs, buyers | RICA-consistent baselines; buyer terms are demo data | reference table |

Two source choices worth flagging. Agreste SAA is not exposed through any API — the
Disar portal is a stateful JSF application with no JSON endpoint — but each dataset
page embeds a static bulk download link, which is what `ml/sources.py` uses. And
Agribalyse's *synthesis* value for dried lentil is 0.581 kg CO₂e/kg, of which 0.244
is retail transport and 0.129 is packaging; the agriculture stage is 0.141. A
farm-gate rotation comparison has to use the per-stage dataset or it overstates the
pulse footprint fourfold.

---

## What was changed from the blueprint

Twenty changes, each because the original would have produced a wrong number or
an indefensible claim. Summarised here, argued in full in
[docs/CHANGES_FROM_BLUEPRINT.md](docs/CHANGES_FROM_BLUEPRINT.md).

The four that matter most:

1. **Both rotations are simulated under shared draws.** The blueprint compared a
   stochastic pulse rotation against one deterministic baseline number, which credits
   the pulse with all of the baseline's good luck.
2. **Only year 2 changes.** The blueprint's own example switched year 2 from barley to
   lentil *and* year 3 from rapeseed to wheat, confounding the pulse effect with a
   separate crop switch.
3. **Disease return intervals apply to the host group, not the species.**
   *Aphanomyces euteiches* carries over between pea, lentil, alfalfa and any unnamed
   grain legume, so lentil after pea is exactly as dangerous as pea after pea. A
   per-species rule would have cleared it.
4. **`P_human` is a documented hazard model, not a trained classifier.** No French
   open dataset records per-lot grading outcomes, so there is no label to fit.
   Training on invented labels would make a fabricated number look like a
   measurement. Per-lot grading records from a cooperative silo are the single
   highest-value dataset a partner could contribute.

Four more found late, all worth knowing about:

- **Winter pea had no Agreste series** and was ranking first on a hand-written
  constant. Agreste publishes one pea series covering both habits, so winter pea is
  now that series with a documented uplift, and the response says so.
- **Fallow land is a first-class baseline.** In a live sample of 1,000 Beauce parcels,
  336 are declared fallow. Converting those displaces no crop margin: +€918/ha against
  −€180/ha for displacing barley. The engine also warns that fallow counts toward BCAE
  8 and a grain legume does not. A real 5.8 ha parcel fallow since 2015 returns
  €986/ha with a 99.6% chance of gain.
- **An unnamed legume in the history now blocks a pea.** RPG code `PAG` declares a
  grain legume without naming the genus, and the code table had no entry for it at
  all. A parcel reading `BTH, PAG, ORH` came back clean; it now blocks both pea and
  lentil on a 2-year gap against a 6-year *Aphanomyces* interval.
- **`MLT` is Millet, not a legume mix.** It was mislabelled in every vintage, which
  would have shown a user millet as a nitrogen-fixing precedent.

---

## API

`POST /api/v1/simulate-rotation` keeps every field name from the blueprint's frozen
Section 6 schema, so a client written against that contract still works. Added blocks
are additive. A test pins this.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/simulate-rotation` | the main engine |
| `POST /api/v1/rank-candidates` | scores every eligible pulse for one parcel |
| `POST /api/v1/parcel` | map click → real RPG parcel and crop history |
| `GET /api/v1/regional-overview` | department adoption, conversion value, sorting gaps |
| `POST /api/v1/dossier` | printable advisor transition dossier with a pre-sowing checklist |
| `GET /api/v1/reference` | everything the frontend needs for its forms |
| `GET /api/v1/model-report` | validation metrics and stated limitations |
| `GET /api/v1/yield-trend` | the observed pulse yield decline |

Measured latency, warm, on this machine:

| Call | Time |
|---|---|
| `simulate-rotation`, 2,000 paired paths | ~140 ms |
| `rank-candidates`, 6 crops | ~800 ms |
| `parcel`, cached | ~4 ms |
| `regional-overview`, 6 departments | ~4.7 s |

The yield model takes about 1.7 s to unpickle, so it is warmed at startup rather than
on the first request.

---

## Personas, and where each one lives in the UI

The Farm & Advisor workspace covers the arable farmer (presets for Beauce, Côte-d'Or
and Gers), the mixed crop-livestock farmer (the livestock toggle reroutes a downgraded
harvest to on-farm feed at its true replacement value, not the feed spot price) and
the co-op advisor (the ranking table and the printable dossier). The Regional
sovereignty map covers the Région/DRAAF view: adoption by department, conversion
value, and which departments have no optical sorting within 80 km. The Food-tech
buyer appears through the contract book, which is scored from the farmer's side.

---

## Known limitations

- Labels are **department mean** yields. Parcel variance is larger, so parcel
  intervals are widened by a measured inflation factor (1.29). This is a correction,
  not a substitute for parcel-level data.
- Features are a department median across lowland stations, not the parcel's weather.
- The weather panel covers 42 departments; the model is trained on the 40 with enough
  pulse area to label. A parcel in one of the other two gets a real local climate but
  a soil-archetype yield baseline, flagged in the response provenance.
- No variety, sowing-date, irrigation or crop-protection data exists in the open
  sources, so management effects stay in the residual.
- Margins are **operational gross margins**. Land, labour and machinery depreciation
  are excluded, as is any change in workload or equipment the switch requires.
- PAC unit amounts are provisional and set annually once declared area is known.
- Conformal coverage holds under exchangeability. A warming climate breaks that
  assumption, so the calibration block must be re-fitted every season.
- Department soil archetypes are a single coarse assignment per department. Always
  pass the parcel's own `soil_type`.
- Buyer prices, volumes and premiums are illustrative demo data, not commercial
  offers.

This is a hackathon prototype. It does not replace advice from a Chamber of
Agriculture or a cooperative agronomist, and no rule table substitutes for a soil
*Aphanomyces* test.

## Licence and attribution

Code is for the hackathon submission. The underlying open data stays under the
licences of Agreste, Météo-France, IGN and ADEME, which require attribution. The
footer of the app and this README carry it.
