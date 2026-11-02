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

---

# Part II: the regional engine

Items 1-20 above concern the farmer's half of the product. What follows was built after
a gap analysis found the planner's half was a six-department sketch with no optimiser
behind its headline button. Same rule as above: each item changes a number or a claim.

---

## 21. Infrastructure distance became a cost instead of a flag

**Before.** The only consequence of having no optical sorter within 80 km was a flat
0.12 multiplicative cut to `P_human` and the loss of an optical-sorted price premium.
The €0.45/t/km haulage rate the blueprint specified appeared nowhere in `finance.py`.

**Problem.** That makes distance a QUALITY story. It is a COST story, and a continuous
one. Without it there is no way to compute the central category of the regional
view — a parcel that is agronomically ideal, passes food specification, and still loses
money purely because of where it is. "Stranded potential" was a label with no
arithmetic under it.

**Change.** `logistics.py` charges incremental haulage inside the Monte Carlo. Two rules
keep it honest:

- **Only the haul beyond 25 km is charged.** A farm already hauls cereals to its local
  collection silo and that cost sits inside the RICA operating cost BOTH arms carry.
  Charging farm-to-sorter in full would double-count the first 25 km and would charge
  the pulse arm for a trip the baseline cereal arm also makes — manufacturing a penalty
  out of an accounting error.
- **Only food tonnes are charged.** The downgraded fraction needs no sorting. So a bad
  grading year hauls LESS and pays less, which partly offsets the grading loss instead
  of compounding it. The sign is tested.

**Also not charged, deliberately:** the station's €38/t toll cleaning-and-sorting fee.
Whether it falls on the farmer or inside the buyer's margin depends on the contract, and
the contract prices this engine uses are quoted delivered to the buyer. It stays in the
reference data because it is the REVENUE line that pays for a new unit, and that is the
only place it is used.

**Effect.** A real stranded parcel: Mesnil-en-Ouche (Eure), nearest sorter 132 km by
road, €48.24/t on food tonnage, €95/ha. The parcel loses €16/ha against cereals — so
€95/ha of haulage is the entire reason it is negative, and the response says exactly
that.

**A finding this produced, not an assumption fed into it.** Because haulage is linear
and the food premium is finite, each crop has a maximum economically viable haul:

        max_km = 25 + (food_price − feed_price) / 0.45

Field pea's food-versus-feed spread is €78/t, so it stops paying for its own haul at
roughly **198 km**. Green lentil's spread is €565/t and would pay to cross the country
(~1,280 km). Beyond its own threshold a crop has NO food-grade share that makes sorting
access worth paying for, and `breakeven_human_fraction` correctly returns "no break-even
exists". A single national 80 km rule treats pea and lentil identically; it should not.

---

## 22. Six departments became forty-two, on real Agreste areas

**Before.** `departments.json` held six hand-written entries whose `arable_ha` and
`pulse_ha` were openly labelled "order-of-magnitude planning figures".

**What was already available and unused.** 42 departments have real Météo-France weather
in `data/processed/weather_panel.csv`, 40 have real Agreste yield labels, and
`dept_soils.json` already covered all 42. The department table was the only thing
capping the product at six.

**Change.** `scripts/build_departments.py` generates all 42 from data on disk: areas from
the Agreste SAA departmental series (mean of 2022-2024), centroids as the
cadastral-area-weighted mean of IGN ADMINEXPRESS commune centroids.

**A mistake made and corrected while building it.** The first version summed only the
eight crops this project models. That put Pyrénées-Atlantiques at 28,200 ha of arable
land and therefore a **37.7% pulse share** — a maize department shown as having already
smashed the 2030 target, because maize, durum wheat, sunflower and winter barley were
missing from the denominator. Fixed by using Agreste's own published subtotals: all
cereals (row 27) + all oilseeds (36) + all grain legumes (46).

**An independent check that the derivation is right.** Across the 42 departments the
generated figures give 7,965,500 ha of arable land and 258,513 ha of food-tier pulses — a
**3.25% share**, against the 4.0% national baseline the policy target is written
against. Nothing was tuned to produce that. The small gap is the right sign: these 42 are
the cereal core, where pulse share is below the national average.

`pulse_ha` is Agreste row 46, grain legumes only. Soybean is reported separately as
`soybean_ha` because Agreste classes it as an oilseed, and folding it in would quietly
inflate the share across the south-west.

