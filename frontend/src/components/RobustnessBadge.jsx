import { eur } from '../lib/api.js'

/* Does this verdict survive its own assumptions?
 *
 * The four stat cards above report point figures, and a point figure reads as a fact.
 * A sensitivity audit found that two assumptions - the food-grade pass rate, which has
 * no observational labels anywhere, and the haulage rate and detour factor - can flip
 * the SIGN of the answer on a marginal field. Leaving the user to discover that is how
 * a tool loses trust: they find out by being contradicted.
 *
 * So the recommendation carries its own range, and says plainly when it is fragile.
 * This is deliberately not reassuring. Two of the three demo presets are fragile.
 */
export default function RobustnessBadge({ r }) {
  if (!r || r.central_eur_ha == null) return null

  const robust = r.verdict_is_robust
  const g = r.grading_pass_rate_pm_0_15 ?? {}
  const h = r.haulage_across_published_range ?? {}

  const span = Math.max(r.range_high_eur_ha - r.range_low_eur_ha, 1)
  const pos = (v) => `${((v - r.range_low_eur_ha) / span) * 100}%`
  const zeroInRange =
    r.range_low_eur_ha < 0 && r.range_high_eur_ha > 0

  return (
    <div
      className={`rounded-lg border-2 p-3 ${
        robust ? 'border-emerald-300 bg-emerald-50/50' : 'border-amber-400 bg-amber-50'
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">
          Does this answer survive its own assumptions?
        </h3>
        <span
          className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
            robust ? 'bg-emerald-600 text-white' : 'bg-amber-500 text-white'
          }`}
        >
          {robust ? 'Verdict holds' : 'Verdict is fragile'}
        </span>
      </div>

      <p className="mt-1 text-sm text-slate-700">{r.verdict}</p>

      {/* The range, with the zero line marked, because where zero sits inside the
          range is the entire question. */}
      <div className="mt-3">
        <div className="relative h-7 rounded bg-white/70 ring-1 ring-inset ring-slate-200">
          <div
            className={`absolute top-1 bottom-1 rounded ${
              robust ? 'bg-emerald-300/70' : 'bg-amber-300/70'
            }`}
            style={{ left: '2%', right: '2%' }}
          />
          {zeroInRange && (
            <div
              className="absolute top-0 bottom-0 w-0.5 bg-rose-600"
              style={{ left: pos(0) }}
              title="Break-even. The range crosses it, so the recommendation changes sign inside it."
            />
          )}
          <div
            className="absolute top-0 bottom-0 w-1 rounded bg-slate-900"
            style={{ left: pos(r.central_eur_ha) }}
            title="The figure reported above"
          />
        </div>
        <div className="mt-1 flex justify-between text-[11px] tabular-nums text-slate-600">
          <span>{eur(r.range_low_eur_ha)} EUR/ha</span>
          <span className="font-semibold text-slate-800">
            reported: {eur(r.central_eur_ha)}
          </span>
          <span>{eur(r.range_high_eur_ha)} EUR/ha</span>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded border border-slate-200 bg-white p-2">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            Food-grade pass rate &plusmn;15 points
          </div>
          <div className="mt-0.5 text-sm tabular-nums text-slate-800">
            {eur(g.low)} &rarr; <span className="font-semibold">{eur(g.central)}</span>{' '}
            &rarr; {eur(g.high)} EUR/ha
          </div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            The widest band of the two, and the one with no observational labels anywhere
            in French open data.
          </div>
        </div>
        <div className="rounded border border-slate-200 bg-white p-2">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            Haulage across its published range
          </div>
          <div className="mt-0.5 text-sm tabular-nums text-slate-800">
            {h.binding ? (
              <>
                {eur(h.low)} &rarr; <span className="font-semibold">{eur(h.central)}</span>{' '}
                &rarr; {eur(h.high)} EUR/ha
              </>
            ) : (
              <span className="text-slate-500">
                Not binding &mdash; a sorter is inside the free collection radius
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            {h.rate_range_eur_t_km
              ? `€${h.rate_range_eur_t_km[0]}–${h.rate_range_eur_t_km[1]}/t/km crossed with a ${h.detour_range?.[0]}–${h.detour_range?.[1]} road detour factor.`
              : 'Published rate range crossed with the detour spread.'}
          </div>
        </div>
      </div>

      <p className="mt-2 text-[11px] italic text-slate-500">
        {r.method}
      </p>
    </div>
  )
}
