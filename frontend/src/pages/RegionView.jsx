import L from 'leaflet'
import { useEffect, useState } from 'react'
import {
  CircleMarker,
  LayerGroup,
  MapContainer,
  Marker,
  TileLayer,
  Tooltip as LTooltip,
} from 'react-leaflet'
import { api, eur, pct } from '../lib/api.js'

/* The regional planner's screen.
 *
 * Two things had to be true for this view to be worth a planner's time, and neither was
 * before: the map has to distinguish land that a sorter would fix from land that no
 * amount of capital would fix, and the tool has to actually SITE the sorter rather than
 * flag the gap and stop. The first is the status colouring below; the second is the
 * optimise button, which runs a capacitated facility location solve over 18,000 real
 * commune demand points and roughly 2,000 candidate silo sites.
 */

const STATUS = {
  viable: {
    colour: '#16a34a',
    label: 'Viable',
    blurb: 'A pulse pays at the sorter distance this land actually has.',
  },
  stranded: {
    colour: '#e11d48',
    label: 'Stranded potential',
    blurb:
      'Loses money at the distance it has, but would pay with a sorter in range. The only category a capital grant can fix.',
  },
  uneconomic: {
    colour: '#94a3b8',
    label: 'Uneconomic',
    blurb:
      'Loses money even with a sorter next door. The limit is agronomy or market, not infrastructure.',
  },
  at_or_above_target: {
    colour: '#0e7490',
    label: 'At or above target',
    blurb: 'Already at or past the 8% pulse share.',
  },
  unmodelled: {
    colour: '#e2e8f0',
    label: 'Not modelled',
    blurb: 'No viable pulse profile for this department.',
  },
}

/* 18,000 circle markers is more than Leaflet will draw smoothly, and more detail than
 * a national view can show anyway. Thinning is by convertible hectares rather than at
 * random, so the communes that carry the decision survive the cull and the map stays an
 * honest picture of where the opportunity is rather than a uniform sample of France.
 *
 * The budget is PER STATUS, which it was not before, and that was a real defect rather
 * than a cosmetic one. A single budget over the combined pool means switching a layer
 * ON removes markers from the layers already drawn: the 18,157 communes split 6,387
 * viable / 6,775 uneconomic / 4,486 stranded, so enabling `uneconomic` let it take
 * 2,269 of the 4,500 slots and pushed the drawn viable communes from 2,626 down to
 * 1,294. Half the viable land appeared to vanish because a different layer was turned
 * on - which reads as the economics changing when only the drawing budget did. A
 * per-status budget makes each layer's picture independent of what else is visible.
 *
 * 2,000 per status is chosen so the default three layers draw about the 4,500 markers
 * the old shared budget did, keeping the national view as dense as it was. The budget
 * must NOT be a total divided by the number of active layers, however tempting: that
 * is the same bug in a different shape, because every layer would shrink as another is
 * switched on. A fixed per-status cap is what makes the layers independent. */
const PER_STATUS_CAP = 2000

function thin(communes, cap) {
  if (communes.length <= cap) return communes
  const sorted = [...communes].sort((a, b) => b.convertible_ha - a.convertible_ha)
  return sorted.slice(0, cap)
}

function thinByStatus(communes, capEach) {
  const buckets = new Map()
  for (const c of communes) {
    const b = buckets.get(c.status)
    if (b) b.push(c)
    else buckets.set(c.status, [c])
  }
  return [...buckets.values()].flatMap((rows) => thin(rows, capEach))
}

function sorterIcon() {
  return L.divIcon({
    className: '',
    html:
      '<div style="width:14px;height:14px;border-radius:3px;background:#0f172a;' +
      'border:2px solid #fff;box-shadow:0 0 0 1px #0f172a"></div>',
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  })
}

function newSiteIcon(rank) {
  return L.divIcon({
    className: '',
    html:
      '<div style="width:22px;height:22px;border-radius:50%;background:#7c3aed;' +
      'border:3px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);color:#fff;' +
      'font:700 11px/16px system-ui;text-align:center;padding-top:1px">' +
      rank +
      '</div>',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  })
}

