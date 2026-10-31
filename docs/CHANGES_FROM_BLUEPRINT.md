# Changes from the Track 3 blueprint, and why

Each item below changes a number or a claim. Cosmetic differences are not listed.
Ordered roughly by how much the output moves.

---

## 1. Both rotations are simulated, under shared random draws

**Blueprint.** `Net Margin₃ᵥᵣ` produces one stochastic figure for the pulse rotation
and compares it against `baseline_3yr_net_margin_eur: 1420.0`, a single deterministic
number.

**Problem.** The baseline is not deterministic. Wheat and barley yields swing as
hard as pulse yields — 2016 wheat in Eure-et-Loir came in at 5.43 t/ha against a
8.3 t/ha norm, visible in the Agreste data the model trains on. Comparing a
distribution against a point estimate credits the pulse with every good draw the
baseline would also have had.

**Change.** Both arms run over the same bootstrapped seasons with the same
standardised residual shocks (common random numbers), and the engine reports the
distribution of the **difference**. The difference is far less noisy than either arm,
which is the whole point: it isolates the decision from weather the farmer faces
either way.

**Effect.** A test pins that `sd(delta) < sd(baseline_total)`. The reported risk
metrics are about the decision, not about farming in general.

---

## 2. Only year 2 changes

**Blueprint.** The worked example switches year 2 from spring barley to green lentil
**and** year 3 from rapeseed to winter wheat, then attributes the whole three-year
difference to the pulse.

**Problem.** Two variables moved. Part of the gain is just rapeseed-to-wheat.

**Change.** Year 1 is identical in both arms and cancels out of the difference. Year 3
keeps the same crop and differs only by the nitrogen credit and the break-crop yield
response the legume leaves behind. A `year3_override` exists for teams that genuinely
want to model the double switch, but it is not the default.

---

## 3. Disease return intervals apply to the host group, not the species

**Blueprint.** `return_interval_years: 6` as a per-crop scalar, with the note
"minimum 5–6 years between pea crops".

**Problem.** *Aphanomyces euteiches* infects pea, lentil and alfalfa. Lentil two years
after pea is as dangerous as pea after pea, and a per-species rule clears it.

**Change.** `rotation_rules.json` defines disease **groups** with host lists and
partial hosts. The engine walks the parcel's RPG history looking for any host of the
candidate's group. High-severity groups block; medium-severity ones warn.

**Effect.** Lentil after pea now returns `severity: "blocked"`. The financial figures
are still returned, so the cost of the constraint is visible, but the first line of
the response says the result must not be acted on.

---

## 4. `P_human` is an honest hazard model, not a fake classifier

**Blueprint.** "the ML classifier predicts the probability `P_human`".

**Problem.** No French open dataset records per-lot grading outcomes. There is no
label. Training a classifier on synthetic labels dresses a fabricated number as a
measurement, and a jury that asks "what did you train that on" gets no good answer.

**Change.** `P_human` is a structured, parameterised hazard model in
`refdata/quality.json`: a per-crop base rate multiplied by named agronomic mechanisms,
each driven by a real Météo-France feature — harvest staining from July rain, bruchid
damage from May days above 20 °C, seed splitting from the drought index, small-seed
abortion from June heat, and an optical-sorting access penalty. It is reported with
`provenance.mode = "reference_table"` and the response states plainly that it has no
observational labels.

**Noted as the top data ask.** Per-lot grading records from a cooperative silo would
turn this into a genuinely trained classifier.

---

## 5. The harvest is graded as a fraction, not a coin flip

**Blueprint.** `P_human × Price_human + (1 − P_human) × Price_feed`, i.e. the
*expected* price.

**Problem.** Using the expectation hides the risk the product exists to quantify.
Flipping one coin per harvest instead overstates it, because part of a lot really can
be sorted into a passing fraction.

**Change.** The human-grade fraction is drawn from a Beta distribution centred on
`P_human`, plus an independent catastrophic whole-lot rejection event whose
probability rises with harvest rain. A wet harvest now produces an 8.5% chance of
total downgrade rather than a smoothly lower average price.

---

## 6. Price is negatively correlated with yield