---

## 23. The regional view stopped re-running the Monte Carlo per request

**Problem created by item 22.** `/regional-overview` ran a full simulation per department
per candidate pulse. At six departments that was about four seconds. At forty-two it was
over two minutes, and `/food-demand` was 62 seconds per call. Neither is a dashboard.

**Change.** `scripts/build_region_profiles.py` bakes, per department, the three-year
margin advantage of every candidate pulse at ZERO incremental haulage — run twice, with
and without sorting access, because the grading hazard model steps at the access
threshold. 800 paths each, about 70 seconds offline, loaded from disk at request time.

**Effect.** `/regional-overview` 316 ms, `/food-demand` 3.2 s, and the whole test suite
back from 148 s to 38 s with 44 more tests in it. The map, the department table, the food
view and the siting optimiser now all read the SAME baked numbers, so they cannot
disagree with each other — which they could before, since each ran its own simulation
with its own seed.

---

## 23b. The cache grew a climate dimension, and learned to record a negative

**Problem left behind by item 23.** The bake covered the observed horizon only, and
"absent from the bake" was overloaded to mean two different things. Both leaks put a
Monte Carlo back inside a request:

1. **Any projected horizon had no cache to read.** The food view offers a horizon
   selector, and picking anything other than `observed` dropped `/food-demand` onto the
   live path — 42 departments × 6 pulses, measured at **71 s per request, on every
   request**. No browser waits that long, so three of that tab's four options looked
   broken rather than slow.
2. **A department with no viable pulse was simply missing.** Tarn (81) and
   Tarn-et-Garonne (82) are boulbène at pH 5.9, which blocks every legume the engine
   recommends — a correct answer, and a permanent one. But the loop could not tell that
   from "never baked", so it re-simulated both on **every** request to rediscover their
   soil is too acid, then discarded the result: ~3 s per call, for nothing.

**Change.** `build_all_horizons` bakes every horizon into `region_profiles.json` under a
`horizons` key (the observed set stays at the top level, so every existing reader is
untouched), and records the no-viable-pulse departments per horizon in
`_meta.no_viable_pulse`. `siting.profiles(horizon)` is memoised per horizon;
`siting.unviable_departments(horizon)` exposes the negative result so a known "no" costs
a set lookup. `classify()`, `/regional-overview` and `/food-demand` memoise their
assembled results, and `lifespan` warms exactly what the bake covers — printing a loud
warning instead of silently computing for minutes when the bake is absent.

**Effect.** Measured end to end:

| | before | after |
|---|---|---|
| `/food-demand` observed | 4.3 s *every call* | 0.00 s |
| `/food-demand` projected horizons | 71 s *every call* | 0.00 s |
| `/regional-overview` | 0.23–0.54 s per call | 0.00 s |
| cold process, bake missing | 128 s **inside the first request** | refuses silently; warns at startup |

The bake costs about six minutes offline for five horizons (`make profiles`), or ~70 s
for the observed horizon alone (`make profiles-fast`). `/health` reports which horizons
the bake covers and which caches are warm, because a missing horizon there is the
difference between a dictionary lookup and a live Monte Carlo.

---

## 24. A real 18,157-point commune demand surface

**Before.** The regional map drew six circles at department centroids. The blueprint
asked for 10,000+ parcels colour-coded, and `ign_rpg.py` is a point-query client with 36
cached responses — there was no data path to it at all.

**Change.** `scripts/build_communes.py` fetches every commune in the 42 departments from
IGN ADMINEXPRESS via WFS: **18,157 real communes** with real boundary-derived centroids,
real cadastral area, real INSEE department and region codes. 2.8 MB on disk.

**Why communes rather than RPG parcels, stated because it is a real choice.** The siting
question moves at the scale of tens of kilometres. There are 9.5 million RPG parcels,
served with full polygon geometry; aggregating them nationally would be a day of
downloading to produce a surface that is identical at 80 km resolution to this one.
Communes are the right grain and are honest about being an aggregate.

**What is assumed, and the bound on the error.** A department's real Agreste arable
hectares are split between its communes in proportion to cadastral area, because Agreste
publishes nothing at commune level to measure that split against. It is right on average
and wrong for any individual commune — one that is mostly forest is credited with arable
land it does not have. The error averages out over the hundreds of communes inside an
80 km haulage radius, which is the scale the siting DECISION is made at, but it is
visible at the scale the MAP is drawn at. Both the API provenance and the map caption say
so.

