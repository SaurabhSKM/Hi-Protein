import { useEffect, useState } from 'react'
import AdoptionMap from '../components/AdoptionMap.jsx'
import AttributionPanel from '../components/AttributionPanel.jsx'
import CropAreaTrend from '../components/CropAreaTrend.jsx'
import RpgChangePanel from '../components/RpgChangePanel.jsx'
import { api } from '../lib/api.js'
import { CROP_COLOUR, CROP_LABEL, fmtHa } from '../lib/landPalette.js'

/* "How the land changed": did French farmland move toward lentils and other grain
 * legumes, where, and why.
 *
 * The page is ordered by how much each answer can be trusted, strongest first:
 *
 *   1. WHAT happened, nationally. Agreste SAA, every department and year the panel
 *      covers, declared hectares. The firmest thing here.
 *   2. WHERE it happened. The same figures per department, on a fixed colour scale
 *      so the slider shows growth rather than re-normalising it away.
 *   3. WHY - attempted, and largely a null result. Weather explains nothing once a
 *      national shock is accounted for, and the drivers that would explain it are
 *      series this project has no usable history for.
 *   4. The parcel-level zoom-in, which leads with the reason its own headline
 *      number cannot be taken at face value.
 *
 * Every figure on this page is computed by the backend from a baked artifact. There
 * are no numeric literals in this file, which is deliberate: a number typed into a
 * view is a number that was true when someone typed it.
 */

const CROPS = ['green_lentil', 'chickpea', 'field_pea', 'fava_bean', 'soybean']

