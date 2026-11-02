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

### Price validation, attempted and failed (added this session)

- **Eurostat `apri_ap_crpouta`** (Selling prices of crop products, absolute prices,
  annual) *does* respond for `geo=FR` and *does* carry dried peas (`02210000`), lentils
  (`02991000`), soya (`02130000`) and the cereals and oilseeds of the baseline arm. It
  looked like the way to put observed prices behind `crops.json`. It is **not usable**,
  for four reasons, and `scripts/validate_prices.py` computes the verdict rather than
  asserting it (artifact: `data/processed/price_validation.json`):
  1. **Unit errors.** The French pulse rows read 2.4 and 14.0 EUR/100 kg for 2010–2011
     and then 33–78 from 2012, a 4.6× step in one year. Detected as a level break
     against the series' own median, not by an absolute floor, because real prices
     differ five-fold across these crops.
  2. **Implausible oilseed levels.** Over 2012–2016 the series puts rapeseed at **1.06×**
     and soybean at **1.28×** soft wheat. No European oilseed market sustains that —
     both crush for oil and meal and trade persistently well above feed wheat. The
     defect is in the series, so any "overstatement" it reports for other crops cannot
     be trusted either. **A jury that checked the rapeseed row would discredit the whole
     comparison**, which is the real reason this is recorded.
  3. **Two candidate crops absent.** France reports no price at all for **fava bean** or
     **chickpea**.
  4. **Series ends 2016**, so the post-2021 price regime is entirely unobserved.
- **Eurostat Comext detailed trade (`DS-045409`)**, which would have given monthly
  tonnage and value by HS code (0713.10 peas, .20 chickpeas, .40 lentils, .50 broad and
  horse beans) and hence unit values plus a food-vs-feed destination read: **404** on
  the statistics dissemination path and **413 Request Entity Too Large** on the comext
  path. `apro_cpnh1` and `ext_st_eu27_2020sitc` both return 200 from the same base, so
  the base URL is right and the dataset is simply not served there.
- **FranceAgriMer utilisation balances.** The `data.gouv.fr` dataset *Bilans mensuels
  oléo-protéagineux* (`5d00bf84634f41787a09c75b`) has exactly one resource and it is an
  **HTML link into VisioNet** (`visionet.franceagrimer.fr/.../Statistiques.aspx`), a
  stateful ASP.NET application — the same class of dead end as Agreste Disar. The annual
  food/feed/export split that would weakly validate `P_human` at national scale is
  therefore **not machine-readable**; it has to be read off a publication and typed in,
  with the page reference recorded. Fourteen numbers, so that is still worth doing.
- **Agreste RICA long series.** `data.gouv.fr` dataset `53699f0fa3a729239d206035`
  advertises `.../RICA-SeriesLongues/RICA_Séries-longues.xlsx`. That URL **404s** (both
  percent-encoded and literal), and the `disaron/RICA-SeriesLongues/detail/` page
  exposes no download link to rediscover it from. The data.gouv record is stale. This is
  why `services/risk.py` uses a negative-exponential utility, whose certainty equivalent
  is invariant to wealth: it is the one utility family that does not need the farm income
  figure this dead link was going to supply.

### Sentinel-2 in `Hi-protein-adits`: checked for the downscaler, cannot support it

Checked directly against `adits/grid/beauce_1000m.parquet` (11,132 cells × 88 columns)
and its `_meta.json`. The NDVI-downscaling idea — regress department yield anomaly on
department-aggregated Sentinel features, then use within-department anomalies to replace
the flat 1.292 parcel variance inflation factor — is **not buildable on this grid**:

1. **One year.** `rpg_year: 2024` and all three Sentinel windows are 2024 dates. The
   yield labels are department-year over 2010–2024, so a single year yields one
   observation per department. Nothing to fit, nothing to hold out.
2. **Six departments** (28, 45, 91, 41, 77, 78), all in one region — so even that single
   year gives at most six points.
3. **The peak-season window is gone.** `s2_ndvi_peak` is null on **93.3%** of cells
   (only 751 of 11,132 have it), `s2_ndvi_greenup` on 95.8%, `s2_ndvi_senescence` on
   93.3%. The 15 Jun–31 Jul window is the most informative one for yield.
