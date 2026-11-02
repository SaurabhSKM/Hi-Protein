import Provenance from './Provenance.jsx'
import { eur, pct } from '../lib/api.js'

/* The food outcome, given the lead position on purpose.

   Everything else in this app is upstream of the farm gate. This panel is the one
   that answers the actual question - of what this parcel grows, how much reaches a
   French plate - and it shows the two multiplications that get there rather than
   just their product, because a reader who sees only the result cannot tell a
   well-graded fava bean (little food demand) from a well-graded lentil (almost all
   food). */
export default function FoodOutcomePanel({ f, T, crop }) {
  if (!f) return null
  const bar = (label, value, tone) => (
    <div className="flex items-center gap-2">
      <div className="w-40 shrink-0 text-xs text-slate-600">{label}</div>
      <div className="h-3 flex-1 overflow-hidden rounded bg-slate-200">
        <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, value * 100)}%` }} />
      </div>
      <div className="w-12 shrink-0 text-right text-xs font-medium tabular-nums text-slate-700">
        {pct(value)}
      </div>
    </div>
  )

  const foodShareOfHarvest =
    f.harvest_tonnes_median > 0 ? f.food_grade_tonnes_median / f.harvest_tonnes_median : 0

  return (
    <div className="rounded-lg border-2 border-emerald-300 bg-emerald-50/50 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-emerald-900">{T.foodOutcome}</h3>
        <span className="text-xs text-emerald-800">{crop}</span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded border border-emerald-200 bg-white p-2.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {T.foodGradeTonnes}
          </div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums text-emerald-900">
            {eur(f.food_grade_tonnes_median, 1)} t
          </div>
          <div className="text-xs text-slate-500">
            {eur(f.food_grade_tonnes_q15, 1)} - {eur(f.food_grade_tonnes_q85, 1)} t &middot;{' '}
            {T.ofHarvest} {eur(f.harvest_tonnes_median, 1)} t
          </div>
        </div>

        <div className="rounded border border-emerald-200 bg-white p-2.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {T.peopleFed}
          </div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums text-emerald-900">
            {eur(f.people_fed_at_recommended_intake)}
          </div>
          <div className="text-xs text-slate-500">
            {T.peopleFedHint} &middot; {eur(f.people_fed_at_current_intake)} {T.atTodaysIntake}
          </div>
        </div>

        <div className="rounded border border-emerald-200 bg-white p-2.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {T.gradingPremium}
          </div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums text-slate-900">
            {eur(f.food_grade_price_premium_eur_t)} EUR/t
          </div>
          <div className="text-xs text-slate-500">{T.gradingPremiumHint}</div>
        </div>

        <div
          className="rounded border border-amber-200 bg-amber-50 p-2.5"
          title={T.valueAtRiskHint}
        >
          <div className="text-[11px] font-medium uppercase tracking-wide text-amber-800">
            {T.valueAtRisk}
          </div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums text-amber-900">
            {eur(f.value_at_risk_from_grading_eur_ha)} EUR/ha
          </div>
          <div className="text-xs text-amber-800/80">{T.valueAtRiskHint}</div>
        </div>
      </div>

      {/* The two multiplications, shown separately. Their product is the headline
          above; separating them is what makes it arguable. */}
      <div className="mt-3 space-y-1.5 rounded border border-emerald-200 bg-white p-2.5">
        {bar(T.humanGradeFraction, f.human_grade_fraction_median, 'bg-emerald-500')}
        {bar(T.foodMarketShare, f.food_market_share, 'bg-sky-500')}
        {bar(T.reachesPlates, foodShareOfHarvest, 'bg-emerald-700')}
        <div className="pt-1 text-[11px] text-slate-500">
          {T.foodSplitNote}{' '}
          <span className="font-medium text-slate-700">
            {eur(f.feed_fallback_tonnes_median, 1)} t {T.toFeed}
          </span>
          .
        </div>
      </div>

      {f.imported_pulse_displaced_tonnes > 0 && (
        <div className="mt-2 rounded border border-sky-200 bg-sky-50 p-2.5 text-xs text-sky-900">
          <span className="font-semibold">
            {eur(f.imported_pulse_displaced_tonnes, 1)} t
          </span>{' '}
          {T.importsDisplaced}
          {f.import_origin_displaced ? ` (${f.import_origin_displaced})` : ''}.{' '}
          {T.importsDisplacedNote}
        </div>
      )}

      {f.crop_food_note && (
        <div className="mt-2 text-[11px] italic text-slate-500">{f.crop_food_note}</div>
      )}
      <Provenance p={f.provenance} />
    </div>
  )
}
