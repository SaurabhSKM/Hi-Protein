# The engine: what it computes, and how

This is the detailed walkthrough of the modelling. For a plain-language tour of what a
visitor to the site actually sees, read [STATUS.md](STATUS.md) instead. For the
endpoint-by-endpoint contract, see [API.md](API.md).

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
[docs/CHANGES_FROM_BLUEPRINT.md](CHANGES_FROM_BLUEPRINT.md).

Per request the engine returns:

| Block | Contents |
|---|---|
| `agronomic_validation` | Terres Inovia return intervals by disease **group**, soil pH, hydromorphy, preceding-crop suitability, sowing window |
| `ml_predictions_year2` | Conformalised yield quantiles, food-grade probability, expected protein |
| `food_outcome` | **Tonnes that reach a French plate**, people fed for a year, the food/feed price gap, and the revenue grading risk puts in play |
| `financial_3yr_comparison_per_ha` | Both arms with 70% bands, an itemised breakdown, and six risk metrics |
| `environmental_impact` | CO₂e avoided per tonne **and per kg of crude protein**, under both land-use-change conventions. Counterfactual: imported soybean meal — i.e. this prices the **downgraded** fraction |
| `climate_context` | Which climate the figures were computed in, and how far the seasons were shifted |
| `matched_offtake_contracts` | Buyers scored on expected revenue after their own quality grid |
| `sovereignty` | This parcel against this dashboard's arable-pulse metric, **plus** the official PSN target stated separately with its own denominator |

### The food outcome, and why two multiplications

Tonnes grown is not the answer to "what do people eat". Two things stand between them,
and `food_outcome` reports both rather than only their product:

* **`human_grade_fraction`** — does *this lot* clear retail specification? Sampled per
  Monte Carlo draw from the hazard model, so a wet July really does downgrade it.
* **`food_market_share`** — does the crop have a human-food outlet *at all*? Structural,
  from published market balances. Green lentil 0.95; fava bean 0.18.

Reporting only the product would make a well-graded fava bean look like food security. It
is not: almost all of it goes to feed, because that is where the demand is. A 45 ha lentil
parcel in Beauce grades about 32 t for human food — the annual pulse intake of roughly
**5,100 people** at the twice-weekly level public nutrition advice recommends.

The two counterfactuals are also kept apart, because conflating them is how a
plant-protein carbon claim gets rejected on review. The fraction that *fails* grading
goes to feed and displaces imported Brazilian soybean meal — that is the
`environmental_impact` block. The fraction that *passes* displaces an **imported pulse on
a French plate**, and is reported as a tonnage rather than as carbon, because only the
transport differential is defensible from open data.

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
[docs/CHANGES_FROM_BLUEPRINT.md](CHANGES_FROM_BLUEPRINT.md).

---


## The regional engine: siting the infrastructure

The farmer's half of this product asks whether a crop is worth sowing on one field. The
planner's half asks a different question — which €450,000 capital grant converts the
most hectares — and that is a facility location problem, not a bigger version of the
same simulation.

**Why infrastructure distance is a cost, not a flag.** To be sold for human
consumption a pulse lot must pass an industrial cleaner and an optical sorter. Charge
the haul to the nearest one and a new category appears that no yield model can produce
on its own: land that is agronomically ideal, passes food specification, and still
loses money because of where it is.

```
delta(km) = delta(0) − food_tonnes_per_ha × €0.45/t/km × max(0, km − 25)
```

Two rules keep that honest. Only the haul **beyond 25 km** is charged, because the
first 25 km is already inside the operating cost both rotations carry — charging it in
full would penalise the pulse for a trip the cereal also makes. And only **food tonnes**
are charged, so a badly graded year hauls less and pays less, which partly offsets the
grading loss instead of compounding it.

**A result that falls out of it.** Because haulage is linear and the food premium is
finite, every crop has a maximum viable haul. Field pea's food-versus-feed spread is
€78/t, so it stops paying for its own haul at about **198 km**. Green lentil's is
€565/t and would pay to cross the country. A single national 80 km rule treats the two
identically, and it should not.

**The demand surface.** 18,157 real IGN communes across the 42 departments this project
has weather for, each carrying its department's real Agreste arable and pulse hectares
split in proportion to cadastral area. Classified four ways, and the third is the only
one a capital grant can act on:

