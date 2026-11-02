import { useMemo, useState } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip as LTooltip } from 'react-leaflet'
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { DIV_PUOR, INK, divStep, fmtHa } from '../lib/landPalette.js'

/* The zoom-in: 158,000 real declared parcels in the Beauce, every campaign 2015-2024.
 *
 * This panel leads with a warning rather than the headline, and that ordering is the
 * point. Taken at face value the region's pulse share rises from 2.00% to 3.39%. Most
 * of that is three crop codes that did not exist before the 2023 campaign, which the
 * artifact proves by diffing the official RPG code tables. A dashboard that showed the
 * 3.39% and moved on would be reporting a vocabulary change as an agronomic one.
 */

function VocabWarning({ vocab, totals, years }) {
  const first = String(years[0])
  const last = String(years[years.length - 1])
  const suspects = vocab.pulse_codes_introduced_in_2023
  // The break year and the last comparable year are derived from the artifact, not
  // written down here: if a future campaign changes the vocabulary again, this panel
  // should move with it rather than keep citing 2023.
  const breakYear = Math.min(...suspects.map((s) => s.first_year_present_in_region))
  const lastStable = String(breakYear - 1)
  const t = totals
  return (
    <div className="rounded border border-rose-300 bg-rose-50 p-3">
      <div className="text-sm font-semibold text-rose-900">
        Read this before the numbers: the series breaks in {breakYear}
      </div>
      <p className="mt-1 text-[13px] leading-relaxed text-rose-900">
        {vocab.n_codes_added_in_2023} crop codes were added to the RPG vocabulary in
        the {breakYear} campaign. {suspects.length} of them are grain legumes, they
        record zero hectares here in every campaign from {first} to {lastStable}, and
        they are absent from the official {lastStable} code table and present in the{' '}
        {breakYear} one - so they could not have been declared earlier whatever was
        actually growing.
      </p>
      <div className="-mx-1 overflow-x-auto px-1"><table className="mt-2 w-full text-[11px] text-rose-900">
        <thead>
          <tr className="text-left">
            <th className="py-1">Code</th>
            <th>Label</th>
            <th className="text-right">Hectares on first appearance</th>
          </tr>
        </thead>
        <tbody>
          {vocab.pulse_codes_introduced_in_2023.map((s) => (
            <tr key={s.code_cultu} className="border-t border-rose-200">
              <td className="py-1 font-mono">{s.code_cultu}</td>
              <td>{s.label}</td>
              <td className="text-right">
                {fmtHa(s.ha_in_first_year)} ha in {s.first_year_present_in_region}
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
      <div className="mt-2 grid gap-2 text-[12px] text-rose-900 sm:grid-cols-3">
        <div className="rounded bg-white/70 p-2">
          <div className="text-[10px] uppercase tracking-wide text-rose-700">
            As published, {first} to {last}
          </div>
          <div className="text-base font-semibold">
            {t[first].pulse_share_pct.toFixed(2)}% &rarr; {t[last].pulse_share_pct.toFixed(2)}%
          </div>
          <div className="text-[10px]">not comparable across 2023</div>
        </div>
        <div className="rounded bg-white/70 p-2">
          <div className="text-[10px] uppercase tracking-wide text-rose-700">
            Stable vocabulary, {first} to {lastStable}
          </div>
          <div className="text-base font-semibold">
            {t[first].pulse_share_pct.toFixed(2)}% &rarr;{' '}
            {t[lastStable].pulse_share_pct.toFixed(2)}%
          </div>
          <div className="text-[10px]">like for like: essentially flat</div>
        </div>
        <div className="rounded bg-white/70 p-2">
          <div className="text-[10px] uppercase tracking-wide text-rose-700">
            New codes removed, {first} to {last}
          </div>
          {/* The like-for-like share is recomputed by the build script with the
              newly-introduced codes excluded from every campaign, which is the only
              reading comparable across the break. */}
          <div className="text-base font-semibold">
            {t[first].pulse_share_pct_like_for_like.toFixed(2)}% &rarr;{' '}
            {t[last].pulse_share_pct_like_for_like.toFixed(2)}%
          </div>
          <div className="text-[10px]">the defensible increase</div>
        </div>
      </div>
    </div>
  )
}

/* Lentil is the clean signal here: LEC is present in the 2022, 2023 and 2024 code
 * tables alike and declared in every campaign, so its series needs no adjustment. */
function CodeSeriesChart({ series, years }) {
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? series.slice(0, 10) : series.slice(0, 5)
  const data = years.map((y) => {
    const row = { year: y }
    for (const s of shown) row[s.code_cultu] = s.ha_by_year[String(y)] ?? null
    return row
  })
  // Fixed order so toggling "show more" never repaints an existing series.
  const colours = ['#16a34a', '#0369a1', '#ea580c', '#7c3aed', '#be123c',
    '#0d9488', '#a16207', '#4338ca', '#9d174d', '#1e3a8a']
  return (
    <div className="rounded border border-slate-300 bg-white p-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-800">
            Declared hectares by RPG crop code
          </div>
          <div className="mb-1 text-xs text-slate-500">
            A code that steps off zero in one campaign is a vocabulary change. A code
            that ramps is adoption.
          </div>
        </div>
        <button
          onClick={() => setShowAll(!showAll)}
          className="shrink-0 rounded border border-slate-300 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-100"
        >
          {showAll ? 'Top 5' : 'Top 10'}
        </button>
      </div>
      <div style={{ height: 280 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 56, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={INK.grid} />
            <XAxis dataKey="year" tick={{ fontSize: 11, fill: INK.muted }} />
            <YAxis
              tick={{ fontSize: 11, fill: INK.muted }} width={56}
              tickFormatter={(v) => fmtHa(v)}
            />
            <Tooltip
              contentStyle={{ fontSize: 12 }}
              formatter={(v, n) => {
                const s = shown.find((x) => x.code_cultu === n)
                return [`${fmtHa(v)} ha`, `${n} - ${s?.label ?? ''}`]
              }}
            />
            {shown.map((s, i) => (
              <Line
                key={s.code_cultu}
                dataKey={s.code_cultu}
                stroke={colours[i]}
                strokeWidth={2}
                dot={{ r: 2, strokeWidth: 0, fill: colours[i] }}
                activeDot={{ r: 5, stroke: '#fff', strokeWidth: 2 }}
                isAnimationActive={false}
                label={(p) =>
                  p.index === years.length - 1 && p.value != null ? (
                    <text
                      x={p.x + 5} y={p.y} dy={4} fontSize={10} fontWeight={600}
                      fill={colours[i]}
                    >
                      {s.code_cultu}
                    </text>
                  ) : null
                }
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-600">
        {shown.map((s, i) => (
          <span key={s.code_cultu} className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: colours[i] }}
            />
            <b className="font-mono">{s.code_cultu}</b> {s.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function CellMap({ cells, compareYears }) {
  const [first, last] = compareYears
  const bound = useMemo(() => {
    const vals = cells
      .map((c) => c.pulse_share_change_pp)
      .filter((v) => v != null)
      .map(Math.abs)
    if (!vals.length) return 1
    // 95th percentile rather than the maximum, so one extreme cell cannot flatten
    // the whole ramp into its neutral midpoint.
    const sorted = vals.sort((a, b) => a - b)
    return Math.max(sorted[Math.floor(sorted.length * 0.95)], 0.5)
  }, [cells])

  return (
    <div className="rounded border border-slate-300 bg-white p-3">
      <div className="text-sm font-semibold text-slate-800">
        Change in pulse share per 5 km cell, {first} to {last}
      </div>
      <div className="mb-2 text-xs text-slate-500">
        Includes the codes new in 2023, so cells gaining human-food pea and bean
        declarations read as gains. Hover for the hectares behind each cell.
      </div>
      <div className="h-[360px] overflow-hidden rounded border border-slate-200">
        <MapContainer
          center={[48.2, 1.8]}
          zoom={8}
          scrollWheelZoom={false}
          style={{ height: '100%', width: '100%', background: '#f8fafc' }}
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            attribution="&copy; OpenStreetMap, &copy; CARTO"
          />
          {cells
            .filter((c) => c.pulse_share_change_pp != null)
            .map((c, i) => (
              <CircleMarker
                key={i}
                center={[c.lat, c.lon]}
                radius={6}
                pathOptions={{
                  fillColor: divStep(c.pulse_share_change_pp, bound) ?? '#f1f5f9',
                  fillOpacity: 0.95,
                  color: '#ffffff',
                  weight: 1,
                }}
              >
                <LTooltip>
                  <div style={{ fontSize: 12 }}>
                    <b>
                      {c.pulse_share_change_pp > 0 ? '+' : ''}
                      {c.pulse_share_change_pp.toFixed(2)} pp pulse share
                    </b>
                    <br />
                    {first}: {fmtHa(c[`pulse_ha_${first}`])} of{' '}
                    {fmtHa(c[`declared_ha_${first}`])} ha declared
                    <br />
                    {last}: {fmtHa(c[`pulse_ha_${last}`])} of{' '}
                    {fmtHa(c[`declared_ha_${last}`])} ha declared
                    <br />
                    lentil: {fmtHa(c[`lentil_ha_${first}`])} &rarr;{' '}
                    {fmtHa(c[`lentil_ha_${last}`])} ha
                    <br />
                    {c[`n_parcels_${last}`]} parcels in {last}
                  </div>
                </LTooltip>
              </CircleMarker>
            ))}
        </MapContainer>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex">
          {DIV_PUOR.map((c) => (
            <div key={c} style={{ background: c }} className="h-3 w-5 border border-white" />
          ))}
        </div>
        <div className="flex w-40 justify-between text-[10px] text-slate-500">
          <span>-{bound.toFixed(1)}</span>
          <span>0</span>
          <span>+{bound.toFixed(1)}</span>
        </div>
        <span className="text-[10px] text-slate-500">
          percentage points, orange lost / purple gained
        </span>
      </div>
    </div>
  )
}

export default function RpgChangePanel({ rpg }) {
  if (!rpg) return <div className="text-sm text-slate-500">Loading parcel data...</div>
  const meta = rpg._meta
  const years = meta.years
  const t = rpg.totals_by_year
  const first = String(years[0])
  const last = String(years[years.length - 1])

  return (
    <div className="space-y-3">
      <div className="rounded border border-slate-300 bg-white p-3">
        <div className="text-sm font-semibold text-slate-800">
          Real declared parcels, {meta.region === 'beauce' ? 'the Beauce' : meta.region},{' '}
          {years[0]}-{years[years.length - 1]}
        </div>
        <div className="mt-1 grid gap-3 text-xs sm:grid-cols-4">
          <div>
            <div className="text-slate-500">Parcels in {last}</div>
            <div className="text-base font-semibold text-slate-800">
              {fmtHa(t[last].n_parcels)}
            </div>
          </div>
          <div>
            <div className="text-slate-500">Declared farmland</div>
            <div className="text-base font-semibold text-slate-800">
              {fmtHa(t[last].declared_ha)} ha
            </div>
          </div>
          <div>
            <div className="text-slate-500">Lentil, {first} &rarr; {last}</div>
            <div className="text-base font-semibold text-slate-800">
              {fmtHa(t[first].lentil_ha)} &rarr; {fmtHa(t[last].lentil_ha)} ha
            </div>
            <div className="text-[10px] text-slate-500">
              code LEC, unaffected by the 2023 change
            </div>
          </div>
          <div>
            <div className="text-slate-500">Declared fallow, {last}</div>
            <div className="text-base font-semibold text-slate-800">
              {t[last].fallow_share_pct.toFixed(2)}%
            </div>
            <div className="text-[10px] text-slate-500">cheapest land to convert</div>
          </div>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          {meta.area_basis} {meta.no_parcel_matching}
        </p>
      </div>

      <VocabWarning
        vocab={rpg.vocabulary_change_2023}
        totals={t}
        years={years}
      />

      <div className="grid gap-3 lg:grid-cols-2">
        <CodeSeriesChart series={rpg.pulse_code_series} years={years} />
        <CellMap cells={rpg.cells} compareYears={rpg.cells_compare_years} />
      </div>

      <div className="rounded border border-slate-300 bg-white p-3 text-[11px] leading-relaxed text-slate-500">
        <b className="text-slate-700">How the pulse total is defined here.</b>{' '}
        {meta.pulse_definition} {meta.why_not_project_crop_map}
        <br />
        <b className="text-slate-700">Grid.</b> {meta.cell_assignment}
        <br />
        <b className="text-slate-700">Source.</b> {meta.source}. Code labels from{' '}
        {meta.code_table_source}. {meta.years_available_note}
      </div>
    </div>
  )
}
