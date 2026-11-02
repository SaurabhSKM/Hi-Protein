# What the site does, and what works

Plain-language tour. No code, no formulas. If you are showing this to someone, demoing
it, or writing about it, this is the page to read first.

Last verified: **2 November 2026**, against the running app. Everything below was
checked by hand on that date — 299 automated tests passing, and all 19 API routes
called directly to see what came back.

---

## In one paragraph

A farmer in France can grow lentils, chickpeas, peas, fava beans or soy. Whether that
pays depends on one thing more than any other: **does the harvest pass the grade for
human food, or does it get sold as animal feed at about a third of the price?** On green
lentil that gap is roughly €630 per tonne. This site estimates the probability of
clearing food grade for a specific field, prices the three-year consequence against what
the farmer would otherwise have grown, and then scales the same question up — what a
region eats versus what it could produce, where a missing sorting machine is the only
reason land doesn't pay, and whether any of it still holds in 2050.

---

## The six screens

### 0. Landing page

The front door. Explains the problem and has buttons through to each view. Nothing is
computed here.

### 1. Farmer view — "should I plant this, on this field?"

**What you do:** pick a department, a soil type and a field size, or click a real field
on the map. Choose which pulse crop to consider. Optionally say you keep livestock, or
pick a future climate horizon.

**What you get back:**

- Whether the crop is even allowed there — disease return intervals, sowing window, soil
  pH. This can come back as a hard "blocked", and should.
- A yield range, not a single number: a low, middle and high estimate with honest
  uncertainty attached.
- **Where the harvest ends up.** The headline: the chance it grades as human food, and
  the money consequence if it doesn't.
- The three-year money comparison against the rotation the farmer would otherwise run,
  shown as a per-hectare figure and a whole-field figure.
- The downside, stated bluntly: the worst 5% of outcomes, the chance of losing money,
  and the price per tonne at which this becomes the better choice.
- How far the nearest optical sorter is, converted into a cost per hectare. If haulage
  is the only reason the field loses money, it says so.
- Who would buy a failed lot — a real livestock holding within 25 km, priced at what the
  feed actually replaces.
- Carbon, per kilo of protein.
- A printable dossier for an advisor, with a pre-sowing checklist.

**Status: working.** This is the most complete screen in the product.

### 2. Food view — "what does this region eat, and could it grow it?"

Population, how much pulse protein those people eat, and how much the region's land
could grade for human food if the 2030 area target were met. Per region, and per
department where margin and food outcome disagree.