| Status | | Communes |
|---|---|---|
| `viable` | Pays at the sorter distance it actually has | 6,387 |
| **`stranded`** | **Loses money now, would pay with a sorter in range** | **4,486** |
| `uneconomic` | Loses money even with a sorter next door | 6,775 |
| `unmodelled` | No viable pulse profile for the department | 509 |

**81,418 ha stranded, worth €9.6M of three-year margin currently lost to haulage.**
Conflating `stranded` with `uneconomic` is how infrastructure money gets spent where no
amount of sorting capacity would help, so a test pins the distinction.

**The optimiser.** Capacitated facility location over those 18,157 demand points
against ~2,100 candidate silo sites. Simulating every pair would be 38 million Monte
Carlos; because haulage is linear, the simulation runs **once per department** and every
pair is an exact closed-form shift. That equivalence is the load-bearing claim of the
whole regional engine, so it is tested against real simulations at 40, 120 and 300 km
rather than assumed.

The objective is the classical uncapacitated facility location objective, which is
monotone and submodular — so greedy marginal gain is within (1 − 1/e) ≈ 0.632 of the
optimum (Nemhauser, Wolsey & Fisher 1978). That is a proof. The worst case is then
checked against the realised one: the same problem is solved exactly with HiGHS over a
candidate set **forced to contain greedy's own picks**, and greedy comes in at **99.7%**
of the exact optimum. Greedy is 40 ms, HiGHS is 3.7 s, so exact verification is a
checkbox rather than the default.

12 units at €5.4M capex: **37,594 ha unlocked, 120,000 t of food-grade pulses, 142,151 t
CO₂e avoided, pulse share 3.24% → 3.72%.** Every sited unit hits 100% of its 10,000 t/yr
throughput, so the binding constraint is the machine, not the geography — which is why
closing the gap to 8% needs on the order of a hundred units rather than one.

---

## The fear-killer, and how big it actually is

A cereal farmer's objection to food-grade pulses is not about average yield. It is that
a wet July turns the whole lot from €840/t lentil into €275/t commodity feed and the
year is a loss.

The answer: a downgraded high-protein lot does not need to be fed on the farm that grew
it, only within haulage distance of it. France imports roughly 3.5 Mt of soybean meal a
year, and a livestock holding 20 km away is buying some of it. The engine matches the
lot to neighbouring holdings inside 25 km and prices **both sides** — what the lot is
worth in a ration, what the breeder pays, what each keeps, and how much imported meal
stops being bought. The surplus split (55% to the farmer) is a stated negotiating
assumption, not a hidden one.

**Two things measurement said that the pitch would rather not hear, both kept.**

**It is a revenue floor, not downside insurance.** The intuitive story is that a bad
year downgrades more of the lot, so the contract's value should concentrate in the left
tail. It does not. The loss tail is driven mostly by low yield, and a low-yield year has
fewer tonnes to downgrade — poor yield and poor grading nearly cancel in downgraded
tonnage (1.49 t/ha in the worst 15% against 1.54 t/ha overall). The uplift is a
near-flat **€46/ha**, only marginally larger in the tail. Real, worth having, and about
six times smaller than a €298/ha CVaR flip.

**And chickpea has no contract worth signing at all.** Its commodity feed price
(~€295/t) is at or above its value in a livestock ration (~€294/t), so no local holding
can outbid the feed market. The engine returns no contract rather than quoting a floor
equal to the spot price and calling it de-risking.

The directory itself is 1,600 holdings on **real IGN commune centroids** — so every
distance is a real distance between real places — with the count per department scaled
by that department's measured non-arable cadastral share. Names and herd sizes are
generated from published per-herd-type averages. No real farm is described, and the API
says so in three separate fields.

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


## The demand side

`GET /api/v1/food-demand`. Everything else in this engine looks upstream of the farm
gate; this looks downstream, because "the proteins people in France will eat" is a
demand question and no amount of agronomy answers it.

Nothing here is a model. It is arithmetic over named parameters, derived at request time
so that a reader who disagrees with the 60 g serving can change one number in
`refdata/food_demand.json` and watch every tonnage move:

| | |
|---|---|
| France eats | ~2.0 kg of dry pulses per person per year → **137,000 t** |
| France grows | **60,500 t** (*légumes secs*, 2022) |
| So French plates are | **44% French** |
| At the PNNS recommendation | pulses twice a week × 60 g dry = 6.24 kg/person → **427,000 t**, i.e. **14% covered** |