**Blueprint.** Prices appear as fixed ranges.

**Problem.** A season that cuts French and European yields lifts the price. Drawing
them independently overstates downside risk by the size of that natural hedge, and a
model that overstates risk is as useless for a planting decision as one that hides it.

**Change.** `prices.py` draws each price with a target correlation to the yield shock:
−0.40 for cereals traded on a deep European market, −0.18 for niche pulses whose price
is set by import competition and contract grids. Verified at −0.39 and −0.18 in test.

---

## 7. Nitrogen carry-over is bounded by soil and weather, not flat

**Blueprint.** "30 to 50 kg of mineralizable nitrogen per hectare", cutting year-3
fertiliser by €45–65/ha.

**Problem.** A flat band ignores that the credit scales with the biomass the legume
actually produced, that cool or shallow soils mineralise residue more slowly, and that
a wet autumn on light soil leaches most of it away.

**Change.** `N_credit = residue_base × (yield ratio)^0.6 × soil mineralisation factor ×
(1 − leaching fraction)`, capped at 70 kg/ha absolute and at 35% of the following
crop's nitrogen budget. The exponent below 1 reflects that a double-yield crop does not
leave double the available N.

**Effect.** Fava bean on deep loam gives 34 kg N/ha; lentil on shallow limestone gives
11; a failed pea gives 16. A wet autumn without a cover crop drops a good pea from 28
to 20.

---

## 8. The year-3 yield boost is crop-specific and smaller than quoted

**Blueprint.** "+0.5 to +0.8 t/ha" for the following wheat, applied uniformly.

**Problem.** Published French trial means cluster nearer +0.4 t/ha, the gain shrinks
when the legume yielded poorly, and lentil and chickpea leave far less biomass than
pea or fava bean. Part of the gain is not nitrogen at all but the break-crop effect on
take-all and grass weeds, which a following rapeseed captures only partly.

**Change.** Per-legume means (lentil 0.28, pea 0.50, fava 0.55, alfalfa 0.80), scaled
by the legume's realised yield, damped in drought-limited years, and multiplied by a
capture factor for the following crop: 1.0 for a cereal, 0.45 for an oilseed.

---

## 9. Agreste's blended yields are corrected for irrigation

**Problem found while testing.** The engine initially recommended rain-fed soybean
almost everywhere, including Beauce. Agreste publishes one departmental yield per crop
that blends irrigated and rain-fed area, and French soy area is majority irrigated, so
the blended mean badly overstates a rain-fed parcel.

**Change.** `refdata/irrigation.json` decomposes the blended mean:
`y_rainfed = observed / (1 + s × uplift)` where `s` is the irrigated share of that
crop's national area. Rain-fed soybean is scaled by 0.77, irrigated by 1.15. Applied
to both arms so the comparison stays fair.

**Effect.** Rain-fed soy in Gers drops to roughly break-even; irrigated soy with a
non-GMO contract stays clearly positive. That matches where soy is actually grown.

---

## 10. The department baseline is adjusted for the parcel's soil

**Problem found while testing.** Switching a Beauce parcel from deep loam to shallow
limestone *raised* the predicted pea yield slightly — the opposite of the agronomy.
The department mean already embeds that department's dominant soil, so the soil
selector moved the weather features but not the yield level.

**Change.** The department baseline is scaled by the ratio of the crop's mean yield on
the parcel soil to its mean on the department's dominant soil, clipped to [0.70, 1.25]
because those crop-by-soil means are confounded by where each crop is grown.

**Effect.** Field pea in Eure-et-Loir now reads 3.80 t/ha on deep loam, 3.19 on
shallow limestone, 2.66 on acid silt.

---

## 11. Carbon is reported per kg of protein and under both LUC conventions

**Blueprint.** `co2e_saved_tons_total: 31.4`, one number, citing Agribalyse.

**Problems.** Three. Comparing per kg of *product* flatters the pulse: soybean meal is
46% protein and field pea is 22%, so a product-weight comparison is a factor-of-two
gift. Amortised land-use change is most of the footprint of South American soy meal,
and whether a buyer's inventory includes it changes the answer fourfold. And the
Agribalyse *synthesis* value includes retail transport and packaging.