export default function RegionView() {
  const [overview, setOverview] = useState(null)
  const [surface, setSurface] = useState(null)
  const [plan, setPlan] = useState(null)
  const [k, setK] = useState(3)
  const [scope, setScope] = useState('')
  const [verify, setVerify] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showStatuses, setShowStatuses] = useState({
    viable: true,
    stranded: true,
    uneconomic: false,
    at_or_above_target: true,
    unmodelled: false,
  })

  useEffect(() => {
    api.regional().then(setOverview).catch((e) => setError(e.message))
    api
      .strandedSurface()
      .then(setSurface)
      .catch((e) => setError(e.message))
  }, [])

  const optimise = async () => {
    setBusy(true)
    setError(null)
    try {
      const body = { k, verify_milp: verify }
      if (scope) {
        // The scope selector works in department codes; a region scope is expressed
        // through the department list the overview already carries.
        body.department_code = scope
      }
      setPlan(await api.optimiseSorters(body))
    } catch (e) {
      setError(e.message)
      setPlan(null)
    } finally {
      setBusy(false)
    }
  }

  if (error && !overview) {
    return (
      <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
        {error}
      </div>
    )
  }
  if (!overview) {
    return <div className="text-sm text-slate-500">Loading the regional surface...</div>
  }

  const t = overview.surface_totals ?? {}
  const band = overview.stranded_band?.low ? overview.stranded_band : null
  const counts = (surface?.communes ?? []).reduce((a, c) => {
    a[c.status] = (a[c.status] ?? 0) + 1
    return a
  }, {})
  const selected = (surface?.communes ?? []).filter((c) => showStatuses[c.status])
  const visible = thinByStatus(selected, PER_STATUS_CAP)
  const impact = plan?.impact
  const mv = plan?.optimisation?.milp_verification

  return (
    <div className="space-y-4">
      {/* --- headline counters ------------------------------------------------ */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          [
            'Pulse share now',
            `${overview.national_current_share_pct}%`,
            `target ${overview.national_target_share_pct}% by ${overview.target_year}`,
            'neutral',
          ],
          [
            'Stranded land',
            // A range, because the driver is a published haulage band and the midpoint
            // alone is false precision. See the note under the table.
            band
              ? `${eur(band.low.stranded_ha / 1000, 0)}–${eur(band.high.stranded_ha / 1000, 0)}k ha`
              : `${eur(t.stranded_ha)} ha`,
            band
              ? `${eur(t.stranded_ha)} ha central · ${eur(t.stranded_communes)} communes a sorter would make profitable`
              : `${eur(t.stranded_communes)} communes a sorter would make profitable`,
            'bad',
          ],
          [
            'Already viable',
            `${eur(t.viable_ha)} ha`,
            `${eur(t.viable_communes)} communes profitable where they stand`,
            'good',
          ],
          [
            'Value of unsticking it',
            band
              ? `${eur(band.low.stranded_value_eur / 1e6, 1)}–${eur(band.high.stranded_value_eur / 1e6, 1)} M EUR`
              : `${eur((t.stranded_value_eur ?? 0) / 1e6, 1)} M EUR`,
            'three-year margin currently lost to haulage',
            'warn',
          ],
          [
            'Existing sorters',
            `${t.existing_units ?? 0}`,
            `across ${overview.departments.length} departments`,
            'neutral',
          ],
        ].map(([l, v, s, tone]) => (
          <div
            key={l}
            className={`rounded-lg border p-3 ${
              tone === 'bad'
                ? 'border-rose-200 bg-rose-50'
                : tone === 'good'
                  ? 'border-emerald-200 bg-emerald-50'
                  : tone === 'warn'
                    ? 'border-amber-200 bg-amber-50'
                    : 'border-slate-200 bg-slate-50'
            }`}
          >
            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
              {l}
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{v}</div>
            <div className="mt-0.5 text-xs text-slate-500">{s}</div>
          </div>
        ))}
      </div>

      {/* --- optimiser controls ---------------------------------------------- */}
      <div className="rounded-lg border-2 border-violet-300 bg-violet-50/50 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs font-medium text-slate-600">
            New optical sorters
            <input
              type="number"
              min="1"
              max="26"
              value={k}
              onChange={(e) => setK(Math.max(1, Math.min(26, Number(e.target.value) || 1)))}
              className="mt-1 w-20 rounded border border-slate-300 px-2 py-1.5 text-sm"
            />
          </label>
          <label className="text-xs font-medium text-slate-600">
            Scope
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm sm:w-56"
            >
              <option value="">Whole modelled territory</option>
              {overview.departments
                .slice()
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((d) => (
                  <option key={d.department_code} value={d.department_code}>
                    {d.department_code} - {d.name}
                  </option>
                ))}
            </select>
          </label>
          <label className="flex items-center gap-2 pb-2 text-xs text-slate-700">
            <input
              type="checkbox"
              checked={verify}
              onChange={(e) => setVerify(e.target.checked)}
            />
            Verify against the exact optimum (slower)
          </label>
          <button
            onClick={optimise}
            disabled={busy}
            className="w-full rounded bg-violet-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-600 disabled:opacity-50 sm:w-auto"
          >
            {busy
              ? 'Optimising...'
              : `Optimise placement (${eur(450000 * k / 1000)}k EUR capex)`}
          </button>
        </div>
        <p className="mt-2 text-[11px] text-slate-600">
          Capacitated facility location over{' '}
          {eur(surface?.n_total ?? 0)} real commune demand points. The objective is
          convertible hectares weighted by the improvement in three-year margin from
          being served by a nearer sorter; the algorithm is greedy marginal gain, which
          is within a factor (1 &minus; 1/e) = 0.632 of the optimum because that
          objective is monotone submodular (Nemhauser, Wolsey &amp; Fisher 1978).
        </p>
      </div>

      {error && (
        <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
        </div>
      )}

      {/* --- live impact ------------------------------------------------------ */}
      {impact && (
        <div className="rounded-lg border-2 border-violet-400 bg-white p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-800">
              What {plan.k_sited} new unit{plan.k_sited > 1 ? 's' : ''} unlock
            </h3>
            <span className="text-[11px] text-slate-500">
              {eur(plan.candidate_sites_considered)} candidate sites &middot;{' '}
              {eur(plan.pairs_evaluated)} site-commune pairs &middot; {plan.compute_ms} ms
            </span>
          </div>

          <div className="mt-2 grid grid-cols-2 gap-3 lg:grid-cols-5">
            {[
              ['Hectares unlocked', `${eur(impact.hectares_unlocked)} ha`],
              ['Food-grade tonnes', `${eur(impact.tonnes_unlocked)} t`],
              ['CO2e avoided', `${eur(impact.co2e_saved_tons)} t`],
              [
                'Pulse share',
                `${impact.pulse_share_before_pct}% to ${impact.pulse_share_after_pct}%`,
              ],
              [
                'Margin per EUR capex',
                `${eur(impact.value_per_euro_capex, 2)} EUR`,
              ],
            ].map(([l, v]) => (
              <div key={l} className="rounded border border-violet-200 bg-violet-50 p-2">
                <div className="text-[11px] uppercase text-slate-500">{l}</div>
                <div className="mt-0.5 text-xl font-semibold tabular-nums text-violet-900">
                  {v}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-300 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-1.5 pr-2">#</th>
                  <th className="py-1.5 pr-2">Site</th>
                  <th className="py-1.5 pr-2 text-right">ha unlocked</th>
                  <th className="py-1.5 pr-2 text-right">t/yr</th>
                  <th className="py-1.5 pr-2 text-right">Utilisation</th>
                  <th className="py-1.5 pr-2 text-right">Levelised cost</th>
                  <th className="py-1.5 text-right">Communes</th>
                </tr>
              </thead>
              <tbody>
                {plan.sites.map((s) => (
                  <tr key={s.rank} className="border-b border-slate-100">
                    <td className="py-1.5 pr-2 font-semibold text-violet-800">{s.rank}</td>
                    <td className="py-1.5 pr-2">
                      <div className="font-medium text-slate-800">{s.commune}</div>
                      <div className="text-[10px] text-slate-500">
                        dept {s.dept} &middot; pop {eur(s.population)}
                      </div>
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {eur(s.hectares_unlocked)}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {eur(s.tonnes_unlocked)}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {s.unit_economics.utilisation_pct}%
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {eur(s.unit_economics.levelised_cost_eur_t, 2)} EUR/t
                    </td>
                    <td className="py-1.5 text-right tabular-nums">
                      {s.communes_served}
                      {s.communes_capacity_limited > 0 && (
                        <span
                          className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-900"
                          title="Communes the unit could only part-serve before hitting its throughput cap."
                        >
                          {s.communes_capacity_limited} capped
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-slate-600">
            <span>
              Capex {eur(plan.capex_eur)} EUR &middot;{' '}
              {plan.share_of_regional_envelope_pct}% of an 11.7 M EUR regional envelope
            </span>
            {mv?.solved ? (
              <span className="font-medium text-emerald-800">
                Greedy reached {pct(mv.greedy_share_of_optimum, 2)} of the exact HiGHS
                optimum, against a 63.2% worst-case guarantee.
              </span>
            ) : (
              <span className="italic">
                Exact verification not run. Tick the box above to solve the same problem
                with HiGHS and see the gap.
              </span>
            )}
          </div>
          {plan.units_for_target?.central && (
            <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-2.5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-amber-900">
                And what reaching the target actually takes
              </div>
              <div className="mt-1 grid gap-2 sm:grid-cols-3">
                {['low', 'central', 'high'].map((k) => {
                  const u = plan.units_for_target[k]
                  return (
                    <div key={k} className="rounded bg-white p-2">
                      <div className="text-[10px] uppercase text-slate-500">
                        {eur(u.capacity_t_yr)} t/yr per line
                      </div>
                      <div className="mt-0.5 text-lg font-semibold tabular-nums text-amber-900">
                        {u.units_required} units
                      </div>
                      <div className="text-[11px] text-slate-600">
                        {eur(u.hectares_per_unit)} ha each &middot; &euro;
                        {eur(u.capex_eur / 1e6)}M
                      </div>
                    </div>
                  )
                })}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-700">
                {plan.units_for_target.note}
              </p>
            </div>
          )}

          <p className="mt-1.5 text-[11px] italic text-slate-500">
            Each unit is loaded only to its throughput cap, and hectares are
            reported after that cap. Levelised cost is capex at a 4% discount over 12
            years plus opex, divided by throughput; below the 38 EUR/t toll fee charged
            on food tonnage the unit services its own capital.
          </p>
        </div>
      )}

      {/* --- map -------------------------------------------------------------- */}
      <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-3 text-xs">
            {/* Only statuses that actually occur. "At or above target" has zero
                members on the current data, and a legend entry for an empty category
                invites a question with no interesting answer. */}
            {Object.entries(STATUS)
              .filter(([key]) => (surface?.totals ? counts[key] > 0 : true))
              .map(([key, v]) => (
              <label key={key} className="flex items-center gap-1.5" title={v.blurb}>
                <input
                  type="checkbox"
                  checked={showStatuses[key]}
                  onChange={(e) =>
                    setShowStatuses((s) => ({ ...s, [key]: e.target.checked }))
                  }
                />
                <span
                  className="inline-block h-3 w-3 rounded-full"
                  style={{ background: v.colour }}
                />
                {v.label}
              </label>
            ))}
          </div>

          {/* Stated rather than silent: a reader comparing marker counts between two
              toggle states needs to know a per-layer drawing cap is in play, and which
              layers it is currently biting on. */}
          <div className="mb-2 text-[11px] text-slate-500">
            Drawing {eur(visible.length)} of {eur(selected.length)} selected communes
            {visible.length < selected.length && (
              <>
                {' '}&middot; capped at {eur(PER_STATUS_CAP)} per status, largest
                convertible area first
              </>
            )}
          </div>

          {/* h-[55vh] on a phone so the page can still be scrolled past the map,
              a fixed 560 px from lg: upward where there is room for it. */}
          <div className="h-[55vh] max-h-[560px] overflow-hidden rounded-lg border border-slate-300 lg:h-[560px]">
            <MapContainer center={[46.9, 2.4]} zoom={6} scrollWheelZoom preferCanvas>
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <LayerGroup>
                {visible.map((c) => (
                  <CircleMarker
                    key={c.insee}
                    center={[c.lat, c.lon]}
                    radius={Math.max(2.5, Math.min(7, Math.sqrt(c.convertible_ha) / 9))}
                    pathOptions={{
                      color: STATUS[c.status]?.colour ?? '#94a3b8',
                      fillColor: STATUS[c.status]?.colour ?? '#94a3b8',
                      fillOpacity: 0.6,
                      weight: 0.6,
                    }}
                  >
                    <LTooltip>
                      <div className="text-xs">
                        <div className="font-semibold">
                          {c.name} ({c.dept})
                        </div>
                        <div>{STATUS[c.status]?.label}</div>
                        <div>
                          {eur(c.convertible_ha)} ha convertible &middot;{' '}
                          {/* "best fit" only when something actually fits; otherwise
                              this is the least-bad of six losing options and must not
                              read as a recommendation. */}
                          {c.delta_eur_ha_if_served >= 0 ? 'best fit ' : 'least-bad '}
                          {c.best_pulse}
                        </div>
                        <div>
                          {eur(c.delta_eur_ha)} EUR/ha now, {eur(c.delta_eur_ha_if_served)}{' '}
                          EUR/ha if served
                        </div>
                        <div>
                          Sorter {c.sorter_road_km == null ? '-' : `${c.sorter_road_km} km`}
                          {c.within_range ? '' : ' (out of range)'}
                        </div>
                      </div>
                    </LTooltip>
                  </CircleMarker>
                ))}
              </LayerGroup>

              {(surface?.existing_sorting_units ?? []).map((u) => (
                <Marker
                  key={u.name}
                  position={[u.location[1], u.location[0]]}
                  icon={sorterIcon()}
                >
                  <LTooltip>
                    <div className="text-xs">
                      <div className="font-semibold">{u.name}</div>
                      <div>Existing unit &middot; {eur(u.capacity_t_yr)} t/yr</div>
                    </div>
                  </LTooltip>
                </Marker>
              ))}

              {(plan?.sites ?? []).map((s) => (
                <Marker key={s.insee} position={[s.lat, s.lon]} icon={newSiteIcon(s.rank)}>
                  <LTooltip>
                    <div className="text-xs">
                      <div className="font-semibold">
                        Proposed unit {s.rank}: {s.commune}
                      </div>
                      <div>
                        {eur(s.hectares_unlocked)} ha &middot; {eur(s.tonnes_unlocked)} t/yr
                      </div>
                      <div>{s.communes_served} communes served</div>
                    </div>
                  </LTooltip>
                </Marker>
              ))}
            </MapContainer>
          </div>
          <p className="mt-1.5 text-[11px] italic text-slate-500">
            Dark squares are the optical sorting units already in the ground; purple
            circles are the optimiser's proposals. Dot size is convertible hectares. The
            national view draws the {eur(4500)} highest-opportunity communes of{' '}
            {eur(surface?.n_total ?? 0)} &mdash; thinned by hectares rather than at
            random, so the land that carries the decision is the land you see. A
            department's arable area is split between its communes in proportion to
            cadastral area, because nothing is published at commune level to measure
            that split against; the error averages out over the hundreds of communes
            inside a haulage radius but is visible commune by commune.
            {band && (
              <>
                {' '}
                <span className="font-semibold not-italic">
                  Stranded land is quoted as a range on purpose:
                </span>{' '}
                it is driven by the haulage rate, which is a published band of
                &euro;{band.low.eur_per_tonne_km}&ndash;{band.high.eur_per_tonne_km}/t/km
                rather than a measured constant. Across that band the figure runs{' '}
                {eur(band.low.stranded_ha)}&ndash;{eur(band.high.stranded_ha)} ha. The
                map colours by the central value because a map needs one colour per
                commune.
              </>
            )}
          </p>
        </div>

        {/* --- department table ----------------------------------------------- */}
        <div className="rounded-lg border border-slate-300 bg-white p-3">
          <h3 className="mb-1 text-sm font-semibold text-slate-800">
            Where the money buys the most, by department
          </h3>
          <p className="mb-2 text-[11px] text-slate-500">
            Sorted by conversion value. The column that decides whether capital helps is
            the last one: a department loss-making at the distance it has but profitable
            at the collection radius is infrastructure-limited. A{' '}
            <span className="rounded bg-slate-200 px-1 text-[9px] font-semibold uppercase">
              none pay
            </span>{' '}
            tag means every candidate loses money there &mdash; the crop named is the
            least-bad option, not a recommendation.
          </p>
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 border-b border-slate-300 bg-white text-left uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-2">Department</th>
                  <th className="py-2 pr-2 text-right">Share</th>
                  <th className="py-2 pr-2">Best / least-bad</th>
                  <th className="py-2 pr-2 text-right">EUR/ha</th>
                  <th className="py-2 pr-2 text-right">km</th>
                  <th className="py-2 pr-2 text-right">Haul</th>
                  <th className="py-2 text-right">Limit</th>
                </tr>
              </thead>
              <tbody>
                {overview.departments.map((d) => (
                  <tr key={d.department_code} className="border-b border-slate-100">
                    <td className="py-1.5 pr-2">
                      <div className="font-medium text-slate-800">{d.name}</div>
                      <div className="text-[10px] text-slate-500">
                        {eur(d.stranded_communes)} stranded communes
                      </div>
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {d.pulse_share_pct}%
                    </td>
                    <td className="py-1.5 pr-2">
                      {d.best_pulse}
                      {d.any_candidate_profitable === false && (
                        <span
                          className="ml-1 rounded bg-slate-200 px-1 text-[9px] font-semibold uppercase text-slate-700"
                          title="Every candidate pulse loses money in this department at the sorter distance it actually has. This is the least-bad option, not a recommendation."
                        >
                          none pay
                        </span>
                      )}
                      {/* The margin to the right is a DIFFERENCE against the year-2
                          crop, and this tab has no crop selector - so naming the
                          comparator is the only way the number can be read. */}
                      {d.displaced_year2_crop && (
                        <div className="text-[10px] text-slate-500">
                          vs {d.displaced_year2_crop}
                          {d.baseline_rotation_caveat && (
                            <span
                              className="ml-1 cursor-help font-semibold text-amber-700"
                              title={d.baseline_rotation_caveat}
                            >
                              (?)
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td
                      className={`py-1.5 pr-2 text-right font-semibold tabular-nums ${
                        d.median_margin_gain_eur_ha >= 0 ? 'text-emerald-700' : 'text-rose-700'
                      }`}
                    >
                      {eur(d.median_margin_gain_eur_ha)}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {d.sorter_road_km == null ? '-' : eur(d.sorter_road_km)}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-slate-600">
                      {d.haulage_cost_eur_ha > 0 ? `-${eur(d.haulage_cost_eur_ha)}` : '0'}
                    </td>
                    <td className="py-1.5 text-right">
                      {d.is_infrastructure_limited ? (
                        <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-900">
                          sorting
                        </span>
                      ) : d.median_margin_gain_eur_ha >= 0 ? (
                        <span className="text-[10px] text-emerald-700">none</span>
                      ) : (
                        <span className="text-[10px] text-slate-500">economics</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {overview.provenance && (
        <p className="text-[11px] italic text-slate-500">
          {overview.provenance.source} {overview.provenance.caveat}
        </p>
      )}
    </div>
  )
}