The 44% is a genuine cross-check rather than a restatement: it is derived from population
× intake against DGPE production, and the France Stratégie evaluation independently puts
the human-consumption tier at "about one third". Two different routes, same region.

Per region, the endpoint sets what the population eats against what the department's
gap-to-target hectares would *grade for human food* — and returns two supply figures
whose divergence is the finding:

> Across the five pilot regions, closing the area gap with the pulse that **pays** best
> grades about **29,000 t** for human food. Closing it with the pulse that **feeds** best
> grades about **52,000 t**. The difference, ~**23,000 t**, is food the current incentive
> structure leaves on the table.

In Vienne (86) the margin-best pulse is winter pea at −€336/ha; the food-best is chickpea
at −€525/ha. Feeding people costs that farmer €189/ha more, and Vienne has **no optical
sorting within 80 km**, which caps the graded share anyway. Nouvelle-Aquitaine covers 38%
of its own population's pulse consumption; Centre-Val de Loire covers 539%, because
Beauce has the arable area and not the mouths. That asymmetry is the inter-regional flow
a DRAAF would plan around.

Public catering is reported as a **floor**, not a solution: the weekly vegetarian main
EGalim put into canteens comes to roughly 31,000 t nationally. Reliable and contractable,
but not a substitute for retail growth — a pitch claiming canteens close the gap is
overstating it, so the engine reports the modest number.

---


## Tomorrow: the climate horizons

`GET /api/v1/climate-outlook`, and a `climate_horizon` field on every request. The
bootstrap answers for next spring. A sorting line or a 2030 area target has to survive
2050.

**The deltas are measured, not asserted.** Rather than hand-writing climate change
factors, `services/climate.py` regresses each phenological variable against spring
temperature *within department* in the project's own Météo-France panel, then shifts
resampled observed seasons by the warming increment of the French **TRACC** reference
trajectory (+2 °C ~2030, +2.7 °C ~2050, +4 °C ~2100). Each observed season keeps its
internal correlation structure; only its level moves. The projection re-fits itself when
the panel is refreshed, and there is no table of assumed deltas to go stale.

Measured sensitivities, per +1 °C:

| Variable | Slope | r | Projected? |
|---|---|---|---|
| May days above 20 °C (bruchid egg-laying) | **+3.33 d** | 0.66 | yes |
| June days above 30 °C | +1.34 d | 0.50 | yes |
| Flowering ETP | +13.8 mm | 0.58 | yes |
| April frost days | −1.03 d | −0.43 | yes |
| **July harvest rain** | +0.29 mm | **0.01** | **no** |

A variable whose response is below |r| = 0.15 is **left unshifted rather than
extrapolated on noise**, and that refusal produces the substantive result: harvest rain
has no measurable temperature response in the observed record, so warming threatens pulse
grading through **insect pressure, not wetter harvests**. That points at variety and pest
tolerance rather than drying capacity.

Green lentil in Beauce, same parcel, same seed, only the climate changing:

| Horizon | Shift | P_human | Food t/ha | Margin €/ha |
|---|---|---|---|---|
| Observed bootstrap | — | 0.589 | 0.630 | −571 |
| Present-day | +0.23 °C | 0.581 | 0.620 | −578 |
| TRACC +2 °C (2030) | +0.53 °C | 0.570 | 0.620 | −597 |
| TRACC +2.7 °C (2050) | +1.23 °C | 0.538 | 0.560 | −605 |
| TRACC +4 °C (2100) | +2.53 °C | 0.473 | **0.440** | −614 |

Chickpea in Gers barely moves by comparison (−6% food tonnage at 2050, and its margin
slightly *improves*), because it is drought-insensitive. So the honest output of this
layer is a **crop-reallocation signal**, not a uniform decline.

One finding falls out of the method rather than the projection. The engine's 30-year
bootstrap window, even with its 12-year recency half-life, sits a **measured 0.23 °C
below the last decade** — so the raw "observed" row already describes a climate that has
passed. Every horizon except `observed` corrects for it, and the correction is reported
separately from the projected warming so a reader can see which is which.

`climate_horizon` defaults to `observed`, which reproduces every number the engine
published before projections existed. A test pins that equivalence.

---


## How the land changed: the adoption view

A fourth screen, `LandChangeView`, answers a question the rest of the engine does not:
has French farmland actually moved toward lentils and other grain legumes, where, and
why. It is ordered by how much each answer can be trusted.

