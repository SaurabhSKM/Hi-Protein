import { eur } from '../lib/api.js'

/* Distance to the nearest optical sorter, as a cost.
 *
 * Before this panel existed, being out of range only showed up as a quieter grading
 * probability - a quality story. It is really a cost story, and a continuous one, which
 * is what lets a parcel be agronomically ideal, pass food specification, and still lose
 * money. That is the "stranded potential" category the regional view is built on, so it
 * has to be legible on the farmer screen too.
 */
export default function SorterPanel({ s, areaHa }) {
  if (!s) return null

  const tone = s.is_stranded
    ? 'border-rose-400 bg-rose-50'
    : s.within_range
      ? 'border-slate-300 bg-white'
      : 'border-amber-400 bg-amber-50'

  return (
    <div className={`rounded-lg border-2 p-3 ${tone}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">
          Getting the crop to an optical sorter
        </h3>
        {s.is_stranded ? (
          <span className="rounded bg-rose-600 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">
            Stranded potential
          </span>
        ) : s.within_range ? (
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
            In range
          </span>
        ) : (
          <span
            className="rounded bg-amber-200 px-2 py-0.5 text-[11px] font-medium text-amber-900"
            title="Beyond the 80 km reference distance. What decides this parcel is the per-kilometre haulage cost below, which is continuous - the threshold itself only alters the grading penalty, and only for lentil, chickpea and fava bean."
          >
            Beyond {s.max_distance_km} km reference
          </span>
        )}
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div>
          <div className="text-[11px] uppercase text-slate-500">Nearest unit</div>
          <div className="font-medium text-slate-800">
            {s.nearest_unit_name ?? 'none on file'}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase text-slate-500">Road distance</div>
          <div className="font-semibold tabular-nums">
            {s.road_km == null ? '-' : `${eur(s.road_km, 1)} km`}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase text-slate-500">Haulage charged</div>
          <div className="font-semibold tabular-nums">
            {eur(s.haulage_eur_per_tonne_food, 2)} EUR/t food
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase text-slate-500">Cost to this parcel</div>
          <div
            className={`font-semibold tabular-nums ${
              s.haulage_cost_eur_ha_median > 0 ? 'text-rose-700' : 'text-slate-700'
            }`}
          >
            {eur(s.haulage_cost_eur_ha_median)} EUR/ha
          </div>
        </div>
      </div>

      <p className="mt-2 text-xs text-slate-700">{s.stranded_note}</p>

      {/* Stated because the 80 km figure is the one the sector quotes and it is the
          weakest part of this panel: measured across the 40 modelled departments,
          moving it to 60 or 120 km changes nothing, because the grading penalty it
          gates applies only to the whole-seed crops and almost every department's
          best candidate is pea or soy. The cost above does the real work. */}
      <p className="mt-1 text-[11px] text-slate-500">
        The 80 km figure is a sector rule of thumb, shown for reference. It is not what
        drives this result: the continuous haulage cost above is. Each crop in fact has
        its own economic limit &mdash; a food premium of &euro;78/t pays for about
        200 km, &euro;565/t for far more &mdash; which is why the engine prices distance
        per crop instead of applying one national threshold.
      </p>

      <p className="mt-1.5 text-[11px] italic text-slate-500">
        {/* Both halves of the attribution rule, because either one alone would mislead. */}
        Only the haul beyond the ordinary {eur(s.max_distance_km === 80 ? 25 : 25)} km
        collection radius is charged &mdash; the first 25 km is already inside the
        operating cost both rotations carry, and charging it would penalise the pulse for
        a trip the cereal also makes. Charged on food-grade tonnes only, so a badly
        graded year hauls less and pays less. Distance is great-circle inflated by a 1.32
        road detour factor, not routed.
        {s.measured_from === 'department_centroid' && (
          <>
            {' '}
            Measured from the department centroid: click a parcel on the map to measure
            from the field itself, which can differ by tens of kilometres.
          </>
        )}
        {areaHa ? ` Whole parcel: ${eur(s.haulage_cost_eur_whole_parcel)} EUR over ${areaHa} ha.` : null}
      </p>
    </div>
  )
}