4. **The surviving columns are degenerate, not complete.** `s2_ndvi_max` and
   `s2_ndvi_amplitude` show 0% nulls, which looks reassuring and is not: where the peak
   window is missing, `ndvi_max` equals `ndvi_late` on **66.9%** of cells and
   `ndvi_amplitude` is exactly **0 on 64.5%**. They are complete because they silently
   fall back to the single available late window.

A multi-year, multi-region Sentinel harvest with real cloud-gap handling would be needed,
which is hours of ingest and a retrain. **Nothing was committed to `Hi-protein-adits`.**

---

## 6. IGN ADMINEXPRESS — commune geometry and cadastral area

The spatial backbone of the regional view and of the siting optimiser's demand surface.

**Endpoint, verified live.**

```
GET https://data.geopf.fr/wfs/ows
  ?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature
  &TYPENAMES=ADMINEXPRESS-COG.LATEST:commune
  &OUTPUTFORMAT=application/json
  &SRSNAME=CRS:84
  &COUNT=5000
  &CQL_FILTER=code_insee_du_departement='28'
```

**Axis order matters and cost a debugging cycle.** With `SRSNAME=EPSG:4326` and a BBOX
in lon/lat the service returns an empty FeatureCollection with HTTP 200 — no error, just
nothing. Use `CRS:84` (lon, lat) or `urn:ogc:def:crs:EPSG::4326` (lat, lon) and be
explicit about which. A silent empty result is the worst failure mode available, so the
build script asserts a non-zero feature count per department.

**Fields used.**

| Field | Use |
|---|---|
| `code_insee` | Commune key |
| `nom_officiel` | Display name |
| `code_insee_du_departement` | Join to the department table |
| `code_insee_de_la_region` | Carried through, unused so far |
| `superficie_cadastrale` | Cadastral area in HECTARES. Not arable area |
| `population` | INSEE census. Used to pick candidate silo sites |
| `geometry` | MultiPolygon; centroid computed locally with shapely |

**Volume.** One department is ~1.5 s and ~5 MB with full geometry. All 42 is about a
minute. Only the centroid, area and codes are kept, so the artefact is 2.8 MB for 18,157
communes rather than ~200 MB.

**Centroid note.** Shapely's planar centroid on geographic coordinates is a few hundred
metres out at French latitudes, which is immaterial against an 80 km haulage radius.
Invalid geometries fall back to `representative_point()`.

**Also available and used once:** `ADMINEXPRESS-COG.LATEST:departement` for official
department names and region codes. `PROPERTYNAME` suppresses geometry, which makes it a
very cheap lookup.

**Not used:** `RPG.<year>:parcelles_graphiques` is served by the same WFS and does work
(`CRS:84` BBOX, verified), so a real per-parcel layer is reachable. It is not used for
the regional surface because 9.5 million polygons would take a day to aggregate and
would be identical to the commune surface at the resolution a siting decision is made
at. `ign_rpg.py` still point-queries API Carto for the single parcel a farmer clicks,
which is where parcel-level precision actually changes an answer.

---

## 6b. The land-change view: what moved, and the two traps in measuring it

Three artifacts back the "How the land changed" tab. Each is independently rebuildable
and each carries its own `_meta`.

| Artefact | Script | Grain |
|---|---|---|
| `data/processed/adoption_panel.csv` | `scripts/build_adoption_panel.py` | Agreste SAA, 93 departments × 12 crops × 2010-2024 |
| `data/processed/dept_geometry.json` | same | IGN `ADMINEXPRESS-COG.LATEST:departement`, simplified to 0.004° |
| `ml/artifacts/adoption_report.json` | `ml/train_adoption.py` | attribution, 42 departments |
| `data/processed/rpg_change_beauce.json` | `scripts/build_rpg_change.py` | RPG parcels, Beauce bbox, 10 campaigns |

### Why the national series is Agreste and not RPG

RPG is the only parcel-level record, and it is the wrong tool for a national time
series: roughly 9.5 million polygons per campaign and ten published campaigns. Agreste
answers the same question at department grain for 93 departments. RPG's job here is the
zoom-in — one region, every campaign, real field boundaries.

### Trap 1: the zero rows

`sources.load_saa` filters to rows with a published yield, which is right for the yield
model and wrong for an adoption question: it removes exactly the 3,644 `area_ha == 0`
rows and nothing else (verified — no row has positive area and a blank yield). National
totals are therefore unaffected, but a department's 0 → 400 ha arrival becomes
invisible, because the series simply starts late. `load_saa(require_yield=False)` keeps
them, and 112 department-crop pairs in the panel go from a true zero to a real area.

