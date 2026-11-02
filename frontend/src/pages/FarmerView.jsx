import { useCallback, useEffect, useMemo, useState } from 'react'
import AgroPanel from '../components/AgroPanel.jsx'
import BreakdownBars from '../components/BreakdownBars.jsx'
import CandidateTable from '../components/CandidateTable.jsx'
import ClimateLadder from '../components/ClimateLadder.jsx'
import ContractTable from '../components/ContractTable.jsx'
import FoodOutcomePanel from '../components/FoodOutcomePanel.jsx'
import MarginFan from '../components/MarginFan.jsx'
import ParcelMap from '../components/ParcelMap.jsx'
import Provenance from '../components/Provenance.jsx'
import RobustnessBadge from '../components/RobustnessBadge.jsx'
import RiskPreferencePanel from '../components/RiskPreferencePanel.jsx'
import SorterPanel from '../components/SorterPanel.jsx'
import StatCard from '../components/StatCard.jsx'
import { api, eur, pct } from '../lib/api.js'

// Baseline rotations here are each department's OWN rotation, derived from its Agreste
// area shares by scripts/build_dept_rotations.py and read back through
// refdata/dept_rotations.json. Every preset used to carry the same hard-coded
// soft_wheat / spring_barley / rapeseed, and the year-2 crop in that list is the one a
// pulse displaces - the largest single term in the result. Spring barley turned out to
// be in the top three crops of only six of the forty-two departments.
//
// Year 2 is rapeseed rather than the winter barley these departments actually grow more
// of, because winter barley has no Agreste yield series in this project and would price
// off a flat national constant. The engine now says so in `assumptions` rather than
// leaving the reader to assume the comparator was measured.
const PRESETS = [
  {
    key: 'beauce',
    title: 'Beauce, deep loam',
    sub: 'High cereal yields raise the bar a pulse has to clear',
    req: {
      department_code: '28', parcel_id: 'RPG-28-09412', area_ha: 45, soil_type: 'deep_loam',
      // A real RPG parcel, so the map outlines the field these numbers describe.
      lon: 1.37, lat: 48.387,
      // Wheat 44%, rapeseed 25%, spring barley 4% of Eure-et-Loir non-legume arable.
      baseline_rotation: ['soft_wheat', 'rapeseed', 'spring_barley'],
      candidate_pulse_year2: 'field_pea', has_livestock_ugb_5: false, irrigated: false,
    },
  },
  {
    key: 'bourgogne',
    title: "Cote-d'Or, shallow limestone",
    sub: 'Low cereal yields, so the pulse competes well',
    req: {
      department_code: '21', parcel_id: 'RPG-21-00421', area_ha: 40, soil_type: 'shallow_limestone',
      lon: 4.772, lat: 47.584,
      // Wheat 46%, rapeseed 13%, spring barley 12%. Winter barley is bigger at 20%
      // but has no yield series here, so the engine flags the substitution.
      baseline_rotation: ['soft_wheat', 'rapeseed', 'spring_barley'],
      candidate_pulse_year2: 'winter_pea', has_livestock_ugb_5: false, irrigated: false,
    },
  },
  {
    key: 'gers',
    title: 'Gers, irrigated clay loam',
    sub: 'Irrigated soy with a non-GMO contract',
    req: {
      department_code: '32', parcel_id: 'RPG-32-01180', area_ha: 30, soil_type: 'clay_loam',
      lon: 0.453, lat: 43.693,
      // The old durum wheat / sunflower pair was the weakest case in the app: NEITHER
      // crop has a yield series, so both years priced off hand-written constants.
      baseline_rotation: ['soft_wheat', 'rapeseed', 'spring_barley'],
      candidate_pulse_year2: 'soybean', has_livestock_ugb_5: false, irrigated: true,
    },
  },
  {
    key: 'mixed',
    title: 'Mixed crop-livestock',
    sub: 'A downgraded harvest is fed on farm, not sold at a loss',
    req: {
      department_code: '21', parcel_id: 'RPG-21-00887', area_ha: 25, soil_type: 'clay_loam',
      lon: 4.572, lat: 47.504,
      // Grain maize kept in year 3: on a livestock holding it is a real rotation
      // member, and year 3 only carries the nitrogen credit and break-crop response.
      baseline_rotation: ['soft_wheat', 'rapeseed', 'grain_maize'],
      candidate_pulse_year2: 'fava_bean', has_livestock_ugb_5: true, irrigated: false,
    },
  },
]