**Change.** The engine reports CO₂e avoided per tonne **and per kg of crude protein**,
under the requested convention **and** the other one, using the Agribalyse
**per-stage** dataset filtered to the agriculture stage.

**Effect.** 45 ha of field pea: 169 t CO₂e avoided with land-use change, 25 t without.
Both are shown. Dried lentil at the farm gate is 0.141 kg CO₂e/kg, not the 0.581 the
synthesis table reports.

---

## 12. Buyer prices are per crop, and quality fit is counted once

**Problems found while testing.** The buyer book had one price per buyer, so a packer
taking both lentil and pea quoted pea at €900/t. And the match score included quality
fit as its own term *after* quality fit had already reduced the revenue estimate,
which ranked a €346/t cooperative above a €905/t packer paying 70% more per hectare.

**Change.** Prices, floors, volumes and tolerances are keyed per crop. Scoring is
normalised against the best offer in the candidate set and driven by expected revenue
and its downside, with quality entering once through the share of the harvest that
clears each buyer's grid. The feed market is included as an explicit no-contract
benchmark that every offer has to beat.

---

## 13. On-farm feed is valued as substitution, not at the feed spot price

**Blueprint.** Downgraded harvest "routes to on-farm livestock feed, saving soy
purchases", priced at the animal-feed floor.

**Problem.** The feed floor understates it. A farm feeding its own pulses replaces
purchased protein meal **and** purchased cereal, and avoids haulage and trader margin
on both.

**Change.** 1 t of pulse substitutes `a_soymeal` tonnes of soybean meal plus
`a_cereal` tonnes of feed wheat on a combined protein and energy basis, plus avoided
logistics. Field pea comes out at €298/t on farm against €252/t at the feed spot.

---

## 14. The eco-scheme uplift is marginal, and PAC aid is scheme-correct

**Problem.** The eco-scheme is paid on *all* eligible hectares, not just the legume
hectares, so attributing the full €45–60/ha to the rotation change double-counts it.
Soy also has its own, lower coupled-aid unit amount, and the forage-legume route
(€124–148/ha) requires the crop to be harvested as forage and cannot be combined with
the grain-legume aid on the same hectares.

**Change.** Only the marginal uplift is credited, and only when the legume insertion is
what crosses the diversification threshold. Soy draws its own unit amount. The forage
route requires the livestock flag. Every aid figure is flagged provisional, because
unit amounts are fixed annually once declared area is known.

---

## 15. Validation is forward in time, and the intervals are conformalised

**Blueprint.** Train three XGBoost quantiles; no validation protocol stated.

**Problems.** Random K-fold leaks, because one growing season appears in many
departments at once and weather is spatially correlated. And raw quantile regression
turned out badly miscalibrated here: its nominal 70% interval covered 39% of held-out
outcomes, because 2022–2024 sit below what 2010–2016 relationships imply.

**Change.** A three-block forward split (fit 2010–2016, calibrate 2017–2021, test
2022–2024), with the normalising baseline fitted on the fit block only, and
conformalised quantile regression with **one-sided** corrections. A symmetric
correction over-widened the upper bound to 95% coverage; one-sided scores put the
correction where the miscoverage actually was.

**Effect.** 70% interval coverage 0.389 → 0.719. Tail coverage 0.148 and 0.867 against
0.15 and 0.85 targets. The pooled lower correction is 0.206 ratio units against 0.005
for the upper — the raw model was systematically too optimistic about bad years.

---

## 16. Winter pea stopped inventing its own yield

**Problem found while testing**, after a peer session cross-checked the RPG code
tables. Agreste publishes a single *Pois protéagineux* series (`LIB_SAA` code 41)
covering both spring and winter habit, so `winter_pea` had no series of its own and
fell through the baseline chain to a hand-written reference constant of 4.0 t/ha. It
then ranked **first** among candidates in Côte-d'Or and Gers, on a number that came
from nobody's data. That is the kind of result that collapses under one question in
jury Q&A.

