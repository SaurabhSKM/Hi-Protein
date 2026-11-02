import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api.js'

export default function MethodView() {
  const [report, setReport] = useState(null)
  const [trend, setTrend] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.modelReport().then(setReport).catch((e) => setError(e.message))
    api.yieldTrend().then(setTrend).catch(() => {})
  }, [])

  if (error) {
    return <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>
  }
  if (!report) return <div className="text-sm text-slate-500">Loading model report...</div>

  const ce = report.calibration_effect
  const kindOf = (k) =>
    k.startsWith('crop_') ? 'crop' : k.startsWith('soil_') ? 'soil' : 'weather'
  const KIND_COLOUR = { weather: '#15803d', crop: '#7c3aed', soil: '#b45309' }
  const allImp = Object.entries(report.feature_importance_top15 ?? {})
  const imp = allImp
    .map(([k, v]) => ({ name: k, v: +(v * 100).toFixed(2), kind: kindOf(k) }))
    .sort((a, b) => b.v - a.v)
    .slice(0, 12)
  // Grouped share, because the individual bars mislead: seven crop dummies at 2.7%
  // each outweigh any single weather feature while meaning something quite different.
  const grouped = allImp.reduce((a, [k, v]) => {
    const g = kindOf(k)
    a[g] = (a[g] ?? 0) + v
    return a
  }, {})
  const groupTotal = Object.values(grouped).reduce((a, b) => a + b, 0) || 1

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-300 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-800">What the model is and how it was tested</h3>
        <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          <div><dt className="text-xs uppercase text-slate-500">Version</dt><dd>{report.model_version}</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Target</dt><dd>{report.target}</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Fit years</dt><dd>{report.splits.fit.join(' to ')} ({report.n_fit} rows)</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Calibration years</dt><dd>{report.splits.calibrate.join(' to ')} ({report.n_calib} rows)</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Test years</dt><dd>{report.splits.test.join(' to ')} ({report.n_test} rows)</dd></div>
          <div><dt className="text-xs uppercase text-slate-500">Labels</dt><dd>{report.data_sources.labels}</dd></div>
        </dl>
        <p className="mt-2 text-xs text-slate-600">{report.splits.rationale}</p>
      </div>

      <div className="rounded-lg border border-slate-300 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-800">
          Calibration: does a 70% interval really contain 70% of outcomes?
        </h3>
        <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ['Raw coverage', `${(ce.interval_coverage_raw * 100).toFixed(1)}%`, 'bg-rose-50 border-rose-200'],
            ['After conformal', `${(ce.interval_coverage_conformal * 100).toFixed(1)}%`, 'bg-emerald-50 border-emerald-200'],
            ['Target', `${(ce.interval_coverage_target * 100).toFixed(0)}%`, 'bg-slate-50 border-slate-200'],
            ['Median bias', `${ce.median_bias_raw} to ${ce.median_bias_conformal}`, 'bg-slate-50 border-slate-200'],
          ].map(([l, v, cls]) => (
            <div key={l} className={`rounded border p-2 ${cls}`}>
              <div className="text-[11px] uppercase text-slate-500">{l}</div>
              <div className="text-lg font-semibold tabular-nums">{v}</div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-600">{ce.interpretation}</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-300 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-800">What drives the prediction</h3>
          <div className="mt-2 h-72">
            <ResponsiveContainer>
              <BarChart data={imp} layout="vertical" margin={{ left: 120, right: 36 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={118} tick={{ fontSize: 10 }} />
                <Tooltip formatter={(v) => [`${v}% of gain`, 'Importance']} />
                <Bar dataKey="v" isAnimationActive={false}>
                  {imp.map((d, i) => (
                    <Cell key={i} fill={KIND_COLOUR[d.kind]} />
                  ))}
                  <LabelList dataKey="v" position="right" style={{ fontSize: 10 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
            {['weather', 'crop', 'soil'].map((k) => (
              <span key={k} className="flex items-center gap-1.5">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ background: KIND_COLOUR[k] }}
                />
                {k === 'weather' ? 'weather + rotation' : `${k} identity`}{' '}
                <span className="font-semibold tabular-nums">
                  {((grouped[k] ?? 0) / groupTotal * 100).toFixed(0)}%
                </span>
              </span>
            ))}
          </div>

          {/* Rewritten. The previous caption claimed "the phenological windows
              dominate: flowering water balance, June heat days and harvest rain
              outrank every crop or soil indicator." That was false against the chart
              printed beside it — soil_deep_loam is the single highest-gain feature and
              crop_rapeseed outranks summer rain — and a reader who checks finds the
              claim contradicted by our own figure. */}
          <p className="mt-1.5 text-xs text-slate-600">
            <span className="font-semibold">Why crop and soil names appear here at
            all.</span> The model does not predict yield, it predicts the{' '}
            <span className="italic">ratio</span> of yield to each
            department-and-crop&apos;s own historical mean. In the training years that
            ratio averages exactly 1.00 for every crop by construction, so a crop name
            carries <span className="italic">no</span> information about yield level.
            What it does is act as a <span className="font-semibold">gate</span>: a tree
            has to split on crop before it can learn that lentil answers May heat
            differently from wheat, and that quantile models must predict wider
            intervals for a volatile crop than a stable one (residual spread runs from
            0.03 for chickpea to 0.21 for fava bean). The giveaway is that the seven
            crop bars sit within half a point of each other &mdash; a predictor would
            separate, a gate does not.
          </p>
          <p className="mt-1 text-xs text-slate-600">
            So read the groups, not the bars. Weather and rotation carry the largest
            share; soil and crop identity are how the single pooled model expresses
            eight different weather responses. Out-of-sample level drift is a separate
            problem and is handled separately, by the per-crop conformal offsets below
            &mdash; green lentil needs the largest correction (&minus;0.25 median bias),
            which is also the crop whose ratio drifted most between the fit and test
            blocks.
          </p>
        </div>

        <div className="rounded-lg border border-slate-300 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-800">Held-out error by crop</h3>
          <div className="-mx-1 overflow-x-auto px-1"><table className="mt-2 w-full text-sm">
            <thead className="border-b border-slate-300 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1.5 pr-2">Crop</th>
                <th className="py-1.5 pr-2 text-right">n</th>
                <th className="py-1.5 pr-2 text-right">MAE t/ha</th>
                <th className="py-1.5 pr-2 text-right">MAE %</th>
                <th className="py-1.5 text-right">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {(report.per_crop_test_performance ?? []).map((r) => (
                <tr key={r.crop} className="border-b border-slate-100">
                  <td className="py-1.5 pr-2">{r.crop}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{r.n}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{r.mae_t_ha}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{r.mae_pct?.toFixed(1)}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {(r.coverage * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      </div>

      {trend && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
          <h3 className="text-sm font-semibold text-amber-900">
            The finding that cuts both ways
          </h3>
          <p className="mt-1 text-sm text-amber-900">{trend.finding}</p>
          <div className="mt-2 h-64">
            <ResponsiveContainer>
              <BarChart data={trend.crops} margin={{ top: 8, right: 8, bottom: 40, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e7d8b0" />
                <XAxis dataKey="crop" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={50} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v}%`} />
                <Tooltip formatter={(v) => [`${v}%`, 'Change in mean yield']} />
                <Bar dataKey="change_pct" isAnimationActive={false}>
                  {trend.crops.map((c, i) => (
                    <Cell key={i} fill={c.is_legume ? '#b45309' : '#64748b'} />
                  ))}
                  <LabelList dataKey="change_pct" position="top" style={{ fontSize: 10 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-amber-800">
            Amber bars are legumes, grey are cereals and rapeseed. Source: {trend.source}.
          </p>
        </div>
      )}

      <div className="rounded-lg border border-slate-300 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-800">
          Stated limitations &mdash; the yield model
        </h3>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {(report.known_limitations ?? []).map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      </div>

      {/* Kept as its own panel rather than folded into the model's list above,
          because these are limits of the REGIONAL engine - a different set of
          methods with a different failure mode, and the largest of them sits
          under the most visually persuasive screen in the product. */}
      <div className="rounded-lg border border-slate-300 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-800">
          Stated limitations &mdash; the regional engine
        </h3>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
          <li>
            <span className="font-medium">
              A department's arable hectares are split between its communes in
              proportion to cadastral area.
            </span>{' '}
            Agreste publishes nothing at commune level to measure that split against.
            It is right on average and wrong for any individual commune &mdash; one
            that is mostly forest is credited with arable land it does not have. The
            error averages out over the hundreds of communes inside an 80 km haulage
            radius, which is the scale a siting decision is made at, but it is visible
            at the scale the map is drawn at. This is the largest assumption behind the
            most persuasive screen in this product.
          </li>
          <li>
            <span className="font-medium">
              Candidate sites are communes above 2,000 people
            </span>
            , standing in for an inventory of cooperative silos, which is not open data.
            A cooperative deploying this would substitute its own site list; the
            optimiser would not otherwise change.
          </li>
          <li>
            <span className="font-medium">
              Distance is great-circle inflated by a 1.32 road detour factor, not
              routed.
            </span>{' '}
            Applied uniformly so it cannot flatter one candidate over another, but it
            understates haulage in hilly terrain.
          </li>
          <li>
            <span className="font-medium">
              The (1 &minus; 1/e) greedy guarantee covers the uncapacitated problem.
            </span>{' '}
            Throughput caps break submodularity and are applied afterwards as an
            allocation step, so the bound does not formally cover the post-capacity
            hectares reported. The exact HiGHS check runs on the same uncapacitated
            objective, and greedy has come within 0.3% of it on every scope tested.
          </li>
          <li>
            <span className="font-medium">
              Baked department profiles use one soil archetype and one baseline rotation
              per department.
            </span>{' '}
            They exist because 42 live Monte Carlos per request took over two minutes.
            Any real parcel should go through the farmer view with its own soil,
            rotation and RPG history.
          </li>
          <li>
            <span className="font-medium">
              The commune-level Aphanomyces constraint is an aggregate, not a parcel
              check.
            </span>{' '}
            With no commune-level rotation history, what is enforced is the steady-state
            ceiling: a pulse on a 5-year return interval cannot exceed a fifth of a
            rotation. That holds regardless of history, but it will clear individual
            fields a parcel-level check would block.
          </li>
          <li>
            <span className="font-medium">
              The livestock holding directory is illustrative on identity and real on
              geography.
            </span>{' '}
            Locations are real IGN commune centroids and the count per department is
            scaled by a measured land-use ratio, but names, herd types and herd sizes
            are generated with a fixed seed. No real farm is described.
          </li>
          <li>
            <span className="font-medium">
              The breeder fallback is a revenue floor, not downside insurance.
            </span>{' '}
            Measured rather than assumed: the loss tail is driven mostly by low yield,
            and a low-yield year has fewer tonnes to downgrade, so poor yield and poor
            grading nearly cancel in downgraded tonnage. The uplift is a near-flat
            ~&euro;46/ha. And for chickpea the commodity feed market already pays at or
            above ration value, so there is no contract worth signing at all.
          </li>
        </ul>
      </div>
    </div>
  )
}
