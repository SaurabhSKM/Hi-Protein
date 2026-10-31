const MODES = {
  live_api: ['Live API', 'bg-emerald-100 text-emerald-800 border-emerald-300'],
  cached: ['Cached', 'bg-sky-100 text-sky-800 border-sky-300'],
  reference_table: ['Reference table', 'bg-indigo-100 text-indigo-800 border-indigo-300'],
  model_output: ['Model output', 'bg-violet-100 text-violet-800 border-violet-300'],
  assumption: ['Assumption', 'bg-amber-100 text-amber-900 border-amber-300'],
}

/* Every numeric block in the API carries provenance. Showing it is the point:
   a farmer deciding on 45 hectares should be able to see which figures are
   measurements, which are model output, and which are assumptions. */
export default function Provenance({ p, compact = false }) {
  if (!p) return null
  const [label, cls] = MODES[p.mode] ?? ['Unknown', 'bg-slate-100 text-slate-700 border-slate-300']
  return (
    <div className="mt-2 text-xs text-slate-600">
      <span className={`mr-2 inline-block rounded border px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>
        {label}
      </span>
      <span className="align-middle">{p.source}</span>
      {!compact && p.caveat && (
        <div className="mt-1 border-l-2 border-amber-300 pl-2 text-[11px] italic text-slate-500">
          {p.caveat}
        </div>
      )}
    </div>
  )
}