**Status: working.** Instant, because the numbers are precomputed (see
[Why some screens are instant](#why-some-screens-are-instant)).

### 3. Region view — "where should we put the infrastructure?"

A map of about 18,000 real French communes, coloured three ways: a pulse pays here
today; it would pay if a sorter were within range; it would not pay either way. Then one
button that places up to 26 new optical sorters where they unlock the most land, and
shows the hectares, tonnes, CO₂e and national-share movement against the €450k-per-unit
cost.

**Status: working.** This is the screen that sells the project, and the one resting on
the biggest single assumption — a department's arable hectares are split between its
communes in proportion to land area, because nothing is published at commune level to
measure that against. It is right on average and wrong for any individual commune. That
caveat is printed on the map itself, and it is the first entry in
[LIMITATIONS.md](LIMITATIONS.md).

### 4. Land view — "what actually happened to pulse area, and why?"

The history: pulse area across 93 departments from 2010 to 2024, a choropleth of who
grew more and who grew less, real Beauce fields tracked across ten years of land
registry, and an attribution panel that asks what explains the movement.

**Status: working — and it reports that it cannot answer the "why".** That is a real
finding, not a failure. See [the next section](#the-thing-that-looks-broken-and-isnt).

### 5. Method view

Validation metrics, the stated limitations, where each number came from. The page for a
sceptical reader.

**Status: working.**

---

## The thing that looks broken, and isn't

There are **two** models in this project, and they behave very differently. This trips
people up, so it is worth being precise.

### Model 1 — the yield model: works, with modest real skill

Predicts yield from weather, soil and department. Trained on 2010–2016, calibrated on
2017–2021, tested on 2022–2024 — forward in time, never shuffled.

It beats a "just use the long-run average" baseline by **14%** on the middle estimate
and **38%** on the low estimate. The high estimate is roughly a wash (−4%). Those are
modest numbers and the model report says so in those words: conformal calibration here
buys *honest* coverage rather than sharpness. For a planting decision, an interval that
is correctly wide beats a narrow one that is wrong 60% of the time.

**Verdict: working as intended.**

### Model 2 — the adoption model: works, and returns a null result

Different question entirely. Not "how much will this field yield" but "**why** did
French farmers change how much pulse they planted?" It tries to attribute the
year-on-year change in a department's pulse area to last season's weather and the
department's soil.

The answer it gives is: **weather explains nothing.**

| Crop | Explained by a national shock | By the department itself | By weather and soil |
|---|---|---|---|
| Green lentil | 18.7% | 2.6% | none measurable |
| Chickpea | 13.7% | 5.5% | none measurable |
| Field pea | 37.3% | 1.8% | none measurable |
| Fava bean | 17.2% | 9.7% | 1.3% |
| Soybean | 14.8% | 11.8% | none measurable |

**If you have looked at this and concluded the model is broken, here is why it isn't.**
The same model fitted the naive way — scored on the data it trained on — reports **69.6%**
explained for green lentil. That figure is pure overfitting. Scoring it properly, held
out by year, gives the −26.8% in the table: adding weather makes the prediction *worse*
than leaving it out. The gap between 69.6% and that is the measurement working. A
negative number here is what an honest test of a useless feature set looks like.

So the conclusion is a real one, and it is in the report's own words:

> A national shock common to every department in the same year is the largest single
> identified factor in year-on-year pulse area change. […] On this evidence the shift to
> pulses is **NOT weather-driven**. The most likely drivers — price, PAC coupled aid and
> contract availability — are exactly the series this repo has no usable history for.

The French farm-gate price series from Eurostat ends in 2016, carries unit errors in
2010–2011, and omits chickpea and fava bean entirely. It was checked and formally marked
NOT USABLE. There is no historical series for contracts or sorting capacity at all.

**Verdict: working. The null is the output.** It is also the strongest argument in the
pitch for why a cooperative's own data matters — the missing series are precisely what a
partner could contribute.

If you want to change this screen, don't remove the held-out scoring that revealed the
null. That would restore the 69.6% and the number would be fiction.

---

## Known defects

One, found on 2 November 2026 by calling every endpoint directly:

**`GET /api/v1/climate-outlook` returns a 500 when given an invalid soil type.** Every
other endpoint rejects a bad soil with a clear 422 listing the six valid values; this one
crashes instead, because its soil parameter is typed as free text rather than as the
restricted list. **It does not affect the app** — the UI only ever sends valid soils — so
this is a hardening fix for anyone calling the API directly, not a user-facing bug. The
fix is one line in `backend/app/main.py`.

Nothing else failed. For the much longer list of things that are *weak* rather than
broken — assumptions, coarse data, missing series — see [LIMITATIONS.md](LIMITATIONS.md).
That list is long on purpose.

---

## What is real, and what is demo data

This matters more than anything else on this page if you are presenting to a judge or a
ministry reader.

**Real, genuinely fetched and parsed:**

- Agreste departmental yields and areas, 2010–2024
- Météo-France monthly climate series, 42 departments
- IGN parcel geometry and crop history (the real fields you click on the map)
- IGN commune geometry, all 18,157 of them
- ADEME Agribalyse carbon and life-cycle impacts
- PAC 2023–2027 subsidy unit amounts

**Deliberately not real, and labelled as such everywhere it appears:**

- **Buyer contract terms** — prices, volumes and premiums are illustrative. They are not
  commercial offers and no named company has agreed to them.
- **The livestock holding directory** — the locations are real IGN commune centroids and
  the count per department is scaled from measured land use, but the holding names, herd
  types and herd sizes are generated. No real farm is described.

Every number in the API also carries a tag: `[LIVE]` fetched this run, `[REPO]`
committed reference data, `[JUDG]` an authored judgement. A ministry reader will check
these, so they are kept accurate.

---

## Why some screens are instant

The farmer view runs its simulation live, which takes about a quarter of a second. The
region and food views answer in about 2 milliseconds, because their numbers were
computed ahead of time by `make profiles` and stored.

This is worth knowing for one reason: **if the margin calculation changes and nobody
re-runs `make profiles`, the region and food views will quietly keep showing the old
numbers.** They read the same precomputed figures the farmer view simulates from,
specifically so the two cannot disagree — and a stale file is the one way they can.
`GET /health` reports when the bake was last built.

---

## What is not built

Not defects — things that were out of scope and are the obvious next steps:

- **Grading outcomes are modelled, not learned.** The headline probability is a
  documented hazard model, because no French open dataset records whether individual lots
  passed food grade. Getting per-lot grading records from a cooperative silo is the single
  highest-value dataset a partner could contribute.
- **Haulage distance is straight-line, inflated by a 1.32 road factor.** Not routed.
  Applied uniformly so it cannot flatter one candidate site over another, but it
  understates hilly terrain.
- **Candidate sorter sites are towns above 2,000 people**, standing in for an inventory
  of real cooperative silos, which is not public. A cooperative would drop in its own
  site list and nothing else would change.
- **Four crops cannot be used as comparators** — winter barley, durum wheat, grain maize
  and sunflower have no departmental yield history here, so they resolve to a national
  constant. In 23 of 42 departments the real largest alternative crop is one of those four.
  The response says so per department rather than hiding it. Fixing it is a data task.
- **The 2050 and 2100 climate figures extrapolate beyond where the models were
  calibrated.** They are there to bound the question, not to be acted on at face value.

---

## Where this runs

Currently on AWS CloudFront in front of the workshop container, served under `/app/`.

Nothing in the code depends on AWS, so moving it is a matter of finding somewhere to run
it. `make docker` builds a single 605 MB image containing the API, the built frontend,
the trained model and the baked profiles; that image was built and smoke-tested on
2026-11-02 and all 23 checks passed inside it, including the live parcel fetch. For
hosting options — Vercel for the frontend, where the backend has to go instead, and what
to do about the data — see [DEPLOYMENT.md](DEPLOYMENT.md).
