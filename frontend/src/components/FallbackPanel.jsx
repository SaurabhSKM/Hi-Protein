import { eur } from '../lib/api.js'

/* The downside bar, drawn twice.
 *
 * The point of this component is that the two numbers stay on screen TOGETHER. An
 * earlier version was a checkbox among three others: ticking it replaced the figure and
 * the old one vanished, so the user had to remember a number to see a change. Here the
 * before bar stays put and the after bar grows out of it, which is the whole argument
 * of the product in one picture.
 *
 * Bars are drawn on a shared scale that spans both values and always includes zero, so
 * the zero line is where a reader expects it and the two bars are directly comparable.
 */
function DownsideBars({ without, withFallback }) {
  const lo = Math.min(without, withFallback, 0)
  const hi = Math.max(without, withFallback, 0)
  const span = hi - lo || 1
  const zeroPct = ((0 - lo) / span) * 100

  const bar = (v, label, tone) => {
    const vPct = ((v - lo) / span) * 100
    const left = Math.min(vPct, zeroPct)
    const width = Math.abs(vPct - zeroPct)
    return (
      <div className="mb-2">
        <div className="mb-0.5 flex items-baseline justify-between text-xs">
          <span className="text-slate-600">{label}</span>
          <span className={`font-semibold tabular-nums ${v >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>
            {eur(v)} EUR/ha
          </span>
        </div>
        <div className="relative h-5 rounded bg-slate-100">
          <div
            className="absolute top-0 bottom-0 w-px bg-slate-400"
            style={{ left: `${zeroPct}%` }}
          />
          <div
            className={`absolute top-0.5 bottom-0.5 rounded ${tone}`}
            style={{ left: `${left}%`, width: `${Math.max(width, 0.8)}%` }}
          />
        </div>
      </div>
    )
  }

  return (
    <div>
      {bar(without, 'Bad year without a fallback contract', 'bg-rose-400')}
      {bar(withFallback, 'Bad year with a local breeder contract', 'bg-emerald-500')}
    </div>
  )
}

export default function FallbackPanel({ f, cropLabel }) {
  if (!f) return null

  const worth = f.worth_signing ?? {}
  const hasPair =
    f.cvar_without_fallback_eur_ha != null && f.cvar_with_fallback_eur_ha != null

  return (
    <div className="rounded-lg border-2 border-emerald-300 bg-emerald-50/40 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">
          The bad year, and who takes it off your hands
        </h3>
        <span className="text-[11px] text-slate-500">
          downgraded lot {eur(f.downgraded_lot_t_median, 1)} t &middot; within{' '}
          {eur(f.search_radius_km)} km
        </span>
      </div>

      <p className="mt-1 text-sm text-slate-700">{f.headline}</p>

      {/* The mechanism can be unavailable for two quite different reasons, and the
          difference matters: nobody is close enough, or the feed market already pays
          more than a livestock ration would. Only the second is a dead end. */}
      {worth.worth_signing === false && (
        <p className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
          {worth.reason}
        </p>
      )}

      {hasPair && (
        <div className="mt-3">
          <DownsideBars
            without={f.cvar_without_fallback_eur_ha}
            withFallback={f.cvar_with_fallback_eur_ha}
          />
          <div className="mt-1 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div>
              <div className="text-slate-500">Worst 15% improves by</div>
              <div className="font-semibold tabular-nums text-emerald-800">
                {eur(f.cvar_improvement_eur_ha)} EUR/ha
              </div>
            </div>
            <div>
              <div className="text-slate-500">Median improves by</div>
              <div className="font-semibold tabular-nums">
                {eur(
                  f.median_with_fallback_eur_ha - f.median_without_fallback_eur_ha,
                )}{' '}
                EUR/ha
              </div>
            </div>
            <div>
              <div className="text-slate-500">Contract price</div>
              <div className="font-semibold tabular-nums">
                {eur(f.best_offered_price_eur_t)} EUR/t
              </div>
            </div>
            <div>
              <div className="text-slate-500">Feed market pays</div>
              <div className="font-semibold tabular-nums text-slate-600">
                {eur(f.feed_spot_price_eur_t)} EUR/t
              </div>
            </div>
          </div>
          {/* Measured, and it contradicts the intuitive pitch, so it is stated rather
              than left for someone to discover. */}
          <p className="mt-2 text-[11px] italic text-slate-500">
            The uplift is close to flat across good and bad years rather than
            concentrated in the downside. A low-yield year has fewer tonnes to
            downgrade, so poor yield and poor grading roughly cancel in downgraded
            tonnage. This is a revenue floor, not insurance.
          </p>
        </div>
      )}

      {f.matches?.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="border-b border-slate-300 text-left uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-1.5 pr-2">Holding</th>
                <th className="py-1.5 pr-2 text-right">km</th>
                <th className="py-1.5 pr-2">Herd</th>
                <th className="py-1.5 pr-2 text-right">Can take</th>
                <th className="py-1.5 pr-2 text-right">Pays</th>
                <th className="py-1.5 text-right">Their avoided soy</th>
              </tr>
            </thead>
            <tbody>
              {f.matches.map((m) => (
                <tr key={m.breeder_id} className="border-b border-slate-100">
                  <td className="py-1.5 pr-2">
                    <div className="font-medium text-slate-800">{m.name}</div>
                    <div className="text-[10px] text-slate-500">
                      dept {m.dept} &middot; {m.ugb} UGB
                    </div>
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{m.distance_km}</td>
                  <td className="py-1.5 pr-2">{m.herd_type}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">
                    {eur(m.max_pulse_intake_t, 1)} t
                    {!m.absorbs_whole_lot && (
                      <span
                        className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-900"
                        title="This holding cannot absorb the whole lot within its inclusion limit."
                      >
                        part
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">
                    {eur(m.offered_price_eur_t)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-emerald-800">
                    {eur(m.breeder_avoided_soy_t, 1)} t &middot;{' '}
                    {eur(m.breeder_avoided_soy_cost_eur)} EUR
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1.5 text-[11px] italic text-slate-500">
            Both sides of the trade are shown deliberately. The lot is worth more inside
            a ration than the feed market pays, and that surplus is split &mdash; the
            farmer takes 55% of it in this model, which is a stated negotiating
            assumption, not a measurement. Haulage past about 25 km eats the premium, so
            holdings beyond it are dropped rather than stretched. Herd identities and
            sizes are illustrative; the locations and the distances are real communes.
          </p>
        </div>
      )}

      {!f.available && f.nearest_holding_km != null && (
        <p className="mt-2 text-xs text-slate-600">
          Nearest holding on file is {eur(f.nearest_holding_km, 1)} km away, outside the{' '}
          {eur(f.search_radius_km)} km radius.
        </p>
      )}

      {f.import_substitution && f.available && (
        <p className="mt-2 text-xs text-slate-700">
          Placed locally, this lot displaces{' '}
          <span className="font-semibold tabular-nums">
            {eur(f.import_substitution.imported_soybean_meal_displaced_t, 1)} t
          </span>{' '}
          of imported soybean meal, worth{' '}
          {eur(f.import_substitution.import_value_displaced_eur)} EUR. Displaced on a
          protein and energy equivalence basis, not tonne for tonne &mdash; soybean meal
          is 46% protein and {cropLabel?.toLowerCase()} is far less.
        </p>
      )}
    </div>
  )
}