**Change.** A `BASELINE_PROXY` table expresses a crop with no series of its own as a
documented multiple of one that has it: winter pea is the spring-pea departmental
baseline × 1.10, reflecting that autumn-sown peas root deeper and largely escape the
June drought that caps spring peas. The provenance string ends in `_via_proxy` and the
API emits a plain-language warning as its first assumption. Lucerne, which lives in
the Agreste forage sheet this pipeline does not ingest, is flagged separately as
reference-table only.

**Effect.** Winter pea now tracks the real department series — 3.25 t/ha in Côte-d'Or,
3.51 in Eure-et-Loir, 2.41 in Gers — instead of a flat invented 3.28 everywhere.

---

## 17. Fallow land is a first-class baseline

**Problem.** The engine could only compare a pulse against an established crop. In a
live RPG 2023 sample of 1,000 Beauce parcels, **336 are declared fallow or temporarily
unexploited**. For those hectares the blueprint's central quantity — the margin the
pulse displaces — is close to zero, and the engine had no way to say so. This is also
the direct answer to the regional view's question of where the 4% → 8% hectares come
from.

**Change.** A `fallow` pseudo-crop with zero revenue and a real maintenance cost
(~€72/ha of topping and weed control) can be declared in any baseline rotation. It
cannot be selected as a candidate. It is a good preceding crop (no shared pathogen,
clean seedbed), and a nitrogen credit handed to a fallow year 3 is worth nothing
because nothing is harvested.

**The catch, which the engine now states.** Fallow counts toward the BCAE 8
non-productive area requirement and a grain legume explicitly does not, so converting
idle land means finding that area elsewhere on the farm. The validator raises it as a
warning rather than letting the attractive economics stand unqualified.

**Effect.** Same parcel, same seed, field pea in year 2: displacing spring barley is
−€180/ha with a 29% chance of gain; converting fallow is +€918/ha with a ~100% chance.

---

## 18. The RPG vocabulary is treated as year-dependent

**Problem.** The code table was written against the campaigns the API serves and
assumed the vocabulary was stable. Checked against the authoritative tables at
`data.geopf.fr/wfs/ows?TYPENAMES=RPG.<year>:codes_cultures`, it is not: **2023 has 372
codes, 2024 has only 147**, and 2024 also stops publishing `code_groupe` altogether.
Eight codes this project used disappear in 2024 (`BVF`, `CHA`, `FFO`, `J5M`, `J6S`,
`LEF`, `MIE`, `PTF`), three of which map to a crop. On 2024 data they would silently
stop matching rather than fail.

**Change.** Both vintages are mapped. A `RETIRED_IN_2024` table resolves a dropped
code through its successor where one exists. The 2024-only pulse codes that were
missing (`FVP`, `PHS`, `PHF`, `MPC`, lupin and vetch variants, legume mixes) are now
present. Fallow and BCAE 8 non-productive codes are classified separately from crops.
And `unmapped_codes()` exists so a year bump surfaces a vocabulary change instead of
quietly losing parcels.

**Validated against real data, not just the table.** Run against the 37 distinct
`code_cultu` values in 1,000 live Beauce 2023 parcels, coverage is complete: 517
rotation crops, 336 fallow, 74 non-productive, 73 other, nothing unresolved. The list
is pinned as a test so it does not need the network.

---

## 19. Two RPG code-table defects that changed an agronomic verdict

Found when a peer session working on a parallel geospatial pipeline in this repo
cross-checked the authoritative code tables.

**`PAG` was missing entirely.** It declares a grain legume without naming the genus
(*Autre légumineuse à graines* in 2023, *Autre protéagineux d'un autre genre* in 2024,
RPG group 8 *Protéagineux*). No yield or price can be predicted for an unnamed crop,
so it maps to an `other_legume` entry whose family keeps it permanently out of the
candidate list while letting it enter the rotation history. It is registered as an
*Aphanomyces* host, which is the cautious reading: a disease with no chemical control
and decade-long inoculum persistence should not be cleared because a crop name is
missing from a form.

**Effect.** A parcel whose RPG history reads `BTH, PAG, ORH` now blocks both pea and
lentil at a 2-year gap against a 6-year interval. Before, that history came back
clean and the engine cleared both. Fava bean and chickpea still pass, correctly,
being different disease groups.

