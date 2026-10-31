import Provenance from './Provenance.jsx'

export default function AgroPanel({ v }) {
  if (!v) return null
  const tone =
    v.severity === 'blocked'
      ? 'border-rose-300 bg-rose-50'
      : v.severity === 'caution'
        ? 'border-amber-300 bg-amber-50'
        : 'border-emerald-300 bg-emerald-50'
  return (
    <div className={`rounded-lg border p-3 ${tone}`}>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Agronomic screening</h3>
        <span className="text-xs font-medium uppercase tracking-wide text-slate-600">
          {v.severity}
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-700">{v.terres_inovia_note}</p>

      {v.blocking_reasons?.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm font-medium text-rose-800">
          {v.blocking_reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      {v.warnings?.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">
          {v.warnings.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-600 sm:grid-cols-4">
        <div><dt className="opacity-70">Return interval</dt><dd className="font-medium">{v.return_interval_years} yr</dd></div>
        <div><dt className="opacity-70">Observed gap</dt><dd className="font-medium">{v.observed_gap_years ?? 'no host'}</dd></div>
        <div><dt className="opacity-70">Disease group</dt><dd className="font-medium">{v.disease_group ?? '-'}</dd></div>
        <div><dt className="opacity-70">Preceding suitability</dt><dd className="font-medium">{v.preceding_crop_suitability ?? '-'}</dd></div>
      </dl>
      <Provenance p={v.provenance} />
    </div>
  )
}
