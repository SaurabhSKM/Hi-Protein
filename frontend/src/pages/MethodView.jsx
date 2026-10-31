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
  const imp = Object.entries(report.feature_importance_top15 ?? {}).slice(0, 10)
    .map(([k, v]) => ({ name: k, v: +(v * 100).toFixed(2) }))

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
                <Bar dataKey="v" fill="#15803d" isAnimationActive={false}>
                  <LabelList dataKey="v" position="right" style={{ fontSize: 10 }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-slate-600">
            The phenological windows dominate: flowering water balance, June heat days and harvest
            rain outrank every crop or soil indicator. That is the hypothesis behind the feature
            engineering, and the held-out data supports it.
          </p>
        </div>

        <div className="rounded-lg border border-slate-300 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-800">Held-out error by crop</h3>
          <table className="mt-2 w-full text-sm">
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
          </table>
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
        <h3 className="text-sm font-semibold text-slate-800">Stated limitations</h3>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {(report.known_limitations ?? []).map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      </div>
    </div>
  )
}
