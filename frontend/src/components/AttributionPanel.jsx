import {
  Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from 'recharts'
import { CROP_COLOUR, CROP_LABEL, INK } from '../lib/landPalette.js'

/* What explains the shift, and what this project cannot explain.
 *
 * This panel reports a null result, so the design job is to make the null legible
 * rather than to dress it up. Three rules follow from that:
 *
 * 1. The composition bar shows only the components that explain something - the
 *    national year effect, the persistent department effect, and the residual. The
 *    weather contribution is stated in words next to it, because its cross-fitted
 *    value is NEGATIVE for four of five crops and "weather explains -84.9% of the
 *    variance" is arithmetically correct and rhetorically useless.
 * 2. The residual wears a neutral grey, not a fifth hue. It is not an identity, it
 *    is the absence of one, and it is always directly labelled with its percentage
 *    so the grey never has to carry the number on its own.
 * 3. The held-out table shows the baseline next to the model. A skill number alone
 *    invites the reader to assume the baseline was beaten.
 *
 * The two identified-effect colours were validated as a categorical pair: all-pairs
 * CVD separation dE 30.2 (protan) and 21.8 (tritan), normal-vision dE 34.0, both
 * above 3:1 contrast on the light surface.
 */

const EFFECT = {
  national_year_effect: { colour: '#1d4ed8', label: 'National year effect' },
  department_effect: { colour: '#a16207', label: 'Persistent department effect' },
  unexplained: { colour: '#64748b', label: 'Unexplained' },
}

function DecompositionChart({ rows }) {
  const data = rows
    .filter((r) => r.variance_explained_increment_pct)
    .map((r) => {
      const inc = r.variance_explained_increment_pct
      // The two fixed effects are a nested partition and sum to at most 100. The
      // residual is taken as the remainder after them, not as the reported
      // "unexplained" field, which also carries the negative weather increment and
      // would push the bar past 100% of its own width.
      const year = Math.max(inc.national_year_effect, 0)
      const dept = Math.max(inc.department_effect, 0)
      return {
        crop: r.crop,
        name: CROP_LABEL[r.crop] || r.crop,
        national_year_effect: year,
        department_effect: dept,
        unexplained: Math.max(100 - year - dept, 0),
        weather: r.weather_contribution,
        n: r.n,
      }
    })

  return (
    <div style={{ height: 40 + data.length * 44 }}>
      <ResponsiveContainer>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 12, bottom: 4, left: 4 }}
          barCategoryGap="28%"
        >
          <CartesianGrid horizontal={false} stroke={INK.grid} strokeDasharray="3 3" />
          <XAxis
            type="number" domain={[0, 100]} unit="%"
            tick={{ fontSize: 11, fill: INK.muted }}
          />
          <YAxis
            type="category" dataKey="name" width={96}
            tick={{ fontSize: 11, fill: INK.secondary }}
          />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(v, n) => [`${v.toFixed(1)}% of variance`, EFFECT[n]?.label || n]}
          />
          {Object.keys(EFFECT).map((k) => (
            <Bar
              key={k} dataKey={k} stackId="a" name={k}
              fill={EFFECT[k].colour} isAnimationActive={false}
              // 2px surface gap between stacked segments.
              stroke="#ffffff" strokeWidth={2}
              radius={k === 'unexplained' ? [0, 4, 4, 0] : 0}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function EnvelopeChart({ envelope }) {
  if (!envelope?.contrasts?.length) return null
  const data = envelope.contrasts
    .slice(0, 6)
    .map((c) => ({
      variable: c.variable.replace(/_lag1$/, '').replace(/_/g, ' '),
      d: c.standardised_difference,
      expanded: c.mean_where_expanded,
      contracted: c.mean_where_contracted,
    }))
    .reverse()
  const bound = Math.max(...data.map((d) => Math.abs(d.d)), 0.1)
  return (
    <div style={{ height: 30 + data.length * 26 }}>
      <ResponsiveContainer>
        <BarChart
          data={data} layout="vertical"
          margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
        >
          <CartesianGrid horizontal={false} stroke={INK.grid} strokeDasharray="3 3" />
          <XAxis
            type="number" domain={[-bound * 1.15, bound * 1.15]}
            tick={{ fontSize: 10, fill: INK.muted }}
          />
          <YAxis
            type="category" dataKey="variable" width={150}
            tick={{ fontSize: 10, fill: INK.secondary }}
          />
          <ReferenceLine x={0} stroke={INK.secondary} strokeWidth={1} />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(v, n, p) => [
              `${v > 0 ? '+' : ''}${v.toFixed(2)} SD  (expanded ${p.payload.expanded}, contracted ${p.payload.contracted})`,
              'standardised difference',
            ]}
          />
          <Bar dataKey="d" isAnimationActive={false} radius={[0, 3, 3, 0]}>
            {data.map((d, i) => (
              // Diverging poles from the validated PuOr pair, not red/green.
              <Cell key={i} fill={d.d >= 0 ? '#542788' : '#b35806'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function AttributionPanel({ attribution, crop }) {
  if (!attribution) return null
  const v = attribution.verdict || {}
  const dec = attribution.decomposition || []
  const held = attribution.held_out_prediction || []
  const env = (attribution.weather_envelope || []).find((e) => e.crop === crop)
  const resp = (attribution.yield_response_to_water || []).find((e) => e.crop === crop)
  const cov = attribution.coverage || {}

  return (
    <div className="space-y-3">
      <div className="rounded border border-amber-300 bg-amber-50 p-3">
        <div className="text-sm font-semibold text-amber-900">
          The shift is not weather-driven, and the likely cause is not in this dataset
        </div>
        <p className="mt-1 text-[13px] leading-relaxed text-amber-900">{v.plain_language}</p>
        <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-amber-900">
          <span>
            national year effect, median across crops:{' '}
            <b>{v.national_year_effect_pct_median}%</b>
          </span>
          <span>
            weather adds nothing for <b>{v.crops_where_weather_adds_nothing}</b> crops
          </span>
          <span>
            held-out skill vs assuming no change, median:{' '}
            <b>{v.held_out_skill_vs_no_change_pct_median}%</b>
          </span>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded border border-slate-300 bg-white p-3">
          <div className="text-sm font-semibold text-slate-800">
            What explains year-on-year change in a department&apos;s pulse share
          </div>
          <div className="mb-2 text-xs text-slate-500">
            Nested variance decomposition. {cov.attribution_departments} departments,{' '}
            {cov.years?.[0]}-{cov.years?.[1]}.
          </div>
          <DecompositionChart rows={dec} />
          <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-600">
            {Object.entries(EFFECT).map(([k, e]) => (
              <span key={k} className="flex items-center gap-1">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ background: e.colour }}
                />
                {e.label}
              </span>
            ))}
          </div>
          <div className="-mx-1 overflow-x-auto px-1"><table className="mt-2 w-full text-[11px]">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-1">Crop</th>
                <th>Weather &amp; soil, cross-fitted</th>
                <th>In-sample, if not cross-fitted</th>
                <th className="text-right">n</th>
              </tr>
            </thead>
            <tbody>
              {dec.filter((r) => r.weather_stage_overfit_check_pct).map((r) => (
                <tr key={r.crop} className="border-t border-slate-200">
                  <td className="py-1 text-slate-700">{CROP_LABEL[r.crop] || r.crop}</td>
                  <td className="font-medium text-slate-800">{r.weather_contribution}</td>
                  <td className="text-slate-500">
                    {r.weather_stage_overfit_check_pct.in_sample}%
                  </td>
                  <td className="text-right text-slate-500">{r.n}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            The right-hand column is what a naive fit would have claimed. The gap
            between the two columns is overfitting, not signal: twelve weather columns
            and a boosted-tree learner on {dec[0]?.n} rows will fit almost any
            residual. Folds are grouped by year so one growing season never appears on
            both sides of the split.
          </p>
        </div>

        <div className="space-y-3">
          <div className="rounded border border-slate-300 bg-white p-3">
            <div className="text-sm font-semibold text-slate-800">
              Held out: can last season&apos;s weather predict next season&apos;s planting?
            </div>
            <div className="mb-2 text-xs text-slate-500">
              Fit to {held[0]?.n_train} observations before {held[0]?.test_years?.[0]},
              tested on {held[0]?.n_test} after. Lower error is better.
            </div>
            <div className="-mx-1 overflow-x-auto px-1"><table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="py-1">Crop</th>
                  <th className="text-right">Model error</th>
                  <th className="text-right">No-change error</th>
                  <th className="text-right">Skill</th>
                  <th className="text-right">Direction</th>
                </tr>
              </thead>
              <tbody>
                {held.filter((r) => r.mae_pp_model != null).map((r) => (
                  <tr key={r.crop} className="border-t border-slate-200">
                    <td className="py-1 text-slate-700">{CROP_LABEL[r.crop] || r.crop}</td>
                    <td className="text-right text-slate-800">{r.mae_pp_model}</td>
                    <td className="text-right text-slate-600">
                      {r.mae_pp_no_change_baseline}
                    </td>
                    <td
                      className={`text-right font-medium ${
                        r.skill_vs_no_change_pct > 0 ? 'text-slate-800' : 'text-rose-700'
                      }`}
                    >
                      {r.skill_vs_no_change_pct}%
                    </td>
                    <td className="text-right text-slate-600">
                      {r.direction_accuracy} <span className="text-slate-400">
                        / {r.direction_base_rate}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table></div>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
              Error is mean absolute error in percentage points of area share. A
              negative skill means the model is worse than assuming the share does not
              move. &quot;Direction&quot; is the share of test cases whose sign it got
              right, against the base rate you would get by always guessing the more
              common direction.
            </p>
          </div>

          <div className="rounded border border-slate-300 bg-white p-3">
            <div className="text-sm font-semibold text-slate-800">
              What this project cannot observe
            </div>
            <ul className="mt-1 space-y-1 text-[11px] leading-relaxed text-slate-600">
              {(attribution.unobserved_drivers || []).map((d, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-slate-400">&bull;</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded border border-slate-300 bg-white p-3">
          <div className="text-sm font-semibold text-slate-800">
            {CROP_LABEL[crop]}: last season&apos;s weather where the crop expanded vs
            contracted
          </div>
          <div className="mb-2 text-xs text-slate-500">
            Standardised difference in each variable between department-years where the
            share rose and where it fell. Association, not mechanism.
          </div>
          <EnvelopeChart envelope={env} />
          <p className="text-[11px] leading-relaxed text-slate-500">
            Purple means the variable was higher where the crop expanded. These
            contrasts are descriptive: region correlates with climate, and the same
            unobserved price and policy shock varies by region, so a difference here is
            not evidence that the weather caused the planting decision. The held-out
            test above is the one that tried, and failed, to make that claim.
          </p>
        </div>

        <div className="rounded border border-slate-300 bg-white p-3">
          <div className="text-sm font-semibold text-slate-800">
            {CROP_LABEL[crop]}: observed yield response to flowering water balance
          </div>
          <div className="mb-2 text-xs text-slate-500">
            Where weather does bite. Quintile bins of May-June rainfall minus reference
            evapotranspiration, from {resp?.n_observations} department-year observations.
            Crop mean {resp?.crop_mean_yield_t_ha} t/ha.
          </div>
          {resp?.bins?.length ? (
            <div style={{ height: 210 }}>
              <ResponsiveContainer>
                <BarChart
                  data={resp.bins.map((b) => ({
                    band: `${Math.round(b.water_balance_mm_from)} to ${Math.round(b.water_balance_mm_to)}`,
                    yield: b.mean_yield_t_ha,
                    n: b.n,
                  }))}
                  margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
                >
                  <CartesianGrid vertical={false} stroke={INK.grid} strokeDasharray="3 3" />
                  <XAxis dataKey="band" tick={{ fontSize: 10, fill: INK.muted }} />
                  <YAxis tick={{ fontSize: 10, fill: INK.muted }} width={38} />
                  <Tooltip
                    contentStyle={{ fontSize: 12 }}
                    formatter={(val, n, p) => [`${val} t/ha from ${p.payload.n} observations`, 'Mean yield']}
                    labelFormatter={(l) => `Water balance ${l} mm`}
                  />
                  <Bar
                    dataKey="yield" fill={CROP_COLOUR[crop]} isAnimationActive={false}
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="text-xs text-slate-500">Not enough observations for this crop.</div>
          )}
          <p className="text-[11px] leading-relaxed text-slate-500">
            This is a yield response, not an area response. Weather clearly moves how
            much a planted hectare produces; the panels above are about whether it
            moves how many hectares get planted, and it does not.
          </p>
        </div>
      </div>
    </div>
  )
}
