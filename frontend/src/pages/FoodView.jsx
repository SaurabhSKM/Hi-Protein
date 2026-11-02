import { useEffect, useState } from 'react'
import AreaTrendReconciliation from '../components/AreaTrendReconciliation.jsx'
import Provenance from '../components/Provenance.jsx'
import { api, eur } from '../lib/api.js'

/* The demand side, which nothing else in this app looks at.

   Two questions, in order. Nationally: how much of the pulse on French plates is
   French? Regionally: if a region closed its area gap, would it feed its own
   population - and does closing that gap for MARGIN grow the same thing as closing it
   for FOOD? Where those two diverge, the incentive structure is buying hectares rather
   than meals, and the difference is reported in tonnes. */

const HORIZONS = [
  ['observed', 'Observed climate'],
  ['present', 'Present-day'],
  ['tracc_2030', 'TRACC +2 C (2030)'],
  ['tracc_2050', 'TRACC +2.7 C (2050)'],
]

function Bar({ value, max, tone }) {
  const w = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="h-2.5 w-full overflow-hidden rounded bg-slate-200">
      <div className={`h-full ${tone}`} style={{ width: `${w}%` }} />
    </div>
  )
}

export default function FoodView({ T }) {
  const [horizon, setHorizon] = useState('observed')
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    setBusy(true)
    setError(null)
    api
      .foodDemand(400, horizon)
      .then((d) => { if (live) setData(d) })
      .catch((e) => { if (live) setError(e.message) })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [horizon])

  if (error) {
    return <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>
  }
  if (!data) return <div className="text-sm text-slate-500">{T.foodLoading}</div>

  const n = data.national
  const maxDemand = Math.max(...data.regions.map((r) => r.recommended_demand_t), 1)

  return (
    <div className={`space-y-4 ${busy ? 'opacity-60' : ''}`}>
      {/* ---- national ------------------------------------------------- */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          [T.franceEats, `${eur(n.current_demand_t)} t`, `${n.current_intake_kg_per_capita_year} kg/person/year`, 'neutral'],
          [T.franceGrows, `${eur(n.domestic_food_production_t)} t`, T.legumesSecs2022, 'neutral'],
          [
            T.selfSufficiency,
            `${n.self_sufficiency_current_pct}%`,
            T.selfSufficiencyHint,
            n.self_sufficiency_current_pct >= 70 ? 'good' : 'warn',
          ],
          [
            T.atRecommended,
            `${eur(n.recommended_demand_t)} t`,
            `${n.recommended_intake_kg_per_capita_year} kg/person/year - ${n.self_sufficiency_at_recommended_pct}% covered`,
            'bad',
          ],
        ].map(([l, v, s, tone]) => (
          <div
            key={l}
            className={`rounded-lg border p-3 ${
              tone === 'good'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                : tone === 'warn'
                  ? 'border-amber-200 bg-amber-50 text-amber-900'
                  : tone === 'bad'
                    ? 'border-rose-200 bg-rose-50 text-rose-900'
                    : 'border-slate-200 bg-slate-50 text-slate-900'
            }`}
          >
            <div className="text-[11px] font-medium uppercase tracking-wide opacity-70">{l}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{v}</div>
            <div className="mt-0.5 text-xs opacity-75">{s}</div>
          </div>
        ))}
      </div>

      <div className="rounded-lg border-l-2 border-emerald-400 bg-emerald-50/60 p-3 text-sm text-slate-800">
        {n.finding}
      </div>

      {/* Sits directly under the claim it qualifies, not in a footnote. The -23% is a
          two-year window inside a dip, and the full series is on the Land change tab;
          leaving a reader to find that contradiction themselves is how credibility
          gets lost. */}
      <AreaTrendReconciliation />

      {/* ---- the area-target caveat, stated rather than buried --------- */}
      <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-900">
        <div className="font-semibold">{T.targetCaveatTitle}</div>
        <div className="mt-1">{T.targetCaveatBody}</div>
      </div>

      {/* ---- regional balance ----------------------------------------- */}
      <div className="rounded-lg border border-slate-300 bg-white p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-800">{T.regionalBalance}</h3>
          <label className="text-xs text-slate-600">
            {T.climateHorizon}{' '}
            <select
              value={horizon}
              onChange={(e) => setHorizon(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            >
              {HORIZONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
        </div>
        <p className="mt-1 text-xs text-slate-500">{data.supply_basis}</p>

        <div className="mt-3 space-y-3">
          {data.regions.map((r) => {
            const cov = r.coverage_of_current_demand_pct ?? 0
            return (
              <div key={r.region_code} className="rounded border border-slate-200 p-2.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="text-sm font-medium text-slate-800">
                    {r.region_name}{' '}
                    <span className="text-xs font-normal text-slate-500">
                      {r.population_millions} M {T.inhabitants}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    {!r.has_optical_sorting && (
                      <span className="rounded border border-rose-300 bg-rose-50 px-1.5 py-0.5 font-medium text-rose-800">
                        {T.noSorting}
                      </span>
                    )}
                    <span
                      className={`rounded px-1.5 py-0.5 font-semibold ${
                        cov >= 100
                          ? 'bg-emerald-100 text-emerald-800'
                          : cov >= 60
                            ? 'bg-amber-100 text-amber-900'
                            : 'bg-rose-100 text-rose-800'
                      }`}
                    >
                      {cov.toFixed(0)}% {T.ofWhatItEats}
                    </span>
                  </div>
                </div>

                <div className="mt-2 grid gap-1.5 text-xs sm:grid-cols-3">
                  <div>
                    <div className="mb-0.5 flex justify-between text-slate-500">
                      <span>{T.eatsToday}</span>
                      <span className="tabular-nums">{eur(r.current_demand_t)} t</span>
                    </div>
                    <Bar value={r.current_demand_t} max={maxDemand} tone="bg-slate-500" />
                  </div>
                  <div>
                    <div className="mb-0.5 flex justify-between text-slate-500">
                      <span>{T.atRecommendedShort}</span>
                      <span className="tabular-nums">{eur(r.recommended_demand_t)} t</span>
                    </div>
                    <Bar value={r.recommended_demand_t} max={maxDemand} tone="bg-rose-400" />
                  </div>
                  <div>
                    <div className="mb-0.5 flex justify-between text-slate-500">
                      <span>{T.couldGrade}</span>
                      <span className="tabular-nums">{eur(r.suppliable_food_grade_t)} t</span>
                    </div>
                    <Bar value={r.suppliable_food_grade_t} max={maxDemand} tone="bg-emerald-600" />
                  </div>
                </div>

                <div className="mt-2 text-[11px] text-slate-500">
                  {T.cateringFloor}: {eur(r.collective_catering_t)} t (
                  {eur(r.school_catering_t)} t {T.schools}) &mdash;{' '}
                  {r.covers_collective_catering ? (
                    <span className="text-emerald-700">{T.cateringCovered}</span>
                  ) : (
                    <span className="text-amber-700">
                      {T.cateringShort} ({(r.catering_coverage_pct ?? 0).toFixed(0)}%)
                    </span>
                  )}
                </div>

                {/* Asked by a reader who noticed the column never changes, which is
                    a fair challenge: a constant column looks like a stuck query. It is
                    not - it is structural, and saying so is more useful than letting
                    someone work it out or distrust the table. */}
                <details className="mt-2 rounded border border-slate-200 bg-slate-50 px-2 py-1.5">
                  <summary className="cursor-pointer text-[11px] font-medium text-slate-700">
                    Why &ldquo;best for food&rdquo; is almost always chickpea
                  </summary>
                  <div className="mt-1 space-y-1 text-[11px] text-slate-600">
                    <p>
                      This column maximises one thing: tonnes reaching a human plate per
                      hectare, which is yield &times; the share that passes grading
                      &times; the share of the crop with a human-food market at all.
                      That last factor splits the candidates in two.
                    </p>
                    <p>
                      Lentil (95%) and chickpea (92%) are almost entirely human food.
                      Pea (30%), soy (25%) and fava bean (18%) are mostly animal feed
                      whatever their quality. So only lentil and chickpea can win &mdash;
                      and chickpea yields roughly twice what lentil does, so it wins
                      nearly everywhere. It is arithmetic, not a stuck query.
                    </p>
                    <p>
                      <span className="font-semibold">Read it as a ceiling, not a
                      recommendation.</span> It deliberately ignores profitability
                      &mdash; the EUR/ha beside it is often heavily negative, which is
                      the point of the comparison. And where it is tagged{' '}
                      <span className="rounded bg-amber-100 px-1 font-semibold uppercase">
                        borrowed yield
                      </span>
                      , the department has no chickpea history of its own and the figure
                      comes from departments with the same soil, so treat it as the
                      weakest number in the row.
                    </p>
                  </div>
                </details>

                {/* The divergence: same hectares, two objectives. */}
                <div className="-mx-1 overflow-x-auto px-1"><table className="mt-2 w-full text-[11px]">
                  <thead>
                    <tr className="text-left text-slate-400">
                      <th className="py-0.5 pr-2 font-medium">{T.department}</th>
                      <th className="py-0.5 pr-2 text-right font-medium">{T.gapHa}</th>
                      <th className="py-0.5 pr-2 font-medium">{T.bestForMargin}</th>
                      <th className="py-0.5 pr-2 text-right font-medium">t {T.food}</th>
                      <th className="py-0.5 pr-2 font-medium">{T.bestForFood}</th>
                      <th className="py-0.5 pr-2 text-right font-medium">t {T.food}</th>
                      <th className="py-0.5 pr-2 text-right font-medium">{T.foodForgone}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.departments.map((d) => {
                      const lost = d.food_t_if_food_optimised - d.food_t_if_margin_optimised
                      return (
                        <tr key={d.department_code} className="border-t border-slate-100">
                          <td className="py-0.5 pr-2 text-slate-700">{d.name}</td>
                          <td className="py-0.5 pr-2 text-right tabular-nums">{eur(d.gap_ha)}</td>
                          <td className="py-0.5 pr-2 text-slate-600">
                            {d.best_margin_pulse}{' '}
                            <span className="text-slate-400">({eur(d.best_margin_eur_ha)} EUR/ha)</span>
                          </td>
                          <td className="py-0.5 pr-2 text-right tabular-nums">
                            {eur(d.food_t_if_margin_optimised)}
                          </td>
                          <td className="py-0.5 pr-2 text-emerald-800">
                            {d.best_food_pulse}{' '}
                            <span className="text-slate-400">({eur(d.best_food_margin_eur_ha)} EUR/ha)</span>
                            {/* The farmer tab warns when a yield baseline is borrowed
                                from other departments. This column rests on one in 22
                                of 40 cases, so the same warning belongs here. */}
                            {d.best_food_baseline_is_local === false && (
                              <span
                                className="ml-1 rounded bg-amber-100 px-1 text-[9px] font-semibold uppercase text-amber-900"
                                title={d.best_food_baseline_caveat ?? 'Yield baseline borrowed from other departments.'}
                              >
                                borrowed yield
                              </span>
                            )}
                          </td>
                          <td className="py-0.5 pr-2 text-right tabular-nums text-emerald-800">
                            {eur(d.food_t_if_food_optimised)}
                          </td>
                          <td
                            className={`py-0.5 pr-2 text-right tabular-nums ${
                              lost > 0 ? 'font-medium text-rose-700' : 'text-slate-400'
                            }`}
                          >
                            {lost > 0 ? `${eur(lost)} t` : '-'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table></div>
              </div>
            )
          })}
        </div>

        <div className="mt-3 rounded border-l-2 border-amber-400 bg-amber-50/70 p-2.5 text-xs text-slate-800">
          {data.finding}
        </div>
        <Provenance p={data.provenance} />
      </div>
    </div>
  )
}
