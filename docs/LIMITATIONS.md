# Known limitations

Everything the authors know to be weak about this engine, stated plainly. It is a long
list on purpose: a reader who finds a limitation here can discount the figure, and a
reader who finds one that is *not* here has found a real problem worth
[filing](../.github/ISSUE_TEMPLATE/data_or_method.yml).

For which of these actually flip a recommendation rather than just moving a number, run
`make audit` — `scripts/sensitivity_audit.py` perturbs every numeric assumption and
reports the ones that change a decision.

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

On the crop the pulse is compared against:

- **The year-2 baseline crop is the largest single term in the reported difference, and
  until now it was a hard-coded constant.** Every path used
  `soft_wheat / spring_barley / rapeseed`, which matched only 2 of each department's top
  3 Agreste crops in 32 of 42 departments — spring barley is in the top three of only
  six. It is now derived per department by `scripts/build_dept_rotations.py` from the
  same Agreste area series that supplies the yield labels. That changed the rotation in
  38 of 42 departments and **made pulses look worse, not better**: the displaced crop is
  usually rapeseed rather than the cheapest cereal in the rotation, and two of eight
  test cases flipped from positive to negative. The old figures were optimistic because
  the comparison was against a low-value crop.
- **The comparator is the best-evidenced alternative, not the most widely grown one.**
  Only soft wheat, spring barley and rapeseed have Agreste departmental yield histories
  here. Winter barley, durum wheat, grain maize and sunflower resolve to a hand-written
  national constant with no departmental signal, so they are not used as comparators —
  in **23 of 42 departments** the department's actual largest alternative is one of
  those, and the response says so per department rather than absorbing it silently.
  Ingesting those four Agreste yield series is the fix, and it is a data task.
- **In eight departments the derived rotation covers under half the arable area** (Aude
  21%, Landes 12%). Those are durum/maize/sunflower country and the figures should be
  read as a wheat-and-rapeseed field in that climate, not as the department.
- **The comparator is still not in the sensitivity audit.** Unlike the grading pass rate
  and the haulage rate, perturbing it means re-simulating a different crop's margin
  rather than repricing existing draws, so it cannot use `robustness.py`'s cheap path.

On the two newest layers specifically:

- **`P_human` is now the headline number and it is still not a trained classifier.** No
  French open dataset records per-lot grading outcomes, so there is no label to fit. It
  is a documented hazard model and the API says so. Promoting it to the lead makes
  obtaining per-lot grading records from a cooperative silo the single highest-value
  dataset a partner could contribute — more so than before, not less.
- **Food-tier demand rests on two soft parameters.** Current intake is a central estimate
  in a 1.7–2.5 kg per-capita band, and the collective-catering meal count is an
  order-of-magnitude planning figure. FranceAgriMer publishes pulse market balances;
  wiring those in would replace both with measurements.
- **Regional catering volumes are the national meal count scaled by population**, because
  meal counts are only published nationally. Transparent scaling, not a regional
  statistic.
- **Regional food supply assumes the area target is met *and* that rotation return
  intervals permit it.** They may well not: a 6-year *Aphanomyces* interval across the
  whole host group disqualifies land that looks suitable. Computing the rotation-*eligible*
  hectare surface from RPG vintages is the obvious next build, and until it exists the
  supply figures are an upper bound.
- **The climate sensitivities are fitted on interannual variation**, which is a
  space-for-time substitution: sound for thermal variables where the mechanism is direct,
  weak for rainfall where circulation change matters. The fitted correlation travels with
  every coefficient so a reader can discount it, and variables below |r| = 0.15 are left
  unshifted. This is a screening projection, not a downscaled climate run — for that, use
  DRIAS-2020.
- **Applying the yield and grading models at +2.7 °C or +4 °C extrapolates beyond their
  calibration range.** The horizons are there to bound the question, not to be acted on
  at face value. The same exchangeability problem that requires annual conformal
  re-calibration applies with more force here.
- No weed-pressure or mechanical-weeding cost line exists, while the sector names
  herbicide withdrawal on legumes as an existential threat. Margins therefore assume weed
  control remains feasible.

On the regional engine:

- **A department's arable hectares are split between its communes in proportion to
  cadastral area.** Agreste publishes nothing at commune level to measure that split
  against. It is right on average and wrong for any individual commune — one that is
  mostly forest is credited with arable land it does not have. The error averages out
  over the hundreds of communes inside an 80 km haulage radius, which is the scale the
  siting decision is made at, but it is visible at the scale the map is drawn at. This is
  the single largest assumption behind the most persuasive screen in the product, and it
  is also stated in the `/stranded-surface` provenance and in the map caption.
- **Candidate sites are communes above 2,000 people, standing in for an inventory of
  cooperative silos**, which is not open data. A market town of that size in an arable
  department is where a silo, a weighbridge and three-phase power are, which is what the
  capex figure assumes it is building onto. A cooperative would substitute its own site
  list and the optimiser would not otherwise change.
- **Distance is great-circle inflated by a 1.32 road detour factor, not routed.** Applied
  uniformly, so it cannot flatter one candidate over another, but it understates haulage
  in hilly terrain. A routed distance matrix is the obvious upgrade and is isolated in one
  function.
- **The baked department profiles use one soil archetype and one baseline rotation per
  department.** They exist because running 42 live Monte Carlos per request took over two
  minutes. Any real parcel should go through `/simulate-rotation` with its own soil,
  rotation and RPG history — which is what the farmer view does.
- **The greedy guarantee covers the uncapacitated problem.** Throughput caps break
  submodularity and are applied afterwards as an allocation step, so the (1 − 1/e) bound
  does not formally cover the reported post-capacity hectares. The exact HiGHS check is
  run on the same uncapacitated objective.
- **The commune-level *Aphanomyces* constraint is an aggregate, not a parcel check.**
  There is no commune-level rotation history, so what is enforced is the steady-state
  ceiling — a pulse on a 5-year return interval cannot exceed a fifth of a rotation. That
  holds regardless of history, but it will clear individual fields that a parcel-level
  check would block.
- **The livestock holding directory is illustrative on identity and real on geography.**
  Locations are real IGN commune centroids and the count per department is scaled by a
  measured land-use ratio, but names, herd types and herd sizes are generated with a
  fixed seed. No real farm is described.

This is a hackathon prototype. It does not replace advice from a Chamber of
Agriculture or a cooperative agronomist, and no rule table substitutes for a soil
*Aphanomyces* test.