function Tabs({ value, onChange, options }) {
  return (
    <div className="flex flex-wrap rounded-lg border border-slate-300 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded px-3 py-1.5 text-xs font-medium ${
            value === o.value
              ? 'bg-slate-800 text-white'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function HeadlineCards({ overview }) {
  const h = overview.headline
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {CROPS.filter((c) => h[c]).map((crop) => {
        const d = h[crop]
        const grew = d.change_first_to_last_ha > 0
        return (
          <div key={crop} className="rounded border border-slate-300 bg-white p-3">
            <div className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 rounded-sm"
                style={{ background: CROP_COLOUR[crop] }}
              />
              <span className="text-xs font-semibold text-slate-700">
                {CROP_LABEL[crop]}
              </span>
            </div>
            <div className="mt-1 text-lg font-bold text-slate-900">
              {d.multiple_first_to_last}&times;
            </div>
            <div className="text-[11px] text-slate-500">
              {fmtHa(d.first_area_ha)} ha in {d.first_year} &rarr;{' '}
              {fmtHa(d.last_area_ha)} ha in {d.last_year}
            </div>
            <div className="mt-1 text-[11px] text-slate-600">
              {grew ? 'Peak' : 'High'} {d.peak_year}: {fmtHa(d.peak_area_ha)} ha
              {d.pct_off_peak > 0 && (
                <span className="text-slate-500">
                  {' '}&middot; now {d.pct_off_peak}% below it
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function LandChangeView() {
  const [overview, setOverview] = useState(null)
  const [attribution, setAttribution] = useState(null)
  const [geometry, setGeometry] = useState(null)
  const [rpg, setRpg] = useState(null)
  const [deptData, setDeptData] = useState(null)
  const [crop, setCrop] = useState('green_lentil')
  const [mapMode, setMapMode] = useState('change')
  const [year, setYear] = useState(null)
  const [section, setSection] = useState('national')
  const [error, setError] = useState(null)

  useEffect(() => {
    api.adoptionOverview()
      .then((o) => {
        setOverview(o)
        setYear(o.years[o.years.length - 1])
      })
      .catch((e) => setError(e.message))
    api.adoptionAttribution().then(setAttribution).catch(() => {})
    api.adoptionGeometry().then(setGeometry).catch(() => {})
  }, [])

  // The parcel artifact is only fetched when its section is opened: it is the
  // heaviest payload on the page and most visitors never scroll to it.
  useEffect(() => {
    if (section === 'parcel' && !rpg) {
      api.rpgChange().then(setRpg).catch((e) => setError(e.message))
    }
  }, [section, rpg])

  useEffect(() => {
    setDeptData(null)
    api.adoptionDepartments(crop).then(setDeptData).catch((e) => setError(e.message))
  }, [crop])

  if (error) {
    return (
      <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
        {error}
      </div>
    )
  }
  if (!overview) return <div className="text-sm text-slate-500">Loading Agreste series...</div>

  const prov = overview.provenance || {}
  const y0 = overview.years[0]
  const y1 = overview.years[overview.years.length - 1]
  const arrivals = overview.arrivals || {}

  return (
    <div className="space-y-4">
      <div className="rounded border border-slate-300 bg-white p-3">
        <h2 className="text-base font-bold text-slate-900">
          Did French land move toward lentils and legumes?
        </h2>
        <p className="mt-1 max-w-4xl text-[13px] leading-relaxed text-slate-600">
          Yes, but not as one movement. Over {y0}-{y1} the two pulses grown for people
          to eat multiplied while the two grown for animal feed roughly halved, and
          four of the five crops here peaked before {y1}. {overview.n_departments}{' '}
          departments, declared hectares, no modelling in this first section.
        </p>
        <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
          <span>
            Source: {prov.area_source}
          </span>
          <span>
            &bull; {arrivals.total_department_crop_arrivals} department-crop
            combinations went from zero hectares to a real area
          </span>
        </div>
      </div>

      <Tabs
        value={section}
        onChange={setSection}
        options={[
          { value: 'national', label: '1. What happened' },
          { value: 'map', label: '2. Where' },
          { value: 'why', label: '3. Why - and what we cannot say' },
          { value: 'parcel', label: '4. Field level, the Beauce' },
        ]}
      />

      {section === 'national' && (
        <div className="space-y-3">
          <HeadlineCards overview={overview} />
          <CropAreaTrend overview={overview} />
          <div className="rounded border border-slate-300 bg-white p-3 text-[11px] leading-relaxed text-slate-500">
            <b className="text-slate-700">The denominator.</b> {prov.denominator}
            <br />
            <b className="text-slate-700">Vintage.</b> {prov.agreste_data_cutoff}
            <br />
            <b className="text-slate-700">Quality flags.</b> {prov.quality_status_caveat}{' '}
            Mix by pulse area:{' '}
            {Object.entries(prov.quality_status_mix_pulse_area_pct || {})
              .map(([k, v]) => `status ${k} ${v}%`)
              .join(', ')}
            .
            <br />
            <b className="text-slate-700">What this is not.</b> {prov.caveat}
          </div>
        </div>
      )}

      {section === 'map' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <div className="mb-1 text-[11px] font-medium text-slate-500">Crop</div>
              <Tabs
                value={crop}
                onChange={setCrop}
                options={CROPS.map((c) => ({ value: c, label: CROP_LABEL[c] }))}
              />
            </div>
            <div>
              <div className="mb-1 text-[11px] font-medium text-slate-500">Show</div>
              <Tabs
                value={mapMode}
                onChange={setMapMode}
                options={[
                  { value: 'change', label: `Change ${y0} to ${y1}` },
                  { value: 'share', label: 'Share in one year' },
                ]}
              />
            </div>
            {mapMode === 'share' && (
              <div className="min-w-0 flex-1 sm:min-w-[240px]">
                <div className="mb-1 text-[11px] font-medium text-slate-500">
                  Year: <span className="font-bold text-slate-800">{year}</span>
                </div>
                <input
                  type="range"
                  min={y0}
                  max={y1}
                  step={1}
                  value={year ?? y1}
                  onChange={(e) => setYear(Number(e.target.value))}
                  className="w-full accent-slate-800"
                />
              </div>
            )}
          </div>

          {deptData ? (
            <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
              <AdoptionMap
                geometry={geometry}
                deptData={deptData}
                year={year}
                mode={mapMode}
              />
              <div className="rounded border border-slate-300 bg-white p-3">
                <div className="text-sm font-semibold text-slate-800">
                  Biggest movers, {CROP_LABEL[crop]}
                </div>
                <div className="mb-2 text-xs text-slate-500">
                  {deptData.n_arrived_during_series} of {deptData.n_departments}{' '}
                  departments went from no declared area in {y0} to a real area by{' '}
                  {y1}.
                </div>
                <div className="max-h-[400px] overflow-auto">
                  <table className="w-full text-[11px]">
                    <thead className="sticky top-0 bg-white">
                      <tr className="text-left text-slate-500">
                        <th className="py-1">Department</th>
                        <th className="text-right">{y0}</th>
                        <th className="text-right">{y1}</th>
                        <th className="text-right">Change</th>
                        <th className="text-right">Peak</th>
                      </tr>
                    </thead>
                    <tbody>
                      {deptData.departments.slice(0, 20).map((d) => (
                        <tr key={d.dept_code} className="border-t border-slate-200">
                          <td className="py-1 text-slate-700">
                            {d.dept_name}{' '}
                            <span className="text-slate-400">{d.dept_code}</span>
                            {d.arrived_during_series && (
                              <span className="ml-1 rounded bg-slate-100 px-1 text-[9px] text-slate-600">
                                new
                              </span>
                            )}
                          </td>
                          <td className="text-right text-slate-600">
                            {fmtHa(d[`area_ha_${y0}`])}
                          </td>
                          <td className="text-right text-slate-800">
                            {fmtHa(d[`area_ha_${y1}`])}
                          </td>
                          <td
                            className={`text-right font-medium ${
                              d.change_ha > 0 ? 'text-slate-900' : 'text-slate-500'
                            }`}
                          >
                            {d.change_ha > 0 ? '+' : ''}
                            {fmtHa(d.change_ha)}
                          </td>
                          <td className="text-right text-slate-500">{d.peak_year}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-1 text-[10px] text-slate-500">
                  Hectares. Top 20 by change; the table is the accessible view of the
                  map beside it.
                </div>
              </div>
            </div>
          ) : (
            <div className="text-sm text-slate-500">Loading departments...</div>
          )}
        </div>
      )}

      {section === 'why' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <div className="mb-1 text-[11px] font-medium text-slate-500">
                Crop for the per-crop panels
              </div>
              <Tabs
                value={crop}
                onChange={setCrop}
                options={CROPS.map((c) => ({ value: c, label: CROP_LABEL[c] }))}
              />
            </div>
          </div>
          <AttributionPanel attribution={attribution} crop={crop} />
        </div>
      )}

      {section === 'parcel' && <RpgChangePanel rpg={rpg} />}
    </div>
  )
}
