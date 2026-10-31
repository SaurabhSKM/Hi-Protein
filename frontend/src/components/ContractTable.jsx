import { eur } from '../lib/api.js'

const FIT = {
  comfortable: ['Comfortable', 'bg-emerald-100 text-emerald-800'],
  tight: ['Tight', 'bg-amber-100 text-amber-900'],
  at_risk: ['At risk', 'bg-rose-100 text-rose-800'],
}

export default function ContractTable({ contracts, selected, onSelect }) {
  if (!contracts?.length) {
    return <p className="text-sm text-slate-500">No buyer in the book takes this crop in this region.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-2 pr-2">Buyer</th>
            <th className="py-2 pr-2 text-right">Food price</th>
            <th className="py-2 pr-2 text-right">Floor</th>
            <th className="py-2 pr-2">Quality grid</th>
            <th className="py-2 pr-2 text-right">Expected</th>
            <th className="py-2 pr-2 text-right">Bad year</th>
            <th className="py-2 pr-2 text-right">km</th>
            <th className="py-2" />
          </tr>
        </thead>
        <tbody>
          {contracts.map((c) => {
            const [fitLabel, fitCls] = FIT[c.quality_fit] ?? ['-', 'bg-slate-100 text-slate-700']
            const isFloor = c.contract_price_eur_t == null
            return (
              <tr
                key={c.buyer_id}
                className={`border-b border-slate-100 ${selected === c.buyer_id ? 'bg-emerald-50/60' : ''}`}
              >
                <td className="py-2 pr-2">
                  <div className="font-medium text-slate-800">{c.buyer_name}</div>
                  <div className="text-[11px] text-slate-500">
                    {c.floor_guaranteed ? 'Floor guaranteed' : isFloor ? 'Benchmark, not an offer' : 'No floor'}
                  </div>
                </td>
                <td className="py-2 pr-2 text-right tabular-nums">
                  {isFloor ? '-' : `${eur(c.contract_price_eur_t)} EUR/t`}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums">{eur(c.fallback_feed_price_eur_t)}</td>
                <td className="py-2 pr-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${fitCls}`}>{fitLabel}</span>
                </td>
                <td className="py-2 pr-2 text-right font-semibold tabular-nums">
                  {eur(c.expected_revenue_eur_ha)}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums text-slate-500">
                  {eur(c.expected_revenue_q15_eur_ha)}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums text-slate-500">
                  {c.distance_km ?? '-'}
                </td>
                <td className="py-2">
                  {!isFloor && (
                    <button
                      onClick={() => onSelect(selected === c.buyer_id ? null : c.buyer_id)}
                      className="rounded border border-emerald-600 px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-600 hover:text-white"
                    >
                      {selected === c.buyer_id ? 'Clear' : 'Price it in'}
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] italic text-slate-500">
        Revenue columns are EUR/ha and already account for the share of the harvest that clears each
        buyer&apos;s quality grid, so a high headline price behind a tolerance this parcel cannot
        reach does not flatter the ranking. Buyer terms are illustrative demo data.
      </p>
    </div>
  )
}