### Trap 2: the RPG 2023 vocabulary change

**This one changes the answer.** Taken as published, the Beauce's grain-legume share
rises from 2.00% in 2015 to 3.39% in 2024. Most of that is not land-use change.

Three pulse codes — `PHF` (pois et haricot frais, alimentation humaine), `PHS` (pois et
haricot secs, alimentation humaine) and `FVP` (féverole de printemps) — record **zero
hectares in this region in every campaign from 2015 to 2022** and then appear at 3,572,
2,734 and 577 ha in 2023. Adoption does not behave like that. The code tables settle
it: all three are **absent from `RPG.2022:codes_cultures` (352 codes) and present in
`RPG.2023:codes_cultures` (372 codes)** — 20 codes were added that campaign, which is
the 2023-2027 PAC's first year. They could not have been declared earlier whatever was
growing.

Like for like:

| Comparison | Pulse share |
|---|---|
| 2015 → 2024, as published | 2.00% → 3.39% |
| 2015 → 2022, stable vocabulary | 2.00% → 1.99% |
| 2015 → 2024, new codes removed | 2.00% → 2.39% |

Lentil is the clean signal: `LEC` is in the 2022, 2023 and 2024 tables alike and
declared every campaign, and it goes 471 → 1,724 ha with no adjustment needed.

Fetching all ten campaigns rather than two endpoints is what made this visible. On two
campaigns a relabelling and a tripling are indistinguishable.

### Why the pulse total does not use this project's own crop map

`services/rpg_codes.py` is built for the yield model: it sends `MPC` and `PAG` to
`other_legume` and has no lupin key. The land-change view instead takes RPG's own
groups — **8 (Protéagineux)** and **15 (Légumineuses à grains)**, plus `SOJ`, which RPG
files under group 7 (Autres oléagineux). Group membership was read from
`RPG.2023:codes_cultures` and verified to hold in both the 2015 and 2024 extracts.
Using the official groups recovered 136 ha in 2015 and 649 ha in 2024.

Note also that `code_group` is what rescues the older codes: `LUD`, `LU5` (luzerne) and
`OEI` (œillette) carry no entry in `CODE_CULTU_LABELS` but classify correctly through
the group fallback. `unmapped_codes()` reports codes with no *label*, which is not the
same as codes that failed to classify — worth knowing before reading its output as a
loss figure.

### Agreste's quality flag

The SAA workbook carries a per-series `STATUT_QUALITE` of 1, 2, 3 or NC, and defines
the codes only by reference to a methodology page that currently returns an error. The
panel therefore **reports the mix and does not interpret the codes**: 86.72% of pulse
area is status 1, 12.02% status 2, 1.25% status 3, and NC rows carry 12 ha in total
across all years. Every row has a value for all 15 years regardless of status, so the
flag changes no figure.

Workbook header, verbatim: *"Données arrêtées au 30/03/2026. Données 2025
provisoires."* So 2010-2024 are definitive and 2025 is excluded. The header also records
that the series were made consistent with the 2020 recensement agricole and back-cast
over 2010-2019.

### What the attribution can and cannot say

Target is the **change** in a department's area share, not the level — the level is
0.969 autocorrelated, so a model fitted on it looks excellent and has only learned
"Beauce grows peas". Weather features are from season **t-1**; using season t would be
leakage, since a farmer sowing in year t cannot know that year's flowering rainfall.

Results: a national year effect common to every department explains 13.7-37.3% of the
variance depending on crop. Weather and soil, **cross-fitted with folds grouped by
year**, add nothing — the increment is negative for four of five crops. Fitted
in-sample the same stage reports 52.2% to 74.2%, which is what twelve weather columns and a
boosted-tree learner will do to 588 rows; both numbers are in the artifact and the gap
is the overfit. Held out on 2020-2024, the model does not beat assuming no change.

So the shift is not weather-driven. The drivers that would explain it are the series
this repo has no usable history for — pulse prices (Eurostat's French series ends 2016
with unit errors and omits chickpea and fava bean; see `price_validation.json`), PAC
coupled aid per campaign (`pac_2023_2027.json` holds one current unit amount), and
contract or sorting capacity. The attribution runs on the 42 departments with
Meteo-France weather; the descriptive view uses all 93.

