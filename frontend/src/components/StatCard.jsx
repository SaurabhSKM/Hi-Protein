export default function StatCard({ label, value, sub, tone = 'neutral', hint }) {
  const tones = {
    good: 'bg-emerald-50 border-emerald-200 text-emerald-900',
    bad: 'bg-rose-50 border-rose-200 text-rose-900',
    warn: 'bg-amber-50 border-amber-200 text-amber-900',
    neutral: 'bg-slate-50 border-slate-200 text-slate-900',
  }
  return (
    <div className={`rounded-lg border p-3 ${tones[tone]}`} title={hint}>
      <div className="text-[11px] font-medium uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs opacity-75">{sub}</div>}
    </div>
  )
}
