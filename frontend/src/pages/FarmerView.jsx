import { useCallback, useEffect, useMemo, useState } from 'react'
import AgroPanel from '../components/AgroPanel.jsx'
import BreakdownBars from '../components/BreakdownBars.jsx'
import CandidateTable from '../components/CandidateTable.jsx'
import ContractTable from '../components/ContractTable.jsx'
import MarginFan from '../components/MarginFan.jsx'
import ParcelMap from '../components/ParcelMap.jsx'
import Provenance from '../components/Provenance.jsx'
import StatCard from '../components/StatCard.jsx'
import { api, eur, pct } from '../lib/api.js'

const PRESETS = [
  {
    key: 'beauce',
    title: 'Beauce, deep loam',
    sub: 'High cereal yields raise the bar a pulse has to clear',
    req: {
      department_code: '28', parcel_id: 'RPG-28-09412', area_ha: 45, soil_type: 'deep_loam',
      baseline_rotation: ['soft_wheat', 'spring_barley', 'rapeseed'],
      candidate_pulse_year2: 'field_pea', has_livestock_ugb_5: false, irrigated: false,
    },
  },
  {
    key: 'bourgogne',
    title: "Cote-d'Or, shallow limestone",
    sub: 'Low cereal yields, so the pulse competes well',
    req: {
      department_code: '21', parcel_id: 'RPG-21-00421', area_ha: 40, soil_type: 'shallow_limestone',
      baseline_rotation: ['soft_wheat', 'spring_barley', 'rapeseed'],
      candidate_pulse_year2: 'winter_pea', has_livestock_ugb_5: false, irrigated: false,
    },
  },
  {
    key: 'gers',
    title: 'Gers, irrigated clay loam',
    sub: 'Irrigated soy with a non-GMO contract',
    req: {
      department_code: '32', parcel_id: 'RPG-32-01180', area_ha: 30, soil_type: 'clay_loam',
      baseline_rotation: ['durum_wheat', 'sunflower', 'soft_wheat'],
      candidate_pulse_year2: 'soybean', has_livestock_ugb_5: false, irrigated: true,
    },
  },
  {
    key: 'mixed',
    title: 'Mixed crop-livestock',
    sub: 'A downgraded harvest is fed on farm, not sold at a loss',
    req: {
      department_code: '21', parcel_id: 'RPG-21-00887', area_ha: 25, soil_type: 'clay_loam',
      baseline_rotation: ['soft_wheat', 'spring_barley', 'grain_maize'],
      candidate_pulse_year2: 'fava_bean', has_livestock_ugb_5: true, irrigated: false,
    },
  },
]

export default function FarmerView({ reference, lang, T }) {
  const [req, setReq] = useState(PRESETS[1].req)
  const [result, setResult] = useState(null)
  const [ranked, setRanked] = useState(null)
  const [parcel, setParcel] = useState(null)
  const [pin, setPin] = useState(null)
  const [busy, setBusy] = useState(false)
  const [rankBusy, setRankBusy] = useState(false)
  const [error, setError] = useState(null)
  const [dossier, setDossier] = useState(null)

  const depts = reference?.departments ?? {}
  const center = useMemo(() => {
    const d = depts[req.department_code]
    return d ? [d.centroid[1], d.centroid[0]] : [47.4, 2.5]
  }, [depts, req.department_code])

  const run = useCallback(async (body) => {
    setBusy(true); setError(null)
    try {
      setResult(await api.simulate(body))
    } catch (e) { setError(e.message); setResult(null) } finally { setBusy(false) }
  }, [])

  useEffect(() => { run(req) }, [req, run])

  const set = (patch) => { setDossier(null); setReq((r) => ({ ...r, ...patch })) }

  const compare = async () => {
    setRankBusy(true)
    try { setRanked((await api.rank(req)).ranked) }
    catch (e) { setError(e.message) } finally { setRankBusy(false) }
  }

  const onPick = async (lon, lat) => {
    setPin([lon, lat])
    try {
      const p = await api.parcel(lon, lat)
      setParcel(p)
      if (p.found) {
        set({
          department_code: p.department_code ?? req.department_code,
          soil_type: p.inferred_soil_type ?? req.soil_type,
          area_ha: p.surface_ha ?? req.area_ha,
          parcel_id: p.history?.[0]?.id_parcel ? `RPG-${p.history[0].id_parcel}` : req.parcel_id,
          crop_history: p.inferred_rotation?.length ? p.inferred_rotation : undefined,
        })
      }
    } catch (e) { setError(e.message) }
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
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            onClick={() => { setRanked(null); setDossier(null); setReq(p.req) }}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-left text-xs hover:border-emerald-500 hover:bg-emerald-50"
          >
            <div className="font-semibold text-slate-800">{p.title}</div>
            <div className="text-slate-500">{p.sub}</div>
          </button>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <div className="space-y-3">
          <div className="rounded-lg border border-slate-300 bg-white p-3">
            <h3 className="mb-2 text-sm font-semibold text-slate-800">{T.parcel}</h3>
            <p className="mb-2 text-xs text-slate-500">{T.clickMap}</p>
            <ParcelMap
              center={center} geometry={parcel?.geometry} pin={pin} onPick={onPick} height={260}
            />
            {parcel && (
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
                onChange={(e) => set({ department_code: e.target.value })}
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
                className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {Object.entries(reference?.soils ?? {}).map(([k, s]) => (
                  <option key={k} value={k}>{s.label_fr} ({s.reserve_utile_mm} mm RU)</option>
                ))}
              </select>
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

            <div className="grid grid-cols-3 gap-2 text-xs font-medium text-slate-600">
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
                <StatCard
                  label="Food grade needed to break even"
                  value={risk.breakeven_human_grade_fraction == null ? '-' : pct(risk.breakeven_human_grade_fraction)}
                  sub={`Model expects ${pct(ml.prob_human_grade)}`}
                  tone={
                    risk.breakeven_human_grade_fraction != null &&
                    ml.prob_human_grade > risk.breakeven_human_grade_fraction ? 'good' : 'warn'
                  }
                  hint="The share of the harvest that must clear food specification for the pulse to match the current rotation."
                />
              </div>

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
                    <div className="grid grid-cols-3 gap-2 text-center text-sm">
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
                    <h3 className="mb-2 text-sm font-semibold text-slate-800">Environment</h3>
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
