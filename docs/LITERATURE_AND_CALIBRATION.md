# Literature grounding, and what it says about this engine's parameters

Every reference below was resolved through the Crossref and Semantic Scholar APIs
during this session; DOIs and citation counts are as returned, not from memory. The
point of the exercise was not a bibliography for its own sake — it was to find out
whether the engine's agronomic and economic parameters sit inside the published
ranges, and whether its results agree or disagree with the peer-reviewed assessments
of the same question.

Two of the answers change how the project should be pitched.

---

## 1. The core references

| Reference | Why it matters here |
|---|---|
| **Magrini et al. (2016)**, *Ecological Economics* 126:152–162, `10.1016/j.ecolecon.2016.03.024` (309 cites) | Lock-in analysis of grain legumes in **the French agrifood system specifically**. The direct academic statement of this project's problem: the barrier is not farmer awareness. |
| **Meynard et al. (2018)**, *Agron. Sustain. Dev.* 38, `10.1007/s13593-018-0535-1` (281 cites) | Socio-technical lock-in hinders crop diversification **in France**. Companion framing to Magrini. |
| **Preissel et al. (2015)**, *Field Crops Research* 175:64–79, `10.1016/j.fcr.2015.01.012` (338 cites) | The systematic review of grain-legume **pre-crop benefits** in Europe: 29 experiments on following-cereal yield, 19 gross-margin studies. The calibration source for `nitrogen.json`. |
| **Reckling et al. (2016a)**, *European Journal of Agronomy* 76:186–197, `10.1016/j.eja.2015.11.005` (191 cites) | Cropping-system assessment framework. Finds grain-legume gross margins **lower** than non-legume systems *despite* pre-crop effects. |
| **Reckling et al. (2016b)**, *Frontiers in Plant Science* 7:669, `10.3389/fpls.2016.00669` (196 cites) | Same framework across five European regions. Grain legumes **reduced** gross margins in **3 of 5** regions; forage legumes raised them in 3 of 3. |
| **Zander et al. (2016)**, *Agron. Sustain. Dev.* 36, `10.1007/s13593-016-0365-y` (206 cites) | Grain legume decline and potential recovery in Europe. |
| **Watson et al. (2017)**, *Advances in Agronomy*, `10.1016/bs.agron.2017.03.003` (296 cites) | Standard reference on grain legume production and use in European systems. |
| **Hardaker et al. (2004)**, *AJARE* 48:253–270, `10.1111/j.1467-8489.2004.00239.x` (334 cites) | **SERF** — stochastic efficiency with respect to a function. The method now implemented in `services/risk.py`. A 2010 comment at `10.1111/j.1467-8489.2010.00498.x` refines it. |
| **Romano, Patterson & Candès (2019)**, *NeurIPS 32*, arXiv `1905.03222` | **Conformalized Quantile Regression.** The method in `ml/train.py` that fixed this project's worst measured defect: raw quantile regression claimed 70% interval coverage and delivered 38.4% on a forward-split test block. CQR restored it to 72.8%. Implemented with ONE-SIDED corrections, because the measured lower-bound error was 0.205 ratio units against 0.011 on the upper. |
| **Nemhauser, Wolsey & Fisher (1978)**, *Mathematical Programming* 14:265–294, `10.1007/BF01588971` | **Greedy maximisation of a monotone submodular set function is within (1 − 1/e) ≈ 0.632 of the optimum.** The guarantee behind the sorter-siting optimiser in `services/siting.py`. Uncapacitated facility location satisfies the conditions; throughput caps do not, so they are applied afterwards as an allocation step and the bound is scoped to the relaxation. Realised against an exact HiGHS solve on this data: **0.9975**. |
| **Anderson & Dillon (1992)**, *Risk analysis in dryland farming systems*, FAO Farm Systems Management Series 2 | The relative-risk-aversion classification (0 = risk neutral through 4 = extremely risk averse) that `services/risk.py` sweeps across to produce the SERF curve. Used as the scale in Hardaker et al. |
| **Huangfu & Hall (2018)**, *Mathematical Programming Computation* 10:119–142, `10.1007/s12532-017-0130-5` | **HiGHS**, the dual-revised-simplex / MIP solver reached through `scipy.optimize.milp`. Used to verify the greedy siting answer exactly rather than asserting the worst-case bound was good enough. |

---

## 2. The engine independently reproduces the European consensus

This is the most useful thing the literature review produced, and it converts a
potential attack into the project's strongest validation.

Scanning the engine across three departments × six candidate pulses against a
productive cereal baseline, **16 of 18 cases return a negative expected delta** — the
pulse loses on expected value. The exceptions are irrigated soybean in Gers (positive
at every risk attitude) and winter pea in Côte-d'Or (marginally positive, flipping at
relative risk aversion ≈ 0.97).

That is exactly what the peer-reviewed assessments find:

- Reckling et al. 2016a: *"In arable systems with grain legumes, gross margins were
  lower than in cropping systems without legumes **despite taking pre-crop effects
  into account**."*
- Reckling et al. 2016b: grain legumes reduced gross margins in **3 of 5** European
  regions.
