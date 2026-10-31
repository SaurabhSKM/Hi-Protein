import { eur, pct } from '../lib/api.js'

export default function CandidateTable({ ranked, current, onPick }) {
  if (!ranked?.length) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-2 pr-2">Crop</th>
            <th className="py-2 pr-2">Agronomy</th>
            <th className="py-2 pr-2 text-right">Yield</th>
            <th className="py-2 pr-2 text-right">Food grade</th>
            <th className="py-2 pr-2 text-right">Median gain</th>
            <th className="py-2 pr-2 text-right">Bad year</th>
            <th className="py-2 pr-2 text-right">Chance of gain</th>
            <th className="py-2 pr-2">Best buyer</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((r) => {
            const blocked = r.agronomic_severity === 'blocked'
            return (
              <tr
                key={r.crop}
                onClick={() => onPick(r.crop)}
                className={`cursor-pointer border-b border-slate-100 hover:bg-slate-50 ${
                  current === r.crop ? 'bg-emerald-50/60' : ''
                } ${blocked ? 'opacity-60' : ''}`}
              >
                <td className="py-2 pr-2 font-medium text-slate-800">{r.label_fr}</td>
                <td className="py-2 pr-2">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                      blocked
                        ? 'bg-rose-100 text-rose-800'
                        : r.agronomic_severity === 'caution'
                          ? 'bg-amber-100 text-amber-900'
                          : 'bg-emerald-100 text-emerald-800'
                    }`}
                    title={blocked ? r.blocking_reasons.join(' ') : undefined}
                  >
                    {blocked ? 'Blocked' : r.agronomic_severity === 'caution' ? 'Caution' : 'Clear'}
                  </span>
                </td>
                <td className="py-2 pr-2 text-right tabular-nums">{r.yield_median_t_ha?.toFixed(2)}</td>
                <td className="py-2 pr-2 text-right tabular-nums">{pct(r.prob_human_grade)}</td>
                <td
                  className={`py-2 pr-2 text-right font-semibold tabular-nums ${
                    r.median_delta_eur_ha >= 0 ? 'text-emerald-700' : 'text-rose-700'
                  }`}
                >
                  {eur(r.median_delta_eur_ha)}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums text-slate-500">
                  {eur(r.delta_q15_eur_ha)}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums">{pct(r.prob_beats_baseline)}</td>
                <td className="py-2 pr-2 text-xs text-slate-600">{r.best_buyer ?? '-'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] italic text-slate-500">
        Gains are EUR/ha across the three years, against the same rotation without the pulse, under
        identical weather draws. Click a row to load it above. A blocked crop keeps its numbers
        visible so the cost of the agronomic constraint is explicit, but it must not be sown.
      </p>
    </div>
  )
}