**The four statuses, and the distinction the whole regional argument rests on.**

| Status | Meaning | Communes |
|---|---|---|
| `viable` | A pulse pays at the sorter distance this land actually has | 6,387 |
| `stranded` | Loses money at the distance it has, WOULD pay with a sorter in range | 4,486 |
| `uneconomic` | Loses money even with a sorter next door | 6,775 |
| `unmodelled` | No viable pulse profile for the department | 509 |

Only `stranded` is something a capital grant can fix. Conflating it with `uneconomic` is
how infrastructure money gets spent where no amount of sorting capacity would help, and a
test pins that stranded implies `delta_now < 0 ≤ delta_if_served`. Classification uses a
€1/ha band around break-even, because a category boundary drawn at exactly zero gets
decided by rounding noise several orders of magnitude below the yield model's own error.

**Total: 81,418 ha stranded, worth €9.6M of three-year margin currently lost to
haulage.**

---

## 25. The siting optimiser, with its guarantee stated and then measured

**Before.** Nothing. No facility-location code of any kind.

**Change.** `siting.py` solves capacitated facility location over the 18,157 commune
demand points against ~2,100 candidate sites.

**The decomposition that makes it interactive.** Simulating every (commune, site) pair
would be ~38 million Monte Carlos. It is also unnecessary, because haulage enters the
margin linearly:

        delta(km) = delta(0) − food_tonnes_per_ha × 0.45 × max(0, km − 25)

So the simulation runs once per department and every pair is an exact closed-form shift.
**That equivalence is the load-bearing claim of the regional engine, so it is tested
directly** against real simulations at 40, 120 and 300 km rather than assumed.

**The algorithm and what it actually guarantees.** The objective is
`F(S) = Σ_j w_j · max_{i∈S∪E} u_j(i)`, the classical uncapacitated facility location
objective, which is monotone and submodular — so greedy marginal gain is within
(1 − 1/e) ≈ 0.632 of the optimum (Nemhauser, Wolsey & Fisher 1978). That is a proof, not
a hope.

**And then the worst case is checked against the realised one.** The same problem is also
solved exactly with HiGHS (`scipy.optimize.milp`) over a reduced candidate set **forced
to contain greedy's own picks** — without that the comparison is not apples to apples,
and the first version of this duly reported greedy at "103% of optimum", a meaningless
number. Corrected, greedy comes in at **99.7%** of the exact optimum against the 63.2%
worst-case floor.

**Why exact verification is off by default.** Greedy is 40 ms; HiGHS is 3.7 s. A planner
dragging a slider needs the first, a jury asking "how do you know that is optimal" needs
the second. Both are available and the answer does not change.

**Capacity breaks submodularity**, so it is applied afterwards as an allocation step:
each unit serves its assigned communes up to 10,000 t/yr and overflow spills to the next
unit with slack. Reported hectares are post-capacity, and the guarantee above is
explicitly scoped to the uncapacitated relaxation.

**The Aphanomyces constraint, in its aggregate form.** There is no commune-level rotation
history to check, so the parcel-level hard block has no direct analogue. What does hold
regardless of history is the steady-state ceiling: a pulse on a 5-year return interval
cannot occupy more than a fifth of a rotation. Convertible hectares are capped by the
binding one of that ceiling and the gap to the 8% target.

**Effect.** 12 units at €5.4M capex: 37,594 ha unlocked, 120,000 t of food-grade pulses,
142,151 t CO₂e avoided, pulse share 3.24% → 3.72%.

**Where this disagrees with the blueprint.** The blueprint's headline was "+3,850
hectares unlocked" for ONE €450k unit. The honest figure is **2,300-4,400 ha per unit**,
and the binding constraint is not geography but the 10,000 t/yr throughput of the
machine: every sited unit in the national run hits 100% utilisation. So the blueprint's
per-unit hectare claim is roughly right and its implied path to 8% is not — closing the
gap needs on the order of a hundred units, not one, and the tool now says so.

---

## 26. The livestock fallback became a counterparty, and then got smaller

