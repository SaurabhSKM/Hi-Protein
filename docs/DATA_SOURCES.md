# Data sources: verified URLs and parse recipes

Every endpoint and file below was fetched successfully while building this. Where a
source turned out to be unusable, that is recorded too, so nobody re-walks the dead
end.

---

## 1. Agreste SAA — yields and areas, department × crop × year

The training labels. This is the upstream French agricultural statistic that Eurostat
reproduces.

**Bulk download** (HTTP 200, ~7.1 MB ZIP, no auth, no session):

```
https://agreste.agriculture.gouv.fr/agreste-web/download/publication/publie/SAA-SeriesLongues/SAA-SeriesLongues-2010-2025_DonneesProvisoires-DepartementalesRegionales.zip
```

Published from the dataset page at
`https://agreste.agriculture.gouv.fr/agreste-web/disaron/SAA-SeriesLongues/detail/`.

The ZIP contains two workbooks:

| File | Level |
|---|---|
| `SAA_2010-2025_provisoires_donnees_departementales.xlsx` | 100 departments |
| `SAA_2010-2025_provisoires_donnees_regionales.xlsx` | regions + national |

**Parse recipe** (implemented in `ml/sources.py:load_saa`):

- Read with `openpyxl`, sheet **`COP`** (Céréales–Oléagineux–Protéagineux). All eight
  target crops live there.
- `skiprows=5`. Rows 1–4 are title and notes, row 5 is blank, row 6 is the header.
- Every value is stored as **text**. Read with `dtype=str`, then `pd.to_numeric(...,
  errors="coerce")`.
- Layout is wide: one row per (geo × crop), 48 value columns.

| Column | Meaning |
|---|---|
| `LIB_DEP` | `"028 - Eure-et-Loir"`, department file only |
| `LIB_REG2` | `"24 - Centre-Val de Loire"`, both files |
| `LIB_SAA` | `"41 - Pois protéagineux"` — the 2-digit prefix is the stable key |
| `SURF_2010` … `SURF_2025` | area, **hectares** |
| `REND_2010` … `REND_2025` | yield, **quintal/ha** — divide by 10 for t/ha |
| `PROD_2010` … `PROD_2025` | production, **quintals** |

Units are stated in the sheet's own note: *"les superficies développées sont exprimées
en hectare, les productions récoltées en quintal et les rendements en quintal par
hectare"*.

Geo codes are not a separate column; split `LIB_DEP` on `" - "`.

**`LIB_SAA` prefixes used here:**

| Prefix | Crop | Internal key |
|---|---|---|
| 01 | Blé tendre d'hiver et épeautre | `soft_wheat` |
| 06 | Blé dur | `durum_wheat` |
| 08 | Orge d'hiver | `winter_barley` |
| 09 | Orge de printemps | `spring_barley` |
| 17 | Maïs grain | `grain_maize` |
| 29 | Colza grain d'hiver | `rapeseed` |
| 32 | Tournesol | `sunflower` |
| 33 | Soja | `soybean` |
| 38 | Féveroles et fèves | `fava_bean` |
| 40 | Lentilles | `green_lentil` |
| 41 | Pois protéagineux | `field_pea` |
| 43 | Pois chiches | `chickpea` |

The sheet also carries `Total …` aggregate rows. Filter them out or you double count.

**Caveats.** `area_ha == 0` is exactly equivalent to "not grown, yield blank" — across
the whole grid there is no case of positive area with a missing yield, so `area_ha > 0`
is a sufficient validity filter. 2025 is flagged provisional in the workbook header and
is dropped. Minor-pulse departmental yields are rounded coarsely (a department can read
2.2 t/ha for three years running), which caps achievable model accuracy for lentil and
chickpea.

**Cross-check.** Agreste national soft wheat area 2023 is 4,761,948 ha; Eurostat
`apro_cpnh1` reports 4,761.95 kha for the same year. Exact match.

**A second, derived use of this same series: rotation history for the ML model.**
`ml/sources.py:load_legume_pressure()` re-reads the SAA area columns (not the
yield columns) to compute, per department-year, the share of mapped arable area
under a grain legume (field pea, fava bean, green lentil, chickpea, soybean). Two
lagged versions of that share — year-1, and the mean of years 2 through 4 — are
merged onto the weather panel and become trained features `legume_share_lag1` and
`legume_share_lag2to4_mean`. This is the closest honest substitute for IGN RPG's
parcel-level crop history that department-year training labels can support; see
`docs/CHANGES_FROM_BLUEPRINT.md` item 20 for the full argument and the empirical
check that the learned effect runs the same direction as the deterministic
Aphanomyces rule it complements.

