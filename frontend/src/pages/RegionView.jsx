import { useEffect, useState } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip as LTooltip } from 'react-leaflet'
import { api, eur, pct } from '../lib/api.js'

const colour = (gain) =>
  gain >= 250 ? '#047857' : gain >= 100 ? '#16a34a' : gain >= 0 ? '#a3b018' : gain >= -150 ? '#f59e0b' : '#e11d48'

export default function RegionView() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.regional(600).then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) {
    return <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>
  }
  if (!data) return <div className="text-sm text-slate-500">Running a simulation for every department...</div>

  const gapRemaining = data.national_target_share_pct - data.national_current_share_pct

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ['Current pulse share', `${data.national_current_share_pct}%`, 'of French arable land'],
          ['Target', `${data.national_target_share_pct}%`, `by ${data.target_year}`],
          ['Gap in pilot departments', `${eur(data.total_gap_ha)} ha`, `${gapRemaining.toFixed(0)} points to close nationally`],
          [
            'Conversion value',
            `${eur(data.total_conversion_potential_eur / 1e6, 2)} M EUR`,
            'three-year margin gain if the gap converts to its best-fitting pulse',
          ],
        ].map(([l, v, s]) => (
          <div key={l} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{l}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{v}</div>
            <div className="mt-0.5 text-xs text-slate-500">{s}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="overflow-hidden rounded-lg border border-slate-300" style={{ height: 460 }}>
          <MapContainer center={[46.8, 2.4]} zoom={6} scrollWheelZoom>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {data.departments.map((d) => (
              <CircleMarker
                key={d.department_code}
                center={[d.centroid[1], d.centroid[0]]}
                radius={Math.max(8, Math.min(26, Math.sqrt(Math.abs(d.gap_ha)) / 12))}
                pathOptions={{
                  color: colour(d.median_margin_gain_eur_ha),
                  fillColor: colour(d.median_margin_gain_eur_ha),
                  fillOpacity: 0.55, weight: 2,
                }}
              >
                <LTooltip>
                  <div className="text-xs">
                    <div className="font-semibold">{d.department_code} {d.name}</div>
                    <div>Pulse share {d.pulse_share_pct}% of {eur(d.arable_ha)} ha arable</div>
                    <div>Gap to target {eur(d.gap_ha)} ha</div>
                    <div>Best fit {d.best_pulse}, {eur(d.median_margin_gain_eur_ha)} EUR/ha</div>
                    <div>Chance of gain {pct(d.prob_gain_positive)}</div>
                    <div>
                      Optical sorting within 80 km:{' '}
                      {d.has_optical_sorting_within_80km ? 'yes' : 'NO - infrastructure gap'}
                    </div>
                  </div>
                </LTooltip>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>

        <div className="rounded-lg border border-slate-300 bg-white p-3">
          <h3 className="mb-2 text-sm font-semibold text-slate-800">
            Where a conversion subsidy buys the most
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-300 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-2">Department</th>
                  <th className="py-2 pr-2 text-right">Share</th>
                  <th className="py-2 pr-2 text-right">Gap ha</th>
                  <th className="py-2 pr-2">Best fit</th>
                  <th className="py-2 pr-2 text-right">EUR/ha</th>
                  <th className="py-2 pr-2 text-right">P(gain)</th>
                  <th className="py-2 pr-2">Sorting</th>
                </tr>
              </thead>
              <tbody>
                {data.departments.map((d) => (
                  <tr key={d.department_code} className="border-b border-slate-100">
                    <td className="py-2 pr-2">
                      <div className="font-medium text-slate-800">{d.name}</div>
                      <div className="text-[11px] text-slate-500">{d.region_name}</div>
                    </td>
                    <td className="py-2 pr-2 text-right tabular-nums">{d.pulse_share_pct}%</td>
                    <td className="py-2 pr-2 text-right tabular-nums">{eur(d.gap_ha)}</td>
                    <td className="py-2 pr-2 text-xs">{d.best_pulse}</td>
                    <td
                      className={`py-2 pr-2 text-right font-semibold tabular-nums ${
                        d.median_margin_gain_eur_ha >= 0 ? 'text-emerald-700' : 'text-rose-700'
                      }`}
                    >
                      {eur(d.median_margin_gain_eur_ha)}
                    </td>
                    <td className="py-2 pr-2 text-right tabular-nums">{pct(d.prob_gain_positive)}</td>
                    <td className="py-2 pr-2">
                      {d.has_optical_sorting_within_80km ? (
                        <span className="text-xs text-emerald-700">ok</span>
                      ) : (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-900">
                          gap
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] italic text-slate-500">
            Circle size is the hectare gap to the 8% target; colour is the median three-year margin
            gain per hectare for the best-fitting pulse. A department shown in red is one where a
            conversion subsidy would be pushing against the economics rather than with them, which
            is exactly what a territorial planner needs to know before spending. Arable and pulse
            areas are planning figures, not official Agreste area statistics.
          </p>
        </div>
      </div>
    </div>
  )
}
