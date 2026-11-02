import { useEffect, useState } from 'react'
import Provenance from './Provenance.jsx'
import { api, eur, pct } from '../lib/api.js'

/* The 'tomorrow' question, as a ladder rather than a single answer.

   One row per warming horizon, same parcel, same seed, same everything else - so the
   rows differ only by climate. The columns on the right are the drivers, included
   because a reader should be able to see WHY the food fraction moves, and to notice
   that harvest rain does not move at all: it has no measurable temperature response in
   the observed record, so the engine refuses to give it a trend. The threat warming
   poses to pulse grading is insect pressure, not wetter harvests. */
export default function ClimateLadder({ departmentCode, crop, soilType, T }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    setBusy(true)
    setError(null)
    api
      .climateOutlook(departmentCode, crop, soilType, 500)
      .then((d) => { if (live) setData(d) })
      .catch((e) => { if (live) setError(e.message) })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [departmentCode, crop, soilType])

  if (error) {
    return (
      <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
        {error}
      </div>
    )
  }
  if (busy && !data) {
    return <div className="text-sm text-slate-500">{T.climateLoading}</div>
  }
  if (!data) return null

  const obs = data.rows.find((r) => r.horizon === 'observed')
  const rel = (v, base) => (base > 1e-9 ? v / base - 1 : 0)

  return (
    <div className="rounded-lg border border-slate-300 bg-white p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">{T.climateLadder}</h3>
        <span className="text-xs text-slate-500">{data.compute_ms} ms</span>
      </div>

      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-300 text-left text-slate-500">
              <th className="py-1 pr-2 font-medium">{T.horizon}</th>
              <th className="py-1 pr-2 text-right font-medium">{T.shiftApplied}</th>
              <th className="py-1 pr-2 text-right font-medium">{T.yieldMedian}</th>
              <th className="py-1 pr-2 text-right font-medium">P_human</th>
              <th className="py-1 pr-2 text-right font-medium">{T.foodPerHa}</th>
              <th className="py-1 pr-2 text-right font-medium">{T.marginDelta}</th>
              <th className="py-1 pr-2 text-right font-medium">{T.mayDays}</th>
              <th className="py-1 pr-2 text-right font-medium">{T.junHeat}</th>
              <th className="py-1 pr-2 text-right font-medium">{T.harvestRain}</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const dFood = obs ? rel(r.food_grade_tonnes_per_ha, obs.food_grade_tonnes_per_ha) : 0
              return (
                <tr key={r.horizon} className="border-b border-slate-100 last:border-0">
                  <td className="py-1.5 pr-2">
                    <div className="font-medium text-slate-800">{r.label_en}</div>
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums text-slate-500">
                    {r.total_shift_applied_c > 0 ? `+${r.total_shift_applied_c.toFixed(2)}` : '0.00'}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{r.yield_median_t_ha.toFixed(2)}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{pct(r.prob_human_grade, 1)}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">
                    {r.food_grade_tonnes_per_ha.toFixed(3)}
                    {r.horizon !== 'observed' && (
                      <span className={dFood < -0.005 ? 'ml-1 text-rose-600' : 'ml-1 text-slate-400'}>
                        {dFood >= 0 ? '+' : ''}{(dFood * 100).toFixed(0)}%
                      </span>
                    )}
                  </td>
                  <td
                    className={`py-1.5 pr-2 text-right tabular-nums ${
                      r.median_delta_eur_ha >= 0 ? 'text-emerald-700' : 'text-rose-700'
                    }`}
                  >
                    {eur(r.median_delta_eur_ha)}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums text-amber-800">
                    {r.may_days_above_20c.toFixed(1)}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums text-amber-800">
                    {r.jun_heat_days_30c.toFixed(1)}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums text-slate-400">
                    {r.harvest_rain_mm.toFixed(0)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-2 rounded border-l-2 border-emerald-400 bg-emerald-50/60 p-2 text-xs text-slate-700">
        {data.finding}
      </div>
      <div className="mt-2 text-[11px] text-slate-500">
        {T.windowCatchup.replace('{c}', data.window_catchup_c.toFixed(2))}
      </div>
      <Provenance p={data.provenance} />
    </div>
  )
}
