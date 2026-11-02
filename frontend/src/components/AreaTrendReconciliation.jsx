import { useEffect, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, eur } from '../lib/api.js'

/* The window-selection fix.
 *
 * The national panel above quotes a 23% fall in human-food pulse area between 2020 and
 * 2022, and that figure is arithmetically correct. But the Land change tab, reading the
 * SAME Agreste series, shows lentil up 2.6x and chickpea up 10.5x since 2010. A reader
 * who moves between the two tabs sees "fell 23%" next to "x10.5" and cannot tell which
 * is true, because neither tab referenced the other.
 *
 * Both are true. The full series is a four-fold rise to a 2019 peak, a sharp two-year
 * dip, and a partial recovery. Picking either endpoint pair alone is cherry-picking, so
 * this component puts the whole series on screen and shades the window the panel above
 * quotes, which is the only honest way to use that number.
 */
export default function AreaTrendReconciliation() {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api
      .adoptionOverview()
      .then((d) => {
        const lentil = Object.fromEntries(
          (d.series?.green_lentil ?? []).map((r) => [r.year, r.area_ha]),
        )
        const chick = Object.fromEntries(
          (d.series?.chickpea ?? []).map((r) => [r.year, r.area_ha]),
        )
        const years = Object.keys(lentil).map(Number).sort((a, b) => a - b)
        setRows(
          years.map((y) => ({
            year: y,
            lentil: lentil[y] ?? 0,
            chickpea: chick[y] ?? 0,
            total: (lentil[y] ?? 0) + (chick[y] ?? 0),
          })),
        )
      })
      .catch((e) => setErr(e.message))
  }, [])

  if (err || !rows || rows.length === 0) return null

  const first = rows[0]
  const last = rows[rows.length - 1]
  const peak = rows.reduce((a, b) => (b.total > a.total ? b : a), rows[0])
  const y2020 = rows.find((r) => r.year === 2020)
  const y2022 = rows.find((r) => r.year === 2022)

  const pct = (from, to) => `${to > from ? '+' : ''}${(100 * (to / from - 1)).toFixed(0)}%`

  return (
    <div className="rounded-lg border-2 border-amber-300 bg-amber-50/50 p-3">
      <h3 className="text-sm font-semibold text-slate-800">
        The same series, read three ways &mdash; so you can judge the &minus;23% for
        yourself
      </h3>
      <p className="mt-1 text-xs text-slate-700">
        The panel above quotes a <span className="font-semibold">&minus;23%</span> fall
        between 2020 and 2022, and that is correct. It is also a two-year window inside a
        dip. Here is the whole Agreste series for the two flagship food pulses, with that
        window shaded, because quoting either endpoint pair on its own would be
        cherry-picking.
      </p>

      <div className="mt-3 h-56">
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 6, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e7d8b0" />
            <XAxis dataKey="year" tick={{ fontSize: 10 }} />
            <YAxis
              tick={{ fontSize: 10 }}
              width={52}
              tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
            />
            <Tooltip
              formatter={(v, n) => [`${eur(v)} ha`, n]}
              labelFormatter={(y) => `${y}`}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {y2020 && y2022 && (
              <ReferenceArea
                x1={2020}
                x2={2022}
                fill="#b45309"
                fillOpacity={0.14}
                label={{ value: 'quoted window', fontSize: 9, fill: '#92400e' }}
              />
            )}
            <Area
              type="monotone"
              dataKey="lentil"
              name="Green lentil"
              stackId="1"
              stroke="#15803d"
              fill="#86efac"
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="chickpea"
              name="Chickpea"
              stackId="1"
              stroke="#b45309"
              fill="#fcd34d"
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {[
          [
            `${first.year} to ${peak.year}`,
            pct(first.total, peak.total),
            `${eur(first.total)} to ${eur(peak.total)} ha — a four-fold rise`,
            'text-emerald-800',
          ],
          [
            y2020 && y2022 ? `${y2020.year} to ${y2022.year}` : 'the quoted window',
            y2020 && y2022 ? pct(y2020.total, y2022.total) : '—',
            'the figure the panel above quotes — a real two-year collapse',
            'text-rose-800',
          ],
          [
            `${first.year} to ${last.year}`,
            pct(first.total, last.total),
            `${eur(last.total)} ha today, still ${(
              100 *
              (1 - last.total / peak.total)
            ).toFixed(0)}% off the ${peak.year} peak`,
            'text-slate-800',
          ],
        ].map(([label, value, sub, tone]) => (
          <div key={label} className="rounded border border-amber-200 bg-white p-2">
            <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
            <div className={`mt-0.5 text-xl font-semibold tabular-nums ${tone}`}>{value}</div>
            <div className="mt-0.5 text-[11px] text-slate-600">{sub}</div>
          </div>
        ))}
      </div>

      <p className="mt-2 text-[11px] text-slate-700">
        <span className="font-semibold">How to read all three together.</span> Human-food
        pulse area is structurally much larger than it was in 2010 and has not recovered
        its {peak.year} peak. So the honest claim is not &ldquo;the crop collapsed&rdquo;
        but <span className="font-semibold">&ldquo;it grew fast, then stalled and
        partially reversed&rdquo;</span> &mdash; and the demand gap on the left is
        unchanged either way, because France still imports more than half of what it
        eats. The Land change tab breaks the same series down by department and tests
        what drives it.
      </p>
    </div>
  )
}
