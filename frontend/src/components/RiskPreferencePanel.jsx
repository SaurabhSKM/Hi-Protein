import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { eur } from '../lib/api.js'

/* Applying a risk attitude, rather than only describing one.
 *
 * The engine has computed all of this since the first build and the API has always
 * returned it; nothing rendered it, so the most decision-useful number in the whole
 * response was invisible. `minimum_viable_contract` in particular answers the question
 * an advisor is actually asked across a kitchen table - "what price would make this
 * worth my while" - with a number rather than a distribution.
 */
export default function RiskPreferencePanel({ rp, cropLabel }) {
  if (!rp) return null

  const mvc = rp.minimum_viable_contract ?? {}
  const tol = rp.tolerance_threshold ?? {}
  const sharing = rp.risk_sharing ?? {}
  const curve = (rp.serf_curve ?? []).map((p) => ({
    rra: p.rra,
    advantage: p.ce_advantage_eur_ha,
    premium: p.switching_risk_premium_eur_ha,
    label: p.label,
  }))

  const verdictText = {
    always: 'Preferred at every risk attitude on the scale, including risk neutral.',
    never: 'Not preferred at any risk attitude on the scale, including risk neutral.',
  }[tol.verdict]

  return (
    <div className="rounded-lg border border-slate-300 bg-white p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">
          What price would make this worth doing
        </h3>
        <span className="text-[11px] text-slate-500">
          SERF, Hardaker et al. (2004) &middot; anchored on {eur(rp.wealth_anchor_eur_ha)} EUR/ha
        </span>
      </div>

      {mvc.headline && (
        <p className="mt-1 rounded bg-slate-50 p-2 text-sm font-medium text-slate-800">
          {mvc.headline}
        </p>
      )}

      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Contract terms that clear the bar
          </h4>
          <div className="-mx-1 overflow-x-auto px-1"><table className="mt-1 w-full text-sm">
            <thead className="border-b border-slate-200 text-left text-[11px] uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-2">Volume contracted</th>
                <th className="py-1 pr-2 text-right">Minimum price</th>
                <th className="py-1 text-right">Reachable</th>
              </tr>
            </thead>
            <tbody>
              {(mvc.terms ?? []).map((t) => (
                <tr key={t.volume_share} className="border-b border-slate-100">
                  <td className="py-1 pr-2 tabular-nums">
                    {(t.volume_share * 100).toFixed(0)}%
                  </td>
                  <td className="py-1 pr-2 text-right font-semibold tabular-nums">
                    {t.min_contract_price_eur_t == null
                      ? '-'
                      : `${eur(t.min_contract_price_eur_t)} EUR/t`}
                  </td>
                  <td className="py-1 text-right">
                    {t.feasible ? (
                      <span className="text-xs text-emerald-700">yes</span>
                    ) : (
                      <span className="text-xs text-rose-700">no</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <p className="mt-1.5 text-[11px] text-slate-500">
            {/* Why more volume lowers the price: it is the risk that is being paid for. */}
            Contracting more volume lowers the price needed, because what the premium
            buys is certainty, not revenue. Found by bisection on the price until the
            certainty equivalent of the DIFFERENCE between the two rotations reaches
            zero, repriced on the Monte Carlo draws already taken.
          </p>
          {mvc.price_sensitivity_full_volume_eur_t && (
            <p className="mt-1 text-[11px] text-slate-600">
              At full volume the required price runs from{' '}
              {eur(mvc.price_sensitivity_full_volume_eur_t.rra_0)} EUR/t for a
              risk-neutral farmer to{' '}
              {eur(mvc.price_sensitivity_full_volume_eur_t.rra_4)} EUR/t for a very
              risk-averse one &mdash; a spread of only{' '}
              {eur(
                mvc.price_sensitivity_full_volume_eur_t.rra_4 -
                  mvc.price_sensitivity_full_volume_eur_t.rra_0,
              )}{' '}
              EUR/t, so the answer is not very sensitive to guessing the attitude.
            </p>
          )}
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Does risk attitude change the verdict?
          </h4>
          <div className="mt-1 h-44">
            <ResponsiveContainer>
              <LineChart data={curve} margin={{ top: 6, right: 10, bottom: 18, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="rra"
                  tick={{ fontSize: 10 }}
                  label={{
                    value: 'relative risk aversion',
                    position: 'insideBottom',
                    offset: -12,
                    style: { fontSize: 10, fill: '#64748b' },
                  }}
                />
                <YAxis tick={{ fontSize: 10 }} width={52} />
                <Tooltip
                  formatter={(v, n) => [
                    `${eur(v)} EUR/ha`,
                    n === 'advantage' ? 'CE advantage of the pulse' : 'Switching premium',
                  ]}
                  labelFormatter={(v) => `RRA ${v}`}
                />
                <ReferenceLine y={0} stroke="#475569" />
                <Line
                  type="monotone"
                  dataKey="advantage"
                  stroke="#15803d"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="premium"
                  stroke="#b45309"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[11px] text-slate-600">
            Green is the certainty-equivalent advantage of the{' '}
            {cropLabel?.toLowerCase()} rotation; amber dashed is the premium a farmer
            would pay to avoid the extra risk of switching.{' '}
            {verdictText ??
              (tol.rra_threshold != null
                ? `The verdict flips at a relative risk aversion of ${tol.rra_threshold}.`
                : '')}
          </p>
          {sharing.finding && (
            <p className="mt-1.5 rounded bg-slate-50 p-2 text-[11px] text-slate-600">
              {sharing.finding} Correlation between the two rotations is{' '}
              {sharing.arm_correlation}, so only{' '}
              {(sharing.share_of_delta_variance_explained_by_arm_asymmetry * 100).toFixed(
                0,
              )}
              % of the variance of the decision comes from the arms differing in
              riskiness.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