**Available and not used:** RPG campaigns 2016-2023 nationally. `GetCapabilities`
advertises `RPG.<year>:parcelles_graphiques` for 2015-2024 (2010-2014 appear only as an
empty `RPG.<year>:rpg_` stub), so a national parcel panel is reachable, at roughly a day
of downloading. Code tables exist only for 2022-2024, and only up to 2023 carry
`code_groupe`.

---

## 7. Generated reference data, and what is real inside it

Five files under `backend/app/refdata/` and `data/processed/` are produced by scripts
rather than hand-written. Each is a mix of measured and assumed, and the mix is stated
here and in the file's own `_meta`.

| Artefact | Script | Real | Assumed |
|---|---|---|---|
| `departments.json` | `build_departments.py` | Areas (Agreste SAA 2022-24 subtotals), centroids (IGN), soils (`dept_soils.json`) | Irrigation shares; dept→region grouping |
| `dept_rotations.json` | `build_dept_rotations.py` | Crop area shares per department (Agreste SAA 2022-24, sheet COP) | Which slot each crop occupies; that a cereal precedes the pulse |
| `data/processed/communes.json` | `build_communes.py` | Everything — IGN geometry, cadastral area, INSEE codes, population | Nothing |
| `data/processed/region_profiles.json` | `build_region_profiles.py` | Output of the same Monte Carlo the farmer endpoint runs, per department × climate horizon | One soil archetype per department |
| `breeders.json` | `build_breeders.py` | Locations (IGN commune centroids); holding COUNT per department (scaled by measured non-COP cadastral share) | Individual identities, names, herd types and herd sizes |

### Why `dept_rotations.json` exists

The year-2 crop of the baseline rotation is the one a candidate pulse displaces, and its
forgone margin is the largest single term in the three-year difference the engine
reports — larger than the nitrogen credit, the break-crop response and the PAC coupled
aid together. It was a hard-coded `soft_wheat / spring_barley / rapeseed` in three code
paths, none of them reachable from the regional, food or climate tabs. Checked against
the Agreste area series this project already ships, that list matched only 2 of each
department's top 3 crops in 32 of 42 departments; spring barley is in the top three of
only six. Re-running the engine with just the comparator changed moved the median
difference by −237 to +511 EUR/ha and flipped the recommendation on three of eight cases.

**Year 2 is the largest priceable alternative, not the largest alternative.** Only soft
wheat, spring barley and rapeseed have Agreste departmental yield histories here; winter
barley, durum wheat, grain maize and sunflower fall through `ml.baseline_yield` to a
hand-written national constant with *no departmental signal* — every deep-loam
department gets the same 7.62 t/ha for winter barley. Using the real second crop would
therefore trade a department-calibrated baseline for a flat number, and the resulting
spread between departments would be an artefact of the fallback rather than agronomy.
That is precisely where the +511 on Marne and the −237 on Saône-et-Loire came from: the
constant sits above the measured Agreste yield in weak departments and below it in
strong ones.

So in **23 of 42 departments** the comparator is not the most widely grown alternative,
and each of those records carries `dominant_alternative_not_priceable` naming the crop
and its area share. In eight departments the derived rotation covers under half the
non-legume arable area (Aude 21%, Landes 12%) and the caveat says so. Ingesting the four
missing Agreste yield series is the real fix and is a data task, not a code change.

**Rebuild:** `make rotations`, then `make profiles` — the rotation changes the margins
the profiles cache.

**The one allocation assumption worth repeating**, because it underpins the most
persuasive screen in the product: a department's real arable hectares are divided between
its communes in proportion to cadastral area. Agreste publishes nothing at commune level
to measure that against. It is right on average, wrong commune by commune, and averages
out at the scale an 80 km siting radius operates on. Stated in the `/stranded-surface`
provenance and in the map caption, not only here.

**Rebuild:** `make regions`. After any change to the margin engine, `make profiles`
alone is enough — and is necessary, or the regional view will quietly disagree with the
farmer view.

`region_profiles.json` is the cache the regional and food views run on, and it carries
two things beyond the per-department economics. It is keyed by climate horizon under
`horizons`, so the food view's horizon selector is a lookup rather than a 71-second
simulation; and `_meta.no_viable_pulse` lists, per horizon, the departments where every
legume is agronomically blocked. That list is the difference between a recorded "no"
and a gap in the cache — without it, departments 81 and 82 were re-simulated on every
request only to re-derive that boulbène at pH 5.9 grows no pulse.