**Before.** `has_livestock_ugb_5` was a checkbox meaning *this farmer owns herbivores*,
which floored the feed price at the on-farm substitution value (€298/t for field pea
against €252/t spot). Real and well-argued — but it only helps farms that already have
animals, and the farms with the most cereal land mostly do not. There was no breeder
directory, no distance matching, and no view of what the breeder gets.

**Change.** `breeders.py` matches a downgraded lot to neighbouring livestock holdings
within 25 km and prices **both sides** of the trade: what the lot is worth in a ration,
what the breeder pays, what each side keeps, and how much imported soybean meal stops
being bought. The surplus split (55% to the farmer) is a stated negotiating assumption,
not a hidden one. `finance.simulate` takes a `fallback_feed_floor_eur_t` that floors the
downgraded fraction for a farm with no animals of its own.

**The directory: real geography, illustrative identity.** 1,600 holdings, each on an
actual IGN commune centroid, so every distance is a real distance between real places.
The NUMBER per department is scaled by the share of that department's cadastral area not
in the Agreste COP sheet — a measured proxy for grass and forage area. Names and herd
sizes are generated from published per-herd-type averages with a fixed seed. No real farm
is described. Same standard `buyers.json` is held to, and the API says so in three
fields.

**Three limits enforced in the arithmetic rather than mentioned in a footnote.**
Inclusion caps (raw pulses carry anti-nutritional factors, so monogastrics take 15-22% of
concentrate and ruminants 30-35%, and `absorbs_whole_lot` reports when a lot is too big);
the 25 km radius (holdings beyond it are dropped, not stretched); and a near miss is
reported as a near miss — "nearest is 26 km against a 25 km radius" is a different fact
from "none exist", and a user staring at an empty list cannot otherwise tell which.

**Two findings that cut against the blueprint's claim, both found by testing rather than
asserted around.**

**First: chickpea has no fallback contract worth signing.** Its commodity feed price is
~€295/t, at or above its ~€294/t value in a livestock ration. No local holding can outbid
the feed market for it. `fallback_floor_eur_t` returns None rather than quoting a floor
equal to the spot price and calling it de-risking.

**Second, and more important: this is a revenue floor, not downside insurance.** The
intuitive pitch is that a bad year downgrades more of the lot, so the contract's value
should concentrate in the left tail. Measured, it does not. The loss tail is driven mostly
by LOW YIELD, and a low-yield year has fewer tonnes to downgrade, so poor grading and
poor yield nearly cancel in downgraded tonnage — **1.49 t/ha in the worst 15% against
1.54 t/ha overall**. The result is a near-flat uplift of about **€46/ha**, only marginally
larger in the tail.

**So the blueprint's headline number is not reproducible.** It claimed the fallback flips
CVaR₁₅ from −€240/ha to +€58/ha, a €298/ha swing. The substitution economics support
about €25/t of uplift on the downgraded fraction, which is €35-50/ha. The mechanism is
real, it is now priced on both sides, and it is roughly six times smaller than claimed.
The UI states this where a reader will see it rather than in a footnote.

---

## 27. Risk machinery that was computed, returned, and never rendered

**Problem.** `serf_curve`, `risk_sharing`, `tolerance_threshold` and
`minimum_viable_contract` have been computed in `risk.py` and shipped in the API response
since the first build. No component rendered any of them, so the most decision-useful
number in the whole response was invisible.

**Change.** `RiskPreferencePanel` renders the minimum viable contract as a price-by-volume
table, the SERF curve as certainty-equivalent advantage against risk aversion, and the
risk-sharing diagnostic.

**Why `minimum_viable_contract` is the one that matters.** It answers the question an
advisor is actually asked across a kitchen table — not "what is the distribution of my
margin" but "what price would make this worth my while". On the stranded Eure parcel:
*becomes preferred at €342/t on 100% of expected volume*. And contracting more volume
lowers the required price, because what the premium buys is certainty rather than
revenue — which is the argument a cooperative needs to hear.

---

## 28. The downside is now drawn twice, on one scale

**Problem.** The fallback was a checkbox third in a list of three. Ticking it replaced the
figure and the old one vanished, so a user had to remember a number to see a change.

**Change.** `FallbackPanel` draws both bars on a shared scale that always includes zero.
The before bar stays put and the after bar grows out of it. That is the whole argument of
the product in one picture — and, given item 26, a picture that shows a €46/ha
improvement rather than a €298/ha one.
