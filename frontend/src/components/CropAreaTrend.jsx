import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { CROP_COLOUR, CROP_LABEL, INK, fmtHa } from '../lib/landPalette.js'

/* National area over time.
 *
 * Why this is several small charts and not one.
 * Field pea sits at 120,000-210,000 ha and green lentil at 12,000-38,000. On one
 * linear axis the lentil line is a flat smear along the bottom, which is the exact
 * opposite of the finding. The two ways out of a scale mismatch are a second y-axis
 * or a common base; a second y-axis lets the author decide which line looks higher,
 * so it is not used anywhere here. Instead the absolute charts are faceted by outlet
 * - the division the data actually turns on - and a separate indexed chart puts all
 * five crops on one scale honestly, with every series starting at 100.
 */

/* Direct label at the end of each line, so a reader never has to match a colour to
 * a legend swatch. This is also what makes the orange/green pair legible to a
 * deuteranopic reader, for whom those two hues sit close together. */
function EndLabel({ x, y, value, index, lastIndex, colour, text }) {
  if (index !== lastIndex || value == null) return null
  return (
    <text x={x + 6} y={y} dy={4} fontSize={11} fontWeight={600} fill={colour}>
      {text}
    </text>
  )
}

function TrendChart({ title, subtitle, crops, overview, mode, height = 260 }) {
  const years = overview.years
  const data = years.map((year, i) => {
    const row = { year }
    for (const crop of crops) {
      const series = overview.series[crop] || []
      const area = series[i]?.area_ha ?? null
      if (mode === 'indexed') {
        const base = series.find((r) => r.area_ha != null)?.area_ha
        row[crop] = area != null && base ? Math.round((100 * area) / base) : null
      } else {
        row[crop] = area
      }
    }
    return row
  })
  const lastIndex = data.length - 1

  return (
    <div className="rounded border border-slate-300 bg-white p-3">
      <div className="text-sm font-semibold text-slate-800">{title}</div>
      {subtitle && <div className="mb-1 text-xs text-slate-500">{subtitle}</div>}
      <div style={{ height }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 86, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={INK.grid} />
            <XAxis dataKey="year" tick={{ fontSize: 11, fill: INK.muted }} />
            <YAxis
              tick={{ fontSize: 11, fill: INK.muted }}
              tickFormatter={(v) => (mode === 'indexed' ? v : fmtHa(v))}
              width={mode === 'indexed' ? 40 : 60}
            />
            <Tooltip
              contentStyle={{ fontSize: 12 }}
              labelStyle={{ color: INK.primary, fontWeight: 600 }}
              formatter={(v, n) => [
                mode === 'indexed'
                  ? `${v} (first year = 100)`
                  : `${fmtHa(v)} ha`,
                CROP_LABEL[n] || n,
              ]}
            />
            {/* Reference level for the indexed chart: 100 is "no change since the
                first campaign", so crossing it is the whole question. */}
            {mode === 'indexed' && (
              <Line
                dataKey={() => 100} stroke={INK.muted} strokeWidth={1}
                strokeDasharray="4 4" dot={false} isAnimationActive={false}
                legendType="none" name="__baseline"
              />
            )}
            {crops.map((crop) => (
              <Line
                key={crop}
                dataKey={crop}
                name={crop}
                stroke={CROP_COLOUR[crop]}
                strokeWidth={2}
                dot={{ r: 2.5, strokeWidth: 0, fill: CROP_COLOUR[crop] }}
                activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }}
                connectNulls={false}
                isAnimationActive={false}
                label={(p) => (
                  <EndLabel
                    {...p}
                    lastIndex={lastIndex}
                    colour={CROP_COLOUR[crop]}
                    text={CROP_LABEL[crop]}
                  />
                )}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function CropAreaTrend({ overview }) {
  if (!overview?.years?.length) return null
  const y0 = overview.years[0]
  const y1 = overview.years[overview.years.length - 1]

  return (
    <div className="space-y-3">
      <TrendChart
        title="Indexed to the first campaign, all five crops on one scale"
        subtitle={`Area as a percentage of its own ${y0} level. Above the dashed line is more land than ${y0}, below it is less.`}
        crops={['green_lentil', 'chickpea', 'field_pea', 'fava_bean', 'soybean']}
        overview={overview}
        mode="indexed"
        height={300}
      />
      <div className="grid gap-3 lg:grid-cols-3">
        <TrendChart
          title="Human-food pulses"
          subtitle="Declared hectares"
          crops={['green_lentil', 'chickpea']}
          overview={overview}
          mode="absolute"
        />
        <TrendChart
          title="Animal-feed pulses"
          subtitle="Declared hectares"
          crops={['field_pea', 'fava_bean']}
          overview={overview}
          mode="absolute"
        />
        <TrendChart
          title="Soy"
          subtitle={`Declared hectares, ${y0}-${y1}`}
          crops={['soybean']}
          overview={overview}
          mode="absolute"
        />
      </div>
    </div>
  )
}