**What happened.** Agreste SAA, 93 departments, 2010-2024, declared hectares, no
modelling. The headline is that this is two opposite movements, not one:

| Crop | 2010 | peak | 2024 |
|---|---|---|---|
| Green lentil | 12,086 ha | 37,909 ha (2019) | 31,398 ha |
| Chickpea | 2,781 ha | 33,203 ha (2019) | 29,135 ha |
| Soybean | 49,736 ha | 187,068 ha (2020) | 152,680 ha |
| Field pea | 209,967 ha | 209,967 ha (2010) | 123,065 ha |
| Fava bean | 151,307 ha | 151,307 ha (2010) | 80,439 ha |

The two pulses grown for people multiplied; the two grown for animal feed lost a third
to a half. Four of the five peaked before 2024, so the view reports peak year as well
as first and last — a first-to-last comparison alone would describe a
plateau-and-retreat as steady growth. 112 department-crop pairs went from a true zero
to a real area, which is only visible because the panel keeps the `area_ha == 0` rows
the training panel filters out.

Charts are faceted rather than dual-axis. Field pea at 210,000 ha and lentil at 12,000
on one linear axis makes the lentil line a flat smear along the bottom, which is the
opposite of the finding, so the absolute charts split by outlet and a separate chart
indexes every crop to its own first year.

**Why — and this is a null result.** `ml/train_adoption.py` models the year-on-year
*change* in a department's area share, not the level: the level is 0.969
autocorrelated, so a model fitted on it scores well and has only learned which
departments grow peas. A national year effect common to every department explains
13.7-37.3% of the variance. Weather and soil, cross-fitted with folds grouped by year,
**add nothing** — the increment is negative for four of five crops, and held out on
2020-2024 the model does not beat assuming no change at all. Fitted in-sample the same
stage claims 52.2% to 74.2%; both numbers are in the artifact and the gap is the overfit.

So the shift is not weather-driven, and the drivers that would explain it are precisely
the series this repo has no usable history for: pulse prices, PAC coupled aid per
campaign, and contract or sorting capacity. The view says so on the page rather than
implying weather did it. Weather does move *yield* — that response is charted beside
the null result, so the two are not confused.

**Field level.** Ten RPG campaigns over the Beauce, 158,302 real declared parcels in
2024. This panel leads with a warning, because its own headline number cannot be taken
at face value: see the vocabulary trap in the data-sources note above.

Rebuild all three artifacts with:

```bash
.venv/bin/python scripts/build_adoption_panel.py   # Agreste panel + IGN boundaries
.venv/bin/python ml/train_adoption.py              # attribution
.venv/bin/python scripts/build_rpg_change.py       # 10 RPG campaigns, ~10 min
```

---


## Personas, and where each one lives in the UI

The **Farm & Advisor workspace** covers the arable farmer (presets for Beauce,
Côte-d'Or and Gers), the mixed crop-livestock farmer (the livestock toggle reroutes a
downgraded harvest to on-farm feed at its true replacement value, not the feed spot
price) and the co-op advisor (the ranking table and the printable dossier). It leads
with the food outcome panel and carries a climate-horizon selector, so the first thing a
farmer sees is where the harvest goes and the last is whether that still holds in 2050.

Three blocks below that answer the three questions an advisor is actually asked.
**Getting the crop to an optical sorter** turns distance into a per-hectare cost and
labels the parcel stranded when haulage is the only reason it is negative. **The bad
year, and who takes it off your hands** names a livestock holding within 25 km, prices
both sides of the trade, and draws the downside twice on one scale so the before figure
stays on screen next to the after. **What price would make this worth doing** answers
the kitchen-table question with a number — *becomes preferred at €342/t on 100% of
volume* — rather than a distribution, and shows why contracting more volume lowers the
price needed.

The **Food demand & supply** tab is the Région/DRAAF's own view of the brief: what the
population eats, what the region's gap-to-target hectares could grade for human food,
and the margin-versus-food divergence per department.

The **Regional sovereignty map** is the investment committee's screen. 18,000 real
communes coloured by whether a pulse pays where they stand, would pay with a sorter in
range, or would not pay either way — and one button that sites up to 26 new units where
they unlock the most land, with the hectares, tonnes, CO₂e and pulse-share movement
updating against the €450k-per-unit capex. The Food-tech buyer appears through the
contract book, which is scored from the farmer's side.