- Preissel et al. 2015: only **35 of 53** modelled legume rotations were competitive
  with comparable non-legume rotations.

So the engine is not an outlier producing inconvenient numbers — it agrees with the
published literature on the general case, using independent French data and a
different method. **And then it locates the exception the literature does not isolate:
idle land.** Converting fallow, where no crop margin is displaced, takes the same field
pea from roughly −€180/ha to +€918/ha at p≈0.998.

The pitch line this supports: *we reproduce the European literature's finding that
pulses displacing a productive cereal lose money, and we identify the specific hectares
where that reverses.* That is a far stronger claim than "our model says pulses pay",
and it is robust to a jury member who knows this field.

---

## 3. Calibration check against Preissel et al. (2015)

The review reports two nitrogen figures that answer two different questions. Using the
wrong one would overstate the credit by a factor of two:

- **60 kg N/ha** — average reduction compatible with *"maintenance of acceptable
  yields"*.
- **23–31 kg N/ha** — reduction compatible with *"maximising yield potential"*.

This engine assumes a farmer who wants the following wheat's full yield, so **23–31 is
the applicable band** and the 60 kg/ha figure must not be cited here.

Following-crop yield: the review measures **0.5–1.6 t/ha** higher cereal yield after a
legume than after a cereal pre-crop.

Measured against the engine as built (`finance.precrop_literature_sensitivity`,
exposed on `/api/v1/simulate-rotation`):

| Site | Engine N credit | Review band | Engine following-crop gain (cereal-equivalent) | Review band |
|---|---|---|---|---|
| Beauce (28), deep loam | 25.0 kg/ha | 23–31 | 0.488 t/ha | 0.5–1.6 |
| Côte-d'Or (21), shallow limestone | 10.7 kg/ha | 23–31 | 0.321 t/ha | 0.5–1.6 |
| Gers (32), clay loam | 11.3 kg/ha | 23–31 | 0.253 t/ha | 0.5–1.6 |

**The defensive conclusion holds**: the engine's following-crop gain is at or below the
bottom of the published range everywhere, so no positive result it produces can be
attributed to generous pre-crop crediting. A test (`test_engine_is_at_or_below_the_
review_lower_bound`) now enforces that rather than asserting it.

**But the conservatism is not uniform, and that is the sharper finding.** Because the
credit scales with the legume's realised yield (damping exponent 0.6), a lower-yielding
site receives roughly half the credit a high-yielding one does. On Beauce the engine
sits *inside* the review's nitrogen band; on Côte-d'Or and Gers it sits at a third of
it. The conservatism therefore bites hardest exactly where the pulse case is most
marginal — which is where it changes the answer.

Repricing the two pre-crop terms on the draws already taken, holding everything else
fixed:

| Case | As built | Review lower | Review midpoint | Review upper |
|---|---|---|---|---|
| Beauce, field pea | −177 | −177 | **−58** | +62 |
| Côte-d'Or, field pea | −44 | **+8** | **+127** | +246 |
| Côte-d'Or, winter pea | +12 | +59 | +178 | +297 |
| Beauce, fava bean | −449 | −446 | −326 | −207 |
| Gers, chickpea | −35 | **+31** | **+150** | +270 |

Two of five cases flip from negative to positive at the review midpoint, and two flip
at its **lower** bound. Beauce fava bean stays robustly negative under every
assumption.

**What to do with this.** Not retune the parameters — that would be fitting to a
preferred answer, and the conservative setting is what makes the positive results
defensible. The correct response is presentational: marginal negative results are the
pessimistic end of a real literature spread and should be shown as a range. The
sensitivity block now ships in the API response so the range is always available, and
`verdict_changes_at_review_midpoint` flags the cases where it matters.

One caveat on the scaling itself: the review reports that following-crop yield benefits
are highest **under low nitrogen fertilisation of the subsequent crop**. It does *not*
report a relationship between the legume's own yield and the credit it leaves. The
engine's yield-scaling is therefore a modelling assumption, not a reviewed finding, and
it is the dominant driver of the conservatism above.

---

## 4. Method note: why the risk layer uses SERF

`services/risk.py` implements Hardaker et al. (2004) rather than picking a single risk
aversion coefficient, because no observable tells us a given farmer's risk attitude.
SERF reports certainty equivalents across a *range* of attitudes and lets the ranking
speak for itself.

Building it produced a result that contradicted the design intuition, and it is
documented in `risk.risk_sharing_diagnostic` with a test:

> Because year 1 is identical in both arms and year 3 differs only by the nitrogen
> credit and break-crop response, the two rotations are ~0.86 correlated and their
> variances differ by under 10% of the variance of their difference. A CARA certainty
> equivalent penalises each arm by roughly (a/2)·Var(arm), so those penalties cancel and
> the whole-rotation ranking is driven almost entirely by the means. Across the entire
> Anderson–Dillon range the arm-level advantage moves by under €8/ha.

So a risk-aversion control over whole-rotation certainty equivalents would have looked
responsive and done nothing. The quantity risk preference genuinely acts on is the
**incremental** risk of switching — the distribution of the difference — which is also
the economically correct object, since the farmer's other hectares are unchanged either
way. The switching risk premium runs €0 → €46/ha across the range on the Côte-d'Or
case, and the contract inversion is built on that formulation so its terms actually
respond to risk attitude (€315/t at risk-neutral, €352/t at extremely risk averse).