**`MLT` was mislabelled.** It is Millet, RPG group 4 *Autres céréales*, in the 2023
and 2024 tables alike; this project had it as a legume-cereal mix. A user reading a
parcel history would have seen millet presented as a nitrogen-fixing precedent. The
real mixes are `MLC`, `MLF`, `MLG` (forage) and `MPC` (protein-cereal).

**A related gap closed at the same time.** Fallow campaigns were being dropped from
the inferred rotation: `JAC`, `JNO`, `SNE`, `J5M` and `J6S` mapped to nothing, so a
parcel idle for six years returned an empty history and lost precisely the
information that drives the strongest result in the engine. They now map to the
`fallow` land use, as does group `11` (*Gel, surfaces gelées sans production*).

**And one correction to an earlier conclusion.** Item 18 noted that the 2024 code
table drops `code_groupe`. True, but the 2024 **parcel** layer does not:
`RPG.2024:parcelles_graphiques` still carries `code_group` on every feature. A
group-level fallback therefore survives into 2024; only the human-readable
`libelle_groupe` is lost. The real constraint is just that API Carto serves 2015-2023.

---

## 20. Three blueprint data layers moved from reference lookup into the trained model and the carbon claim

All three are real, live-fetched, and were already used before this change — the
point here is where. Checked directly against the running code:

| Blueprint layer | Already used, since the first build | Newly added here |
|---|---|---|
| Farm Parcel Geometry & Crop History (IGN RPG v2) | `POST /api/v1/parcel` live-fetches the real parcel polygon and crop history; `agronomy.py` uses it to gate the Aphanomyces return interval and the preceding-crop suitability multiplier | A real, lagged, TRAINED feature of the yield model itself (below) |
| Costs, Prices & Subsidies (PAC 2023-2027, RICA baselines) | Fully driving `finance.py`'s Monte Carlo: coupled protein aid, eco-scheme uplift, RICA-consistent operating costs, correlated market prices | `carbon_abatement_cost_eur_per_tonne`, an explicit EUR-per-tonne-CO2e bridge between this layer and the carbon layer |
| Carbon & LCA Impact (ADEME Agribalyse) | Live-fetched, agriculture-stage-only footprints, reported per kg of protein and under both land-use-change conventions | The headline tonnage is now computed across the WHOLE Monte Carlo sample, not one point yield |

None of the three was previously a feature the TRAINED quantile model could see.
RPG crop history gated a deterministic rule; prices and costs only entered the
finance engine downstream of the model; carbon was computed once, from the median
yield, after the model had already collapsed its own uncertainty away.