One gap this introduced and had to close: the weather bootstrap samples 30 years
back, but Agreste's series only starts in 2010, so pre-2010 weather rows have no
real legume-share match. `ml/build_dataset.py` fills those with the department's
own 2010-2024 mean rather than leaving NaN, which a model trained only on
2010-2024 rows would not have learned to handle.

---

## 2. Météo-France — monthly climate, per department

The model features.

```
https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/MENS/MENSQ_{DD}_previous-1950-2024.csv.gz
https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/MENS/MENSQ_{DD}_latest-2025-2026.csv.gz
```

`{DD}` is the two-digit department code. Catalogued on `data.gouv.fr` as dataset
`6569b3d7d193b4daf2b43edc`, *Données climatologiques de base - mensuelles*, 318
resources. Gzipped CSV, **semicolon-delimited**, one row per station-month, 122 columns.

**Columns used:**

| Column | Meaning |
|---|---|
| `NUM_POSTE`, `NOM_USUEL`, `LAT`, `LON`, `ALTI` | station identity |
| `AAAAMM` | year and month |
| `RR` | monthly rainfall, mm |
| `ETP` | monthly reference evapotranspiration, mm |
| `TX`, `TN`, `TM` | mean daily max, min, mean temperature |
| `NBJTX30`, `NBJTX25` | days with Tmax at or above 30 °C / 25 °C |
| `NBJGELEE` | frost days |
| `NBJTXI20` | days with Tmax **below** 20 °C |

Watch the suffix convention: **`I` means *inférieur* and `S` means *supérieur***. Days
with Tmax at or above 20 °C — what drives bruchid egg-laying — is
`days_in_month − NBJTXI20`, not `NBJTXI20`.

Departments are listed in two files. `ml/train_depts.txt` holds the 40 the model is
trained on, chosen by pulse area. `ml/weather_only_depts.txt` holds departments wanted
for climate but deliberately excluded from training, because their pulse area is too
small for the reported yield to mean anything. Carrying them still pays off twice: the
Monte Carlo engine samples a real local climate for a parcel there instead of falling
back to the national pool, and a consumer joining a finer spatial grid to this panel
gets full coverage of the demo region. Their yield baseline falls back to the soil
archetype and the API says so in its provenance. A test asserts they never leak into
the training panel.

Stations above 700 m are excluded. Arable pulses are not grown there and those stations
drag a department's heat-stress signal down. Station-months are aggregated to
station-years, then to a department-year **median** rather than a mean, so one station
with a thunderstorm cell or a long data gap cannot move a whole department's feature.

Winter recharge spans the calendar boundary, so October–December is shifted forward to
the agricultural year that benefits from it.

---

## 3. IGN API Carto — RPG v2 parcel geometry and crop history

Live, per map click, cached to disk.

```
GET https://apicarto.ign.fr/api/rpg/v2?geom={GeoJSON}&annee=YYYY
```

`geom` is a URL-encoded GeoJSON geometry; a `Point` works. Returns a GeoJSON
`FeatureCollection`.

**Feature properties** (verified against live responses):
`id_parcel`, `surf_parc`, `code_cultu`, `code_group`, `culture_d1`, `culture_d2`.

Campaign years **2015–2023** respond. 2010 returns HTTP 400. Walking the years at one
point reconstructs the declared crop history, which is what the return-interval check
needs.

**Gotchas.** The documented path is `/api/rpg/v2` with no trailing resource —
`/api/rpg/v2/parcelle` and `/api/rpg/v2/search` both 404. The OpenAPI JSON at
`/api/doc/json/rpg` also 404s; only the HTML doc at `/api/doc/rpg` resolves. RPG
records the **declared main crop** per campaign and carries no soil or yield data, so
the department and soil archetype are inferred from the parcel location.

`code_cultu` → internal crop mapping is in `backend/app/services/rpg_codes.py`, with
`code_group` as a coarse fallback and a set of non-arable groups that map to nothing.

### The code vocabulary changes between campaigns

The authoritative per-campaign code tables are a separate WFS service:

```
GET https://data.geopf.fr/wfs/ows
    ?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature
    &TYPENAMES=RPG.2024:codes_cultures&OUTPUTFORMAT=application/json&COUNT=1000
```

Properties are `code` and `libelle`, plus `code_groupe` and `libelle_groupe` **up to
2023 only**.

The obvious inference from that is wrong, so it is worth stating: the 2024 **code
table** dropped `code_groupe`, but the 2024 **parcel layer** did not.
`RPG.2024:parcelles_graphiques` still carries `code_group` on every feature, verified
non-null on 100 of 100 sampled Beauce parcels, alongside a new `cat_cult_p` field
(`TA` for *terre arable*). A group-level fallback therefore still works on 2024 data
if the group is read off the parcel rather than looked up by crop code; what is lost
is only the human-readable `libelle_groupe`. The real constraint for this project is
simply that API Carto RPG v2 serves campaigns 2015 to 2023.

