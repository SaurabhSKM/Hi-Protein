import {
  Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { eur } from '../lib/api.js'

/* Confidence fan for both rotations. Plotting only the pulse arm, as a naive
   version does, hides that the baseline is uncertain too. The honest comparison
   is two fans drawn from the same weather draws. */
export default function MarginFan({ fan }) {
  if (!fan?.length) return null
  const data = fan.map((r) => ({
    year: r.year,
    pulseBand: [r.pulse_q15, r.pulse_q85],
    baseBand: [r.baseline_q15, r.baseline_q85],
    pulse: r.pulse_median,
    baseline: r.baseline_median,
  }))
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="year" tick={{ fontSize: 12 }} />
          <YAxis
            tick={{ fontSize: 12 }}
            tickFormatter={(v) => eur(v)}
            label={{ value: 'EUR/ha cumulative', angle: -90, position: 'insideLeft', fontSize: 11 }}
          />
          <Tooltip
            formatter={(v, n) =>
              Array.isArray(v) ? [`${eur(v[0])} to ${eur(v[1])} EUR/ha`, n] : [`${eur(v)} EUR/ha`, n]
            }
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area
            dataKey="baseBand" name="Current rotation, 70% range"
            stroke="none" fill="#94a3b8" fillOpacity={0.25} isAnimationActive={false}
          />
          <Area
            dataKey="pulseBand" name="Pulse rotation, 70% range"
            stroke="none" fill="#16a34a" fillOpacity={0.22} isAnimationActive={false}
          />
          <Line
            dataKey="baseline" name="Current rotation, median"
            stroke="#475569" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false}
          />
          <Line
            dataKey="pulse" name="Pulse rotation, median"
            stroke="#15803d" strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