**Crop history, as a real trained feature.** IGN RPG records crop history per
PARCEL. Agreste, the training data, records no such thing - its finest grain is
department-year. Inventing parcel-level rotation history for 15 years of training
rows that do not have it would be fabrication, not integration. What the training
data CAN support is the department's own historical legume footprint: Agreste
already publishes area by crop by department by year, which is exactly the series
`ml/sources.py:load_legume_pressure` turns into `legume_share_lag1` (last year's
legume area share of the department's mapped arable area) and
`legume_share_lag2to4_mean` (the three years before that). Both are lagged by
construction, so neither is contemporary with the yield they help predict, and both
are merged onto the weather panel so the Monte Carlo bootstrap carries them: when a
simulation draws a real historical (department, year) season, it gets that
season's real rotation pressure along with its real rainfall, the same way it
already gets the real heat and drought jointly.

**The result is mechanistically sensible, not just technically present.** Both
features carry real gain in the trained model (`legume_share_lag2to4_mean` ranks
26th of 38 features, `legume_share_lag1` 33rd - genuine but not dominant, exactly
what a macro-scale proxy for a parcel-scale effect should look like). Checked
against the training panel directly: higher recent regional legume share correlates
with LOWER pulse yield the following year for every pulse crop, strongest for
lentil (-0.18) and chickpea (-0.19) - the same Aphanomyces disease-pressure
mechanism the deterministic rule engine already encodes at the parcel level, now
also learned, continuously, at the regional level the training data actually
supports.

**A real gap this surfaced and had to fix first.** The weather bootstrap samples
30 years back (to capture genuine historical extremes); Agreste's series only
starts in 2010. Half of every simulation's sampled seasons would have silently
carried NaN into these two columns at inference, for a model never trained on NaN
here (training rows only ever span 2010-2024). Fixed by filling pre-2010 weather
rows with that department's own 2010-2024 mean legume share, the same fallback
`load_legume_pressure` already uses for the first 1-4 years inside the Agreste
series itself, verified to leave zero NaN anywhere in either panel.

Parcel-level RPG history is NOT overwritten by this. It keeps doing exactly what
it did before - gating the hard agronomic block and multiplying the yield
expectation for the suitability of THIS field's actual preceding crop. The two
signals are complementary, not competing: one continuous and regional, learned
from real historical covariation; one deterministic and parcel-specific, sourced
live from the one farmer asking the question.

**Carbon, propagated across the whole Monte Carlo sample.** `carbon.impact()`
took a single yield value - always the model's median prediction - and returned one
number. `carbon.impact_distribution()` runs the identical Scope 3 substitution and
nitrogen-credit accounting over every sampled yield draw the financial engine
already produced, and returns `co2e_saved_tons_q15/median/q85`. A bad year that
roughly halves the pulse harvest also roughly halves the soy meal it displaces;
the carbon claim now says so, instead of reporting a single number that implicitly
claimed more certainty than the yield model it is built on actually has. The new
median matches the old scalar calculation within 0.1 percent, so nothing the
pitch deck already said changes - the band around it is what is new.

**Costs/Prices and Carbon, tied together explicitly.** The financial delta already
carries PAC coupled aid, RICA-consistent costs and correlated market prices. Dividing
the whole-parcel 3-year delta by the median tons of CO2e avoided gives
`carbon_abatement_cost_eur_per_tonne`: a positive number is the EUR of farm income
given up per tonne avoided, directly comparable to an EU ETS or voluntary-credit
price; a negative number means the rotation is already profitable AND cuts carbon
at the same time. A marginal field pea rotation in Cote-d'Or costs about 20 EUR/tonne;
an irrigated, contracted soybean rotation in Gers comes out at -73 EUR/tonne -
carbon reduction that pays the farmer, not costs them.

---

## Smaller corrections

- **`year_index` dropped as a feature.** It was the highest-gain feature, but in a
  forward split its test values never occur in training, so the trees extrapolate it
  flat and it only soaked up capacity.
- **Two-piece normal for yield sampling.** The conformalised interval is asymmetric;
  a single symmetric standard deviation did not reproduce either stated quantile and
  drove the sampled lower tail below anything ever observed.
- **Parcel-level variance inflation.** Labels are department means, which average away
  within-department variability, so department intervals understate what one parcel
  faces. Widened by a measured factor of 1.30.
- **Mountain stations excluded** from the department weather median (above 700 m).
  Arable pulses are not grown there and they drag the heat-stress signal down.
- **Weather is bootstrapped from real department-years**, not drawn per-variable. A dry
  flowering and a hot June co-occur in nature at −0.63 correlation; independent
  Gaussian draws destroy that and understate how often a genuinely bad year happens.
- **Minimum-area filter on labels.** A 40 ha departmental lentil "crop" is a few trial
  plots whose reported yield is close to meaningless, and those rows dominated the
  15th-percentile model.
- **Agribalyse exact-phrase matching.** Passing a free-text query alongside the field
  filter let relevance ranking return a different product, which silently gave pea and
  chickpea the same footprint.
- **Risk metrics beyond the quantiles.** Probability of beating the baseline,
  conditional value at risk at 5%, probability of losing more than €100/ha, and the
  break-even food-grade fraction — which is the question advisors are actually asked.
- **Latency.** The blueprint promised 500 paths in under 30 ms. Reality on this
  machine is 2,000 *paired* paths in about 140 ms end to end over HTTP, doing roughly
  four times the work. The model is warmed at startup because unpickling it takes 1.7 s.
