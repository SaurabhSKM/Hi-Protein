import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { eur } from '../lib/api.js'

/* Where the three-year difference actually comes from. Showing the forgone
   baseline year-2 margin as a negative bar is essential: it is almost always the
   largest single term, and a chart that lists only the gains is marketing. */
export default function BreakdownBars({ b }) {
  if (!b) return null
  const data = [
    { name: 'Pulse revenue', v: b.pulse_gross_revenue_eur },
    { name: 'PAC coupled aid', v: b.pac_coupled_aid_eur },
    { name: 'Eco-scheme uplift', v: b.eco_scheme_uplift_eur },
    { name: 'Year 3 N saved', v: b.nitrogen_saved_year3_eur },
    { name: 'Year 3 yield boost', v: b.wheat_yield_boost_year3_eur },
    { name: 'On-farm feed value', v: b.on_farm_feed_substitution_eur },
    { name: 'Pulse costs', v: -b.pulse_operational_cost_eur },
    // Zero whenever a sorter is inside the ordinary collection radius, so it drops out
    // of the chart entirely for a well-served parcel and appears only where it bites.
    { name: 'Haulage to sorter', v: -(b.sorter_haulage_cost_eur ?? 0) },
    { name: 'Forgone year-2 margin', v: -b.forgone_baseline_year2_margin_eur },
  ].filter((d) => Math.abs(d.v) > 0.5)

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 56, bottom: 4, left: 110 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => eur(v)} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={105} />
          <Tooltip formatter={(v) => [`${eur(v)} EUR/ha`, 'Contribution']} />
          <Bar dataKey="v" isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.v >= 0 ? '#16a34a' : '#e11d48'} />
            ))}
            <LabelList dataKey="v" position="right" formatter={(v) => eur(v)} style={{ fontSize: 11 }} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