Note the 2024 WFS parcel query needs its BBOX in **lat,lon** order with an explicit
CRS URN. The lon,lat order silently returns zero features rather than erroring.

| Campaign | Codes | `code_groupe` |
|---|---|---|
| 2023 | 372 | yes |
| 2024 | 147 | **no** |

The 2024 campaign consolidated the vocabulary. Eight codes used here disappear:
`BVF`, `CHA`, `FFO`, `J5M`, `J6S`, `LEF`, `MIE`, `PTF`. Three map to a crop
(`FFO` → fava bean, `LEF` → lentil, `MIE` → maize), so on 2024 data they would stop
matching silently. `RETIRED_IN_2024` resolves them through their successor where one
exists (`CHA` → `CHV`, `J5M`/`J6S` → `JAC`, `PTF` → `PTC`); the forage variants and
maize silage were folded into their parents and have no separate successor.

Call `unmapped_codes()` with the distinct `code_cultu` values of any new extract
before trusting a campaign year. Against the 37 distinct values in 1,000 live Beauce
2023 parcels, coverage is complete: 517 rotation crops, 336 fallow or idle, 74
BCAE 8 non-productive features, 73 other. Those 37 codes are pinned in
`tests/test_rpg_codes.py` so the check does not need the network.

**One third of that sample is idle.** 336 of 1,000 parcels are `JAC`, `JNO`, `SNE`,
`J5M` or `J6S`. That is the cheapest land to convert to a nitrogen-fixing legume,
because no crop margin is displaced, and it is why `fallow` is a first-class baseline
land use in the engine. Those codes map to `fallow` rather than to nothing, so an idle
campaign survives into the inferred rotation; dropping it lost exactly the information
that drives the result. Group `11`, *Gel (surfaces gelées sans production)*, maps to
`fallow` for the same reason.

A worked case from live data: a 5.8 ha parcel in Beauce declared `J6S` every campaign
from 2015 to 2020. Six years with no *Aphanomyces* host, fallow scored as a good
preceding crop, and field pea returning €986/ha against the idle baseline, with the
BCAE 8 compliance warning attached.

### Three codes worth getting right

**`SRS`, Sarrasin (buckwheat)** is a pseudo-cereal in Polygonaceae and fixes no
nitrogen. RPG files it under group 4, *Autres céréales*, not under *protéagineux*. It
maps to no crop here deliberately and should not appear in any protein-crop list.

**`MLT` is Millet**, group 4 *Autres céréales*, in the 2023 and 2024 tables alike.
This project had it mislabelled as a legume-cereal mix, which would have shown a user
millet as a nitrogen-fixing precedent. The actual mixes are `MLC`, `MLF` and `MLG`
(forage legume mixes) and `MPC` (protein-cereal mix).