export default function FarmerView({ reference, lang, T }) {
  // Opens on PRESETS[0] (Beauce, field pea) deliberately: field pea has real
  // held-out metrics in ml/artifacts/model_report.json (MAE 24.2%, coverage 0.701).
  // Do NOT default to PRESETS[1] (Cote-d'Or, winter pea) — Agreste publishes a single
  // "Pois proteagineux" series, so winter pea is proxy-derived and has NO row in
  // per_crop_test_performance. It is the most interesting risk case (it is the one
  // preset where the recommendation flips with risk attitude), so keep it one click
  // away, but do not open the demo on the one pulse with no validation numbers.
  const [req, setReq] = useState(PRESETS[0].req)
  const [result, setResult] = useState(null)
  const [ranked, setRanked] = useState(null)
  const [parcel, setParcel] = useState(null)
  const [busy, setBusy] = useState(false)
  const [rankBusy, setRankBusy] = useState(false)
  const [error, setError] = useState(null)
  const [dossier, setDossier] = useState(null)
  // True while a point is being resolved to an RPG parcel. The simulation waits on it,
  // so picking a field costs ONE run against the resolved parcel instead of two - one
  // against the previous soil and area, then another when the lookup lands. Starts true
  // because the opening preset carries a point that has to be resolved on mount.
  const [resolving, setResolving] = useState(PRESETS[0].req.lon != null)
  // Bumped whenever a point should be resolved again. Without it, re-picking the
  // preset already loaded - or clicking the same spot twice - changes none of the
  // effect's dependencies, so the lookup never fires and `resolving` stays true
  // forever, leaving the panel stuck on 'Looking up the parcel ...'.
  const [resolveToken, setResolveToken] = useState(0)

  const depts = reference?.departments ?? {}
  const center = useMemo(() => {
    const d = depts[req.department_code]
    return d ? [d.centroid[1], d.centroid[0]] : [47.4, 2.5]
  }, [depts, req.department_code])

  // The pin and the outline both follow the request's own point, so a preset and a map
  // click leave the map in the same state by the same route. Previously the pin was
  // separate state that only a click ever set, which is why opening the app showed a
  // field's economics with nothing marked on the map.
  const pin = req.lon != null && req.lat != null ? [req.lon, req.lat] : null

  // Which preset the current request still represents, DERIVED from the request rather
  // than cancelled by the act of clicking. A preset is a scenario - a department, a
  // soil, a baseline rotation, a candidate pulse and the two farm flags - not a single
  // field. Picking a neighbouring parcel inside Beauce changes which field is being
  // priced but none of those five things, so the scenario is still Beauce and the card
  // stays lit; it only clears when the request genuinely leaves that scenario, by moving
  // to another department or by changing the soil, rotation, crop or farm type.
  //
  // Deliberately excluded from the comparison: lon/lat, area_ha, parcel_id and
  // crop_history. Those describe WHICH field, not which scenario, and every one of them
  // changes on an ordinary click.
  const activePreset = useMemo(
    () =>
      PRESETS.find(
        (p) =>
          p.req.department_code === req.department_code &&
          p.req.soil_type === req.soil_type &&
          p.req.candidate_pulse_year2 === req.candidate_pulse_year2 &&
          !!p.req.has_livestock_ugb_5 === !!req.has_livestock_ugb_5 &&
          !!p.req.irrigated === !!req.irrigated &&
          (p.req.baseline_rotation ?? []).join('|') ===
            (req.baseline_rotation ?? []).join('|'),
      ) ?? null,
    [req],
  )

  const run = useCallback(async (body) => {
    setBusy(true); setError(null)
    try {
      setResult(await api.simulate(body))
    } catch (e) { setError(e.message); setResult(null) } finally { setBusy(false) }
  }, [])

  // Resolve the point to a real RPG parcel whenever it moves, for presets as well as
  // clicks. This is the only place that does it, so both routes adopt the real
  // geometry, area and declared history identically.
  useEffect(() => {
    if (req.lon == null || req.lat == null) {
      setParcel(null); setResolving(false); return
    }
    let live = true
    ;(async () => {
      try {
        const p = await api.parcel(req.lon, req.lat)
        if (!live) return
        setParcel(p)
        if (p.found) {
          // Adopt the parcel's own area and id so the outlined polygon, the hectare
          // figure and the economics all describe the same field.
          setReq((r) => ({
            ...r,
            department_code: p.department_code ?? r.department_code,
            // The inferred soil is only the DEPARTMENT's dominant soil, so it carries no
            // information about a field within a department we are already in - and
            // applying it there would quietly overwrite a soil the user chose on
            // purpose. The mixed crop-livestock scenario is clay loam in Cote-d'Or,
            // where the dominant soil is shallow limestone: adopting the inference on
            // every click reset that scenario the moment the user picked a nearby field.
            // So it is adopted only when the click actually crosses into a department
            // whose archetype we have not got a soil for yet.
            soil_type:
              p.department_code && p.department_code !== r.department_code
                ? p.inferred_soil_type ?? r.soil_type
                : r.soil_type,
            area_ha: p.surface_ha ?? r.area_ha,
            parcel_id: p.history?.[0]?.id_parcel
              ? `RPG-${p.history[0].id_parcel}`
              : r.parcel_id,
            // Left undefined rather than carried over: a new field must not inherit the
            // previous one's declared rotation.
            crop_history: p.inferred_rotation?.length ? p.inferred_rotation : undefined,
          }))
        }
      } catch {
        // A failed lookup must not blank the simulation. The request still has a
        // department, a soil and a point, which is all the engine needs; the map simply
        // shows no outline.
        if (live) setParcel(null)
      } finally {
        if (live) setResolving(false)
      }
    })()
    return () => { live = false }
  }, [req.lon, req.lat, resolveToken])

  // Held back until the parcel lookup has settled, so the numbers on screen always
  // belong to the field outlined on the map.
  useEffect(() => { if (!resolving) run(req) }, [req, run, resolving])

  const set = (patch) => {
    setDossier(null)
    setReq((r) => ({ ...r, ...patch }))
  }

  const selectPreset = (p) => {
    setRanked(null); setDossier(null); setParcel(null)
    // Set in the same batch as the request, so the simulation effect already sees the
    // pending lookup and does not fire against the preset's unresolved area.
    if (p.req.lon != null) { setResolving(true); setResolveToken((t) => t + 1) }
    setReq(p.req)
  }

  const compare = async () => {
    setRankBusy(true)
    try { setRanked((await api.rank(req)).ranked) }
    catch (e) { setError(e.message) } finally { setRankBusy(false) }
  }

  // Haulage distance to the nearest optical sorter is measured from this point. A
  // parcel at the edge of a department can be stranded when the department centroid is
  // comfortably in range, so the real point matters.
  const onPick = (lon, lat) => {
    setRanked(null); setDossier(null)
    setResolving(true)
    setResolveToken((t) => t + 1)
    setReq((r) => ({ ...r, lon, lat }))
  }

  const loadDossier = async () => {
    try { setDossier(await api.dossier(req)) } catch (e) { setError(e.message) }
  }

  const risk = result?.financial_3yr_comparison_per_ha?.risk
  const fin = result?.financial_3yr_comparison_per_ha
  const ml = result?.ml_predictions_year2
  const blocked = result?.agronomic_validation?.severity === 'blocked'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-stretch gap-2">
        {PRESETS.map((p) => {
          const active = activePreset?.key === p.key
          return (
            <button
              key={p.key}
              onClick={() => selectPreset(p)}
              aria-pressed={active}
              className={`rounded-lg border px-3 py-2 text-left text-xs ${
                active
                  ? 'border-emerald-600 bg-emerald-50 ring-1 ring-emerald-600'
                  : 'border-slate-300 bg-white hover:border-emerald-500 hover:bg-emerald-50'
              }`}
            >
              <div
                className={`font-semibold ${
                  active ? 'text-emerald-900' : 'text-slate-800'
                }`}
              >
                {p.title}
              </div>
              <div className={active ? 'text-emerald-700' : 'text-slate-500'}>{p.sub}</div>
              {/* The department is the scenario's actual extent. Shown because the
                  titles name natural regions - "Beauce" spans four departments - and
                  without it there is no way to tell how far you can click before the
                  scenario changes. */}
              <div className={`mt-0.5 ${active ? 'text-emerald-600' : 'text-slate-400'}`}>
                dept {p.req.department_code}
                {depts[p.req.department_code] ? ` · ${depts[p.req.department_code].name}` : ''}
              </div>
            </button>
          )
        })}
      </div>

      {/* Which FIELD is being priced, stated separately from which scenario. These are
          two different things: clicking a neighbouring parcel changes the field and
          leaves the scenario alone, so one chip cannot carry both. */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {activePreset ? (
          <span className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-emerald-800">
            Scenario: <strong>{activePreset.title}</strong> &middot; anywhere in dept{' '}
            {req.department_code}
          </span>
        ) : (
          <span className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-amber-800">
            Custom scenario &middot; dept {req.department_code} &middot;{' '}
            {reference?.soils?.[req.soil_type]?.label_fr ?? req.soil_type} &middot;{' '}
            {reference?.crops?.[req.candidate_pulse_year2]?.label_fr ??
              req.candidate_pulse_year2}
          </span>
        )}
        {resolving ? (
          <span className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-500">
            Field: looking up ...
          </span>
        ) : parcel?.found ? (
          <span className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-600">
            Field: RPG {parcel.history?.[0]?.id_parcel} &middot; {parcel.surface_ha} ha
          </span>
        ) : pin ? (
          <span className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-500">
            Field: no RPG parcel at the clicked point
          </span>
        ) : (
          <span className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-500">
            Field: none picked &mdash; priced from the department centroid
          </span>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <div className="space-y-3">
          <div className="rounded-lg border border-slate-300 bg-white p-3">
            <h3 className="mb-2 text-sm font-semibold text-slate-800">{T.parcel}</h3>
            <p className="mb-2 text-xs text-slate-500">{T.clickMap}</p>
            <ParcelMap
              center={center} geometry={parcel?.geometry} pin={pin} onPick={onPick} height={260}
            />
            {resolving && (
              <div className="mt-2 text-xs text-slate-500">Looking up the parcel ...</div>
            )}
            {!resolving && parcel && (
              <div className="mt-2 text-xs text-slate-600">
                {parcel.found ? (
                  <>
                    <div>
                      Parcel {parcel.history?.[0]?.id_parcel} &middot; {parcel.surface_ha} ha &middot;{' '}
                      dept {parcel.department_code ?? '?'}
                    </div>
                    <div className="mt-1">
                      Declared history:{' '}
                      {parcel.history.map((h) => `${h.year} ${h.code_cultu}`).join(', ')}
                    </div>
                  </>
                ) : (
                  <div>No RPG parcel at that point. Click inside a declared field.</div>
                )}
                <Provenance p={parcel.provenance} compact />
              </div>
            )}
          </div>

          <div className="space-y-2 rounded-lg border border-slate-300 bg-white p-3">
            <label className="block text-xs font-medium text-slate-600">
              Department
              <select
                value={req.department_code}
                // Changing department by hand drops the map point: it lies in the
                // department that was just left, and haulage is measured from it. The
                // engine falls back to the new department's centroid, which is the
                // right answer for "somewhere in this department".
                onChange={(e) =>
                  set({ department_code: e.target.value, lon: undefined, lat: undefined })
                }
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {Object.entries(depts).map(([code, d]) => (
                  <option key={code} value={code}>{code} - {d.name}</option>
                ))}
              </select>
            </label>

            <label className="block text-xs font-medium text-slate-600">
              {T.soil}
              <select
                value={req.soil_type}
                onChange={(e) => set({ soil_type: e.target.value })}
                className={`mt-1 w-full rounded border px-2 py-1.5 text-sm ${
                  parcel?.found && parcel.inferred_soil_type === req.soil_type
                    ? 'border-emerald-500 bg-emerald-50'
                    : 'border-slate-300'
                }`}
              >
                {Object.entries(reference?.soils ?? {}).map(([k, s]) => (
                  <option key={k} value={k}>{s.label_fr} ({s.reserve_utile_mm} mm RU)</option>
                ))}
              </select>
              {parcel?.found && parcel.inferred_soil_type === req.soil_type && (
                <span className="mt-0.5 block font-normal text-[11px] text-emerald-700">
                  Inferred from the picked parcel &mdash; confirm before relying on it
                </span>
              )}
            </label>

            <label className="block text-xs font-medium text-slate-600">
              {T.candidate}
              <select
                value={req.candidate_pulse_year2}
                onChange={(e) => set({ candidate_pulse_year2: e.target.value })}
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {(reference?.pulse_crops ?? []).map((c) => (
                  <option key={c} value={c}>{reference.crops[c].label_fr}</option>
                ))}
              </select>
            </label>

            <label className="block text-xs font-medium text-slate-600">
              {T.area}
              <input
                type="number" min="1" max="2000" step="1" value={req.area_ha}
                onChange={(e) => set({ area_ha: Number(e.target.value) || 1 })}
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              />
            </label>

            {/* One per row on a phone — three 16px selects side by side truncate the
                crop names to uselessness. */}
            <div className="grid gap-2 text-xs font-medium text-slate-600 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <label key={i} className="block">
                  Year {i + 1}
                  <select
                    value={req.baseline_rotation[i]}
                    onChange={(e) => {
                      const r = [...req.baseline_rotation]; r[i] = e.target.value
                      set({ baseline_rotation: r })
                    }}
                    className="mt-1 w-full rounded border border-slate-300 px-1 py-1.5 text-xs"
                  >
                    {Object.entries(reference?.crops ?? {})
                      .filter(([, c]) => !c.is_legume)
                      .map(([k, c]) => <option key={k} value={k}>{c.label_fr}</option>)}
                  </select>
                </label>
              ))}
            </div>

            {/* Defaults to 'observed', which reproduces the engine's published
                behaviour exactly - so the projection is opt-in, never a surprise. */}
            <label className="block text-xs font-medium text-slate-600">
              {T.climateHorizon}
              <select
                value={req.climate_horizon ?? 'observed'}
                onChange={(e) => set({ climate_horizon: e.target.value })}
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {(reference?.climate_horizons ?? [{ horizon: 'observed', label_en: 'Observed climate' }])
                  .map((h) => (
                    <option key={h.horizon} value={h.horizon}>
                      {lang === 'fr' ? (h.label_fr ?? h.label_en) : h.label_en}
                    </option>
                  ))}
              </select>
            </label>

            {[
              ['has_livestock_ugb_5', T.livestock],
              ['irrigated', T.irrigated],
              ['has_cover_crop', T.coverCrop],
            ].map(([k, label]) => (
              <label key={k} className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox" checked={!!(req[k] ?? (k === 'has_cover_crop'))}
                  onChange={(e) => set({ [k]: e.target.checked })}
                />
                {label}
              </label>
            ))}

            <button
              onClick={compare} disabled={rankBusy}
              className="mt-1 w-full rounded bg-slate-800 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {rankBusy ? 'Comparing...' : T.ranking}
            </button>
          </div>
        </div>

        <div className="space-y-4">
          {error && (
            <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
              {error}
            </div>
          )}
          {busy && !result && <div className="text-sm text-slate-500">Simulating...</div>}

          {result && (
            <>
              {blocked && (
                <div className="rounded-lg border-2 border-rose-400 bg-rose-50 p-3 text-sm font-medium text-rose-900">
                  Agronomically blocked. The figures below are shown so the cost of the constraint
                  is visible, but this crop must not be sown on this parcel until the blocking
                  condition is resolved.
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatCard
                  label={T.medianGain} value={`${eur(risk.median_delta_eur_ha)} EUR/ha`}
                  sub={`${eur(result.financial_3yr_whole_parcel_eur.delta_median_eur)} EUR over ${result.area_ha} ha`}
                  tone={risk.median_delta_eur_ha >= 0 ? 'good' : 'bad'}
                  hint="Median of the difference between the two rotations across all simulated paths."
                />
                <StatCard
                  label={T.probGain} value={pct(risk.prob_pulse_beats_baseline, 1)}
                  sub={`${pct(risk.prob_delta_below_minus_100_eur_ha, 1)} chance of losing over 100 EUR/ha`}
                  tone={risk.prob_pulse_beats_baseline >= 0.6 ? 'good' : risk.prob_pulse_beats_baseline >= 0.45 ? 'warn' : 'bad'}
                />
                <StatCard
                  label={T.worstCase} value={`${eur(risk.delta_q15_eur_ha)} EUR/ha`}
                  sub={`Worst 5% average ${eur(risk.cvar_5pct_delta_eur_ha)} EUR/ha`}
                  tone={risk.delta_q15_eur_ha >= 0 ? 'good' : 'warn'}
                  hint="15th percentile of the difference: roughly a one-in-seven season."
                />
                {/* The quantity is clipped to [0, 1], so a crop that loses money at
                    any grading outcome reports a flat 100% - which reads as a
                    placeholder rather than as the finding it is. Say what it means
                    instead of showing the clipped number bare. */}
                <StatCard
                  label="Food grade needed to break even"
                  value={
                    risk.breakeven_human_grade_fraction == null
                      ? 'n/a'
                      : risk.breakeven_human_grade_fraction >= 0.999
                        ? 'Unreachable'
                        : pct(risk.breakeven_human_grade_fraction)
                  }
                  sub={
                    risk.breakeven_human_grade_fraction == null
                      ? 'No food-versus-feed spread to break even on'
                      : risk.breakeven_human_grade_fraction >= 0.999
                        ? `Even a perfect harvest would not match the cereals here (model expects ${pct(ml.prob_human_grade)})`
                        : `Model expects ${pct(ml.prob_human_grade)}`
                  }
                  tone={
                    risk.breakeven_human_grade_fraction != null &&
                    risk.breakeven_human_grade_fraction < 0.999 &&
                    ml.prob_human_grade > risk.breakeven_human_grade_fraction ? 'good' : 'warn'
                  }
                  hint="The share of the harvest that must clear food specification for the pulse to match the current rotation. Capped at 100%: when it reads Unreachable, the limit is the crop's price, not its quality."
                />
              </div>

              {/* Sits directly under the four point figures it qualifies. Placing it
                  lower would let a reader take the headline and leave. */}
              <RobustnessBadge r={risk.robustness} />

              <SorterPanel s={result.sorter_access} areaHa={result.area_ha} />

              {/* Given the lead position deliberately: of everything this engine
                  computes, this is the block that answers what people in France eat. */}
              <FoodOutcomePanel
                f={result.food_outcome}
                T={T}
                crop={result.crop_label_fr}
              />

              {result.climate_context && result.climate_context.horizon !== 'observed' && (
                <div className="rounded-lg border border-sky-300 bg-sky-50 p-2.5 text-xs text-sky-900">
                  <span className="font-semibold">{result.climate_context.label_en}</span>{' '}
                  &mdash; every sampled season shifted by{' '}
                  <span className="font-medium tabular-nums">
                    +{result.climate_context.total_shift_applied_c.toFixed(2)} C
                  </span>
                  , of which +{result.climate_context.window_catchup_applied_c.toFixed(2)} C is the
                  measured correction for the bootstrap window lagging the last decade.{' '}
                  {result.climate_context.notes}
                </div>
              )}

              <AgroPanel v={result.agronomic_validation} />

              <div className="rounded-lg border border-slate-300 bg-white p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-800">{T.threeYear}</h3>
                  <span className="text-xs text-slate-500">
                    {fin.n_simulations} paired paths &middot; {result.compute_ms} ms
                  </span>
                </div>
                <MarginFan fan={fin.cumulative_margin_fan} />
                <Provenance p={fin.provenance} />
              </div>

              <RiskPreferencePanel
                rp={fin.risk_preference}
                cropLabel={result.crop_label_fr}
              />

              <ClimateLadder
                departmentCode={req.department_code}
                crop={req.candidate_pulse_year2}
                soilType={req.soil_type}
                T={T}
              />

              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-lg border border-slate-300 bg-white p-3">
                  <h3 className="mb-1 text-sm font-semibold text-slate-800">
                    Where the difference comes from
                  </h3>
                  <BreakdownBars b={fin.breakdown_year2_year3_gains} />
                </div>

                <div className="space-y-3">
                  <div className="rounded-lg border border-slate-300 bg-white p-3">
                    <h3 className="mb-2 text-sm font-semibold text-slate-800">
                      Yield and grading, year 2
                    </h3>
                    <div className="grid grid-cols-3 gap-1.5 text-center text-sm sm:gap-2">
                      <div className="rounded bg-rose-50 p-2">
                        <div className="text-[11px] uppercase text-slate-500">Bad year</div>
                        <div className="text-lg font-semibold tabular-nums">{ml.yield_q15_t_ha}</div>
                      </div>
                      <div className="rounded bg-slate-50 p-2">
                        <div className="text-[11px] uppercase text-slate-500">Median</div>
                        <div className="text-lg font-semibold tabular-nums">{ml.yield_median_t_ha}</div>
                      </div>
                      <div className="rounded bg-emerald-50 p-2">
                        <div className="text-[11px] uppercase text-slate-500">Good year</div>
                        <div className="text-lg font-semibold tabular-nums">{ml.yield_q85_t_ha}</div>
                      </div>
                    </div>
                    <div className="mt-2 text-xs text-slate-600">
                      t/ha &middot; food-grade probability {pct(ml.prob_human_grade)} &middot;
                      expected protein {ml.expected_protein_pct}%
                    </div>
                    <Provenance p={ml.provenance} />
                  </div>

                  <div className="rounded-lg border border-slate-300 bg-white p-3">
                    <h3 className="mb-0.5 text-sm font-semibold text-slate-800">
                      Environment, feed-substitution tier
                    </h3>
                    {/* Naming the counterfactual. These figures price the DOWNGRADED
                        fraction against imported soybean meal, which is animal feed.
                        The food tier's own claim lives in the panel above, in tonnes
                        of imported pulse displaced rather than in carbon. */}
                    <p className="mb-2 text-[11px] text-slate-500">
                      Counterfactual: imported Brazilian soybean meal. This is what the
                      fraction that does NOT clear food specification displaces.
                    </p>
                    <div className="space-y-1 text-sm text-slate-700">
                      <div className="flex justify-between">
                        <span>CO2e avoided, {result.environmental_impact.convention.replace('_', ' ')}</span>
                        <span className="font-semibold tabular-nums">
                          {eur(result.environmental_impact.co2e_saved_tons_total, 1)} t
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-500">
                        <span>Bad year to good year (q15-q85)</span>
                        <span className="tabular-nums">
                          {eur(result.environmental_impact.co2e_saved_tons_q15, 1)} to{' '}
                          {eur(result.environmental_impact.co2e_saved_tons_q85, 1)} t
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-500">
                        <span>Under the other convention</span>
                        <span className="tabular-nums">
                          {eur(result.environmental_impact.co2e_saved_tons_other_convention, 1)} t
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Per kg of crude protein</span>
                        <span className="tabular-nums">
                          {result.environmental_impact.co2e_saved_per_kg_protein} kg CO2e
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span>Synthetic N avoided</span>
                        <span className="tabular-nums">
                          {eur(result.environmental_impact.synthetic_n_reduced_kg_total)} kg N
                        </span>
                      </div>
                      {result.environmental_impact.carbon_abatement_cost_eur_per_tonne != null && (
                        <div
                          className={`mt-2 flex justify-between rounded px-2 py-1.5 ${
                            result.environmental_impact.carbon_abatement_cost_eur_per_tonne < 0
                              ? 'bg-emerald-50 text-emerald-800'
                              : 'bg-amber-50 text-amber-900'
                          }`}
                        >
                          <span className="font-medium">
                            {result.environmental_impact.carbon_abatement_cost_eur_per_tonne < 0
                              ? 'Carbon cut pays for itself'
                              : 'Cost of this carbon cut'}
                          </span>
                          <span className="font-semibold tabular-nums">
                            {result.environmental_impact.carbon_abatement_cost_eur_per_tonne < 0
                              ? `+${eur(-result.environmental_impact.carbon_abatement_cost_eur_per_tonne)} EUR/t profit`
                              : `${eur(result.environmental_impact.carbon_abatement_cost_eur_per_tonne)} EUR/t`}
                          </span>
                        </div>
                      )}
                    </div>
                    <Provenance p={result.environmental_impact.provenance} />
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-slate-300 bg-white p-3">
                <h3 className="mb-2 text-sm font-semibold text-slate-800">{T.contracts}</h3>
                <ContractTable
                  contracts={result.matched_offtake_contracts}
                  selected={req.selected_buyer_id}
                  onSelect={(id) => set({ selected_buyer_id: id })}
                />
              </div>

              {ranked && (
                <div className="rounded-lg border border-slate-300 bg-white p-3">
                  <h3 className="mb-2 text-sm font-semibold text-slate-800">
                    Every pulse on this parcel
                  </h3>
                  <CandidateTable
                    ranked={ranked} current={req.candidate_pulse_year2}
                    onPick={(c) => set({ candidate_pulse_year2: c })}
                  />
                </div>
              )}

              <div className="rounded-lg border border-slate-300 bg-white p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-800">{T.assumptions}</h3>
                  <button
                    onClick={loadDossier}
                    className="rounded border border-slate-400 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  >
                    {T.dossier}
                  </button>
                </div>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-slate-600">
                  {result.assumptions.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>

              {dossier && (
                <div className="rounded-lg border-2 border-slate-400 bg-white p-4 print:border-0">
                  <div className="flex items-baseline justify-between">
                    <h3 className="text-base font-semibold text-slate-900">
                      Advisor transition dossier &middot; {dossier.crop}
                    </h3>
                    <button
                      onClick={() => window.print()}
                      className="rounded border border-slate-400 px-2 py-1 text-xs print:hidden"
                    >
                      Print
                    </button>
                  </div>
                  <p className="text-xs text-slate-500">
                    Parcel {dossier.parcel_id ?? '-'} &middot; department {dossier.department} &middot;
                    generated {dossier.generated_at}
                  </p>
                  <h4 className="mt-3 text-sm font-semibold text-slate-800">Checklist before sowing</h4>
                  <ul className="mt-1 space-y-1 text-sm">
                    {dossier.agronomic_checklist.map((c, i) => (
                      <li key={i} className="flex gap-2">
                        <span
                          className={`mt-0.5 inline-block w-28 shrink-0 rounded px-1.5 text-[10px] font-semibold uppercase ${
                            c.status === 'pass' ? 'bg-emerald-100 text-emerald-800'
                              : c.status === 'fail' ? 'bg-rose-100 text-rose-800'
                                : c.status === 'action_required' ? 'bg-amber-100 text-amber-900'
                                  : 'bg-slate-100 text-slate-600'
                          }`}
                        >
                          {c.status.replace('_', ' ')}
                        </span>
                        <span>
                          <span className="font-medium text-slate-800">{c.item}.</span>{' '}
                          <span className="text-slate-600">{c.detail}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                  <h4 className="mt-3 text-sm font-semibold text-slate-800">Recommendation</h4>
                  <p className="text-sm text-slate-700">
                    {dossier.sections[0].body.recommendation}
                  </p>
                  <p className="mt-3 border-t border-slate-200 pt-2 text-[11px] italic text-slate-500">
                    {dossier.disclaimer}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