---

## 5. What the literature does **not** settle

- **No per-lot grading data exists anywhere in it.** `P_human` remains a structured
  hazard model. The literature gives mechanisms, not labels.
- **Price levels.** No reviewed source gives a current French food-grade vs feed-grade
  price grid; see `DATA_SOURCES.md` for the Eurostat attempt and why it failed.
- **The yield–price correlation** (`prices.py`, −0.40 cereals / −0.18 pulses) is still
  an imposed assumption. Nothing found here estimates it for French pulses.
- **Weed pressure and herbicide withdrawal**, which the French sector press names as
  existential for legumes, is absent from the engine and from these references' economic
  models alike.

---

## Haulage, sorting infrastructure and facility location

**Bulk road haulage, €0.45/t/km (range €0.32-0.58).** French domestic bulk agricultural
haulage on 25-30 t semi-trailers, 2024-2025. The low end is backhaul-loaded contract
work, the high end short-distance spot. Applied only to distance beyond a 25 km local
collection radius, because the first 25 km is already inside the RICA operating cost both
rotations carry.

**Road detour factor, 1.32.** Great-circle to road-distance ratio for rural
origin-destination pairs on the French secondary network. Applied uniformly, so it cannot
flatter one candidate site over another — but it IS an approximation, and it understates
haulage in hilly terrain. A production deployment should substitute a routed distance
matrix; the code isolates this in one function so that substitution is local.

**80 km sorting access threshold.** Retained as the binary flag because it is the figure
the sector uses, but the engine's economics are continuous and that is what actually
drives results. The threshold's real justification is derivable rather than assumed: with
a €78/t food premium, field pea stops paying for its own haul at ~198 km, while green
lentil at €565/t would pay far further. A single national threshold is therefore the wrong
instrument, and `logistics.max_viable_haul_km` reports the per-crop figure.

**Optical sorting line, €450k capex, 10,000 t/yr, €62k/yr opex, 12-year life, 4%
discount.** Order of magnitude of a cooperative-scale turnkey line (pre-cleaner,
calibrator, optical sorter, bagging), consistent with Planification Écologique equipment
grant scales. Levelised cost is reported per tonne against the €38/t toll fee charged on
food tonnage, so a planner can see whether a sited unit services its own capital or needs
the grant. Siting is restricted to existing silo platforms because the capex excludes
land, three-phase power, weighbridge and reception pit.

**Greedy submodular maximisation.** Nemhauser, Wolsey & Fisher (1978), "An analysis of
approximations for maximizing submodular set functions", *Mathematical Programming*
14:265-294. The uncapacitated facility location objective is monotone and submodular, so
greedy marginal gain is within (1 − 1/e) ≈ 0.632 of the optimum. Capacity breaks
submodularity and is applied as a post-hoc allocation, so the guarantee is explicitly
scoped to the uncapacitated relaxation. Realised performance against an exact HiGHS solve
over a candidate set containing greedy's own picks: **0.997**.

**Steady-state rotation ceiling.** A pulse with a 5-year disease return interval cannot
exceed one fifth of a rotation at steady state, whatever the economics say. Used as the
commune-level aggregate form of the parcel-level *Aphanomyces* block, which has no direct
analogue because no commune-level rotation history exists. It binds where it should:
in departments already near their agronomic limit.

---

## Feed substitution and the local breeder fallback

**Substitution ratios** come from `feed_substitution.json` and are unchanged: 1 t of
pulse replaces `a_soymeal` t of 48% soybean meal plus `a_cereal` t of feed wheat on a
combined crude-protein and metabolisable-energy basis, plus €16/t of avoided logistics.

**Inclusion caps by herd type**, the binding constraint on how much of a lot one holding
can take: monogastrics 15-22% of concentrate (trypsin inhibitors in soy, tannins and
vicine in fava bean), ruminants 30-35%. Purchased protein concentrate — not total ration,
most of which is home-grown forage and is not addressable — is the denominator.

**Surplus split, 55% to the farmer.** A negotiating assumption, not a measurement, and
flagged as one. Both sides of the trade are reported precisely so the assumption can be
argued with rather than hidden.

**A calibration result that contradicts the obvious story, kept because it is what the
numbers say.** The fallback contract was expected to be concentrated downside insurance.
Measured over 800 paired paths it is not: the loss tail is driven mostly by low yield,
and a low-yield year has fewer tonnes to downgrade, so poor yield and poor grading nearly
cancel in downgraded tonnage (1.49 t/ha in the worst 15% against 1.54 t/ha overall). The
uplift is a near-flat ~€46/ha. It is a revenue floor, not insurance, and the UI and the
test docstring both say so.

**And one crop where the mechanism does not work at all.** Chickpea's commodity feed
price (~€295/t) is at or above its value in a livestock ration (~€294/t), so no local
holding can outbid the feed market. The engine returns no contract rather than quoting a
floor equal to the spot price.