**`PAG` declares a grain legume without naming the genus** (*Autre légumineuse à
graines* in 2023, *Autre protéagineux d'un autre genre* in 2024), RPG group 8
*Protéagineux*. No yield or price can be predicted for an unnamed crop, so it maps to
an `other_legume` entry whose family keeps it out of the candidate list while letting
it enter the rotation history. It is treated as an *Aphanomyces* host, which is the
cautious reading: a disease with no chemical control and decade-long inoculum
persistence should not be cleared on the strength of a missing label. Before this was
mapped, a parcel that declared `PAG` two campaigns ago looked clean and the engine
would have cleared both pea and lentil.

---

## 4. ADEME Agribalyse — carbon and LCA

Live, cached. Use the **per-stage** dataset, not the synthesis table.

```
GET https://data.ademe.fr/data-fair/api/v1/datasets/agribalyse-31-detail-par-etape/lines
    ?qs=Nom_du_Produit_en_Français:"Lentille, sèche"&size=1
```

Query with `qs` (Lucene phrase) **alone**. Passing a free-text `q` alongside it lets
relevance ranking return a different product, which silently gave pea and chickpea the
same footprint.

**Fields used:** `Changement_climatique_-_Agriculture` and
`Changement_climatique_-_émissions_liées_au_changement_d'affectation_des_sols_-_Agriculture`.

**Why per-stage matters.** For *Lentille, sèche*:

| Stage | kg CO₂e/kg |
|---|---|
| Agriculture | **0.141** |
| Transport | 0.244 |
| Packaging | 0.129 |
| Retail and distribution | 0.067 |
| Synthesis total | 0.581 |

A farm-gate rotation comparison that uses 0.581 overstates the pulse footprint by a
factor of four.

**Verified agriculture-stage values:**

| Product | Agriculture | of which LUC |
|---|---|---|
| Lentille, sèche | 0.141 | 0.017 |
| Pois cassé, sec | 0.400 | 0.173 |
| Pois chiche, sec | 0.400 | 0.173 |
| Fève, sèche | 0.508 | 0.004 |
| Tournesol, graine | 1.800 | 0.592 |

**Two caveats.** Agribalyse assigns pea and chickpea the same pulse proxy, including a
land-use-change component that is implausible for a European grain legume and suggests
the proxy blends imported product. And Agribalyse is a **consumer-food** database, so
soybean meal, wheat grain and rapeseed have no entry at all; those fall back to the
local reference table in `refdata/carbon.json`, flagged as such in the response.

**Propagated across the Monte Carlo sample, not read once at a point yield.**
`backend/app/services/carbon.py:impact_distribution()` re-runs this same Scope 3
substitution over every yield draw the financial engine already produced for the
request, returning `co2e_saved_tons_q15/median/q85` instead of one number. A bad
year that roughly halves the pulse harvest also roughly halves the soy meal it
displaces, and the carbon claim now says so. It also feeds
`carbon_abatement_cost_eur_per_tonne`, the whole-parcel 3-year financial delta
(which already carries the PAC coupled aid and RICA-consistent costs from layer 5,
below) divided by the median tonnes avoided — the EUR-per-tonne bridge between the
Costs/Prices/Subsidies layer and this one.

---

## 5. Reference tables (not fetched)

In `backend/app/refdata/`, each with a `_meta` block stating its basis and its
caveats.

| File | Contents |
|---|---|
| `crops.json` | 16 crops: reference yields, price and cost distributions, protein, return intervals, soil tolerances |
| `departments.json` | pilot departments: region, centroid, arable and pulse area, dominant soil, national target |
| `pac_2023_2027.json` | coupled protein aid, eco-scheme, BCAE 7/8, nitrates directive |
| `rotation_rules.json` | disease groups, preceding-crop suitability, sowing windows, bruchid, quality specs |
| `nitrogen.json` | STICS/AzoFert-style carry-over bounds, leaching, following-crop response |
| `quality.json` | the `P_human` hazard model parameters |
| `soils.json` | six soil archetypes with plant-available water capacity, pH, hydromorphy |
| `dept_soils.json` | one dominant arable archetype per department |
| `irrigation.json` | irrigated share and yield uplift per crop |
| `feed_substitution.json` | on-farm replacement ratios against soybean meal and feed wheat |
| `carbon.json` | fallback footprints, protein contents, land-use-change conventions |
| `buyers.json` | the offtake demand book — **illustrative demo data** |

Buyer company names are real French pulse processors and cooperatives. Every price,
volume, premium and tolerance attached to them is invented for this prototype and
labelled `is_demo_data: true`.

---

## Dead ends, confirmed

Do not re-test these.

- **Eurostat `apro_cpshr`** (crop production by NUTS 2 region). Returns HTTP 200 with
  **zero values** for every French region and every crop, via both the JSON-stat API
  and the SDMX TSV endpoint. France does not report regional crop data to Eurostat.
- **Eurostat national `apro_cpnh1`** does work and is a useful sanity check, but
  Agreste is strictly better: finer geography, more crops, and it is the upstream
  source. SDMX dimension order is `freq.crops.strucpro.geo`; valid `strucpro` codes are
  `AR_THS_HA`, `YLD_T_HA`, `HPRD_THS_T`, `HUMD_PC` — not the
  `YLD_HUMD_EU_T_HA` the regional dataset advertises.
- **FAOSTAT** `fenixservices.fao.org/faostat/api/v1/...` returned HTTP 521 throughout.
- **Agreste Disar as an API.** It is a stateful JSF application. `/agreste-web/api/*`
  and `/disaron/<dataset>/detail/export` both 404. The only machine-readable path is
  the static bulk link embedded in each dataset page.
- **`data.gouv.fr` search for SAA data.** The dataset
  `agreste-statistique-agricole-annuelle-saa` has exactly one resource, and it is a
  link to an Agreste methodology web page. Searches for *pois protéagineux*,
  *grandes cultures rendement* and *SAA surfaces rendements* all return zero results.
- **Older Agreste `SAANR_*` FDS archives** exist and are department level, but stop at
  2020 and carry only aggregate product groups (`Céréales`, `Oléagineux`,
  `Protéagineux`) with a single surface indicator. Superseded entirely by
  `SAA-SeriesLongues`.
