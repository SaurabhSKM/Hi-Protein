"""Risk preference, and the contract terms that would satisfy it.

The engine already MEASURES risk — `finance.summarise` returns the probability of
beating the baseline, a 5% conditional value at risk, and the probability of losing
more than EUR 100/ha. None of that APPLIES a risk preference, so the engine could
describe a distribution but never say which rotation a particular farmer should
prefer. Two farmers facing the same distribution, one with a tight loan covenant and
one with twenty years of equity, read those numbers completely differently, and the
reason the French pulse area is not moving is loss aversion rather than expected
value (Magrini et al. 2016, doi:10.1016/j.ecolecon.2016.03.024).

This module closes that gap with stochastic efficiency with respect to a function
(SERF), after Hardaker, Richardson, Lien and Schumann (2004),
doi:10.1111/j.1467-8489.2004.00239.x. SERF orders risky alternatives by their
certainty equivalents over a RANGE of risk attitudes rather than at one assumed
coefficient, which is exactly right here: we cannot know a given farmer's risk
aversion, but we can report the whole curve and the point at which the ranking flips.

Two deliberate methodological choices:

1. NEGATIVE EXPONENTIAL (CARA) UTILITY, not power/CRRA. Under CARA the certainty
   equivalent of a risk does not depend on the decision maker's initial wealth. That
   matters because no open French dataset gives us this farm's wealth or income — the
   Agreste RICA long-series bulk file that would have supplied it is a dead link (see
   `docs/DATA_SOURCES.md`). Choosing the one utility family whose answer is invariant
   to the number we are missing is a principled choice rather than a workaround.

2. THE WEALTH ANCHOR IS THE PARCEL, AND THAT IS STATED. To report risk aversion on an
   interpretable scale we still need to turn a relative coefficient into an absolute
   one, which needs a currency anchor. We use the better of the two arms' own median
   three-year margin on this parcel. So `rra` here means "how averse is this farmer to
   variation THE SIZE OF THIS DECISION", not aversion to variation in total household
   wealth. A farmer who cannot absorb a loss the size of one parcel's three-year
   margin genuinely is, at this scale, very risk averse. Scaling against whole-farm
   equity instead would shrink every risk premium and is the correct refinement once
   farm-level income data exists.

The coefficient range follows the Anderson and Dillon classification used throughout
the SERF literature: 0.5 hardly risk averse, 1 somewhat, 2 rather, 3 very, 4
extremely.
"""
from __future__ import annotations

import numpy as np

# Anderson and Dillon relative risk aversion classes, as used by Hardaker et al.
RRA_GRID: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 3.0, 4.0)
RRA_LABELS: dict[float, str] = {
    0.0: "risk neutral",
    0.5: "hardly risk averse",
    1.0: "somewhat risk averse",
    2.0: "rather risk averse",
    3.0: "very risk averse",
    4.0: "extremely risk averse",
}

# If both arms' median margins are near zero or negative — which happens on a fallow
# baseline, where there is no revenue and a real maintenance cost — the parcel gives
# no usable currency anchor and we fall back to this. It is the order of magnitude of
# a three-year arable margin per hectare, not a measurement.
MIN_WEALTH_ANCHOR_EUR_HA = 300.0


def wealth_anchor(sim: dict) -> float:
    """The currency scale used to turn relative risk aversion into absolute.

    The better of the two arms, because the anchor should describe the decision the
    farmer is facing rather than the arm that happens to be worse.
    """
    base = float(np.median(sim["baseline_total"]))
    pulse = float(np.median(sim["pulse_total"]))
    return max(base, pulse, MIN_WEALTH_ANCHOR_EUR_HA)


def certainty_equivalent(x: np.ndarray, ara: float) -> float:
    """Certainty equivalent of outcome array `x` under negative exponential utility.

    CE = -(1/a) * ln( E[ exp(-a x) ] ), and CE = E[x] when a == 0.

    Computed around the mean rather than on raw values: exp(-a*x) with x in the
    thousands overflows to inf in float64 and silently returns -inf, which would have
    made every risk-averse comparison meaningless. Shifting by the mean is exact
    because the shift factors straight out of the logarithm.
    """
    x = np.asarray(x, dtype=float)
    if ara <= 0.0:
        return float(np.mean(x))
    m = float(np.mean(x))
    z = x - m
    # exp(-a z) is now centred on 1, so no overflow for any plausible a.
    return float(m - np.log(np.mean(np.exp(-ara * z))) / ara)


def risk_sharing_diagnostic(sim: dict) -> dict:
    """Why whole-rotation risk aversion barely moves the ranking here.

    A measured result that was not obvious before building this, and that contradicts
    the intuition that a risk-aversion control should visibly flip the recommendation.

    Year 1 is IDENTICAL in both arms and year 3 differs only by the nitrogen credit and
    break-crop response, so the two rotations share most of their weather risk — around
    0.86 correlation on the Beauce field-pea case. A CARA certainty equivalent penalises
    each arm by roughly (a/2)·Var(arm), so when the arm variances are nearly equal the
    penalties cancel out of the comparison and the SERF ranking is driven almost
    entirely by the means.

    The quantity that risk aversion genuinely acts on is therefore the INCREMENTAL risk
    of switching — the distribution of the difference — which is also the economically
    correct object: the farmer's other hectares are unchanged whichever arm is chosen.
    """
    b, p, d = sim["baseline_total"], sim["pulse_total"], sim["delta"]
    var_diff = float(np.var(p) - np.var(b))
    var_delta = float(np.var(d))
    return {
        "arm_correlation": round(float(np.corrcoef(b, p)[0, 1]), 4),
        "sd_baseline_eur_ha": round(float(np.std(b)), 1),
        "sd_pulse_eur_ha": round(float(np.std(p)), 1),
        "sd_delta_eur_ha": round(float(np.std(d)), 1),
        "variance_difference_between_arms": round(var_diff, 1),
        "variance_of_delta": round(var_delta, 1),
        "share_of_delta_variance_explained_by_arm_asymmetry": (
            round(abs(var_diff) / var_delta, 4) if var_delta > 0 else None
        ),
        "finding": (
            "The two rotations share most of their weather risk, so whole-rotation "
            "certainty equivalents differ almost only by their means. Risk preference "
            "acts on the incremental risk of switching, not on the level of farm risk."
        ),
    }


def serf_curve(sim: dict, rra_grid: tuple[float, ...] = RRA_GRID) -> list[dict]:
    """Certainty equivalents across a range of risk attitudes.

    Reports both framings, because they answer different questions and disagree here:

    * `ce_advantage_eur_ha` is orthodox SERF — each alternative's own certainty
      equivalent, differenced. It answers "which whole rotation does this farmer
      prefer". It is nearly flat in `rra` for the reason `risk_sharing_diagnostic`
      measures, and that flatness is itself a result worth showing.
    * `ce_delta_eur_ha` applies the same utility to the distribution of the DIFFERENCE.
      It answers "is switching worth it", prices the incremental risk the pulse
      introduces, and is the number that actually responds to risk attitude.

    `switching_risk_premium_eur_ha` is what the farmer implicitly pays for bearing the
    extra uncertainty: mean(delta) − CE(delta).
    """
    w = wealth_anchor(sim)
    mean_d = float(np.mean(sim["delta"]))
    out = []
    for rra in rra_grid:
        ara = rra / w
        ce_b = certainty_equivalent(sim["baseline_total"], ara)
        ce_p = certainty_equivalent(sim["pulse_total"], ara)
        ce_d = certainty_equivalent(sim["delta"], ara)
        out.append({
            "rra": float(rra),
            "label": RRA_LABELS.get(rra, f"rra={rra}"),
            "ara_per_eur": float(ara),
            "ce_baseline_eur_ha": round(ce_b, 1),
            "ce_pulse_eur_ha": round(ce_p, 1),
            "ce_advantage_eur_ha": round(ce_p - ce_b, 1),
            "ce_delta_eur_ha": round(ce_d, 1),
            "switching_risk_premium_eur_ha": round(mean_d - ce_d, 1),
            "pulse_preferred": bool(ce_d > 0.0),
        })
    return out


def risk_tolerance_threshold(sim: dict) -> dict:
    """The risk attitude at which the switch stops being worth making.

    Bisects on a continuous coefficient rather than reading off the display grid.
    Uses the certainty equivalent of the DIFFERENCE, for the reason set out in
    `risk_sharing_diagnostic`: the arm-level comparison is nearly insensitive to risk
    aversion, so a threshold derived from it would be an artefact.

    `always` and `never` are both real answers and are reported as such rather than
    forced into a number. `never` specifically means the switch fails on expected
    value, so no degree of risk tolerance rescues it.

    THE THRESHOLD IS ILL-CONDITIONED ON MARGINAL CASES, AND SAYS SO
    ---------------------------------------------------------------
    The crossing point is where the switching risk premium equals the mean delta. The
    premium is well estimated — it is driven by Var(delta) and varies by about 2% across
    seeds. The mean delta on a marginal case is not: at +11 EUR/ha against a delta
    standard deviation near 300, 2,000 draws give it a standard error around 7, so it
    moves 23% between seeds. The ratio inherits that noise and amplifies it, and the
    measured threshold on the Cote-d'Or winter pea case ranges 0.82 to 1.71 across eight
    seeds at 2,000 draws, and still 0.89 to 1.53 at 20,000.

    So a bare two-decimal threshold would imply precision that does not exist. This
    returns a bootstrap interval alongside the point estimate, and `verdict_resolved` is
    False whenever the sign of the mean delta is itself within two standard errors of
    zero — in which case the honest reading is "too close to call", not a number.
    Anything quoting this figure should quote the interval with it.
    """
    w = wealth_anchor(sim)
    d = np.asarray(sim["delta"], dtype=float)
    n = d.size
    mean_d = float(np.mean(d))
    se_d = float(np.std(d, ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    resolved = bool(abs(mean_d) > 2.0 * se_d)

    def adv(rra: float, arr: np.ndarray | None = None) -> float:
        return certainty_equivalent(d if arr is None else arr, rra / w)

    def crossing(arr: np.ndarray) -> float | None:
        if adv(0.0, arr) <= 0.0 or adv(8.0, arr) > 0.0:
            return None
        a, b = 0.0, 8.0
        for _ in range(32):
            m = 0.5 * (a + b)
            if adv(m, arr) > 0.0:
                a = m
            else:
                b = m
        return 0.5 * (a + b)

    def interval() -> dict:
        """Bootstrap the crossing point by resampling the delta draws."""
        rng = np.random.default_rng(12345)
        boots = [
            c for _ in range(120)
            if (c := crossing(d[rng.integers(0, n, n)])) is not None
        ]
        if len(boots) < 30:
            return {"rra_threshold_p10": None, "rra_threshold_p90": None,
                    "bootstrap_crossings": len(boots)}
        return {
            "rra_threshold_p10": round(float(np.percentile(boots, 10)), 2),
            "rra_threshold_p90": round(float(np.percentile(boots, 90)), 2),
            "bootstrap_crossings": len(boots),
        }

    stats = {
        "mean_delta_eur_ha": round(mean_d, 1),
        "mean_delta_standard_error_eur_ha": round(se_d, 2),
        "verdict_resolved": resolved,
        "n_draws": int(n),
    }
    if not resolved:
        stats["caution"] = (
            "The sign of the mean delta is within two standard errors of zero, so "
            "whether this switch pays at all is unresolved at this draw count. Any "
            "threshold below is a point on noise; quote the interval, not the point."
        )

    lo_adv, hi_adv = adv(0.0), adv(8.0)
    if lo_adv <= 0.0:
        # Not preferred even by a risk-neutral farmer: this is an expected-value
        # problem, not a risk problem, and no amount of risk tolerance fixes it.
        return {"verdict": "never", "rra_threshold": None,
                "advantage_risk_neutral_eur_ha": round(lo_adv, 1), **stats}
    if hi_adv > 0.0:
        return {"verdict": "always", "rra_threshold": None,
                "advantage_risk_neutral_eur_ha": round(lo_adv, 1), **stats}
    lo, hi = 0.0, 8.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if adv(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    thr = 0.5 * (lo + hi)
    ci = interval()
    band = ""
    if ci["rra_threshold_p10"] is not None:
        band = f" (bootstrap 10-90%: {ci['rra_threshold_p10']:.2f} to {ci['rra_threshold_p90']:.2f})"
    # Quote the coefficient to ONE decimal in prose. The second decimal is not
    # reproducible across seeds and invites a precision the estimate cannot support.
    interp = (
        f"Preferred by a farmer up to roughly {RRA_LABELS.get(round(thr), 'this level of caution')} "
        f"(relative risk aversion about {thr:.1f} against this parcel's own margin){band}; "
        "rejected by anyone more cautious."
    )
    if not resolved:
        interp = (
            "Too close to call at this draw count: the mean delta is within two "
            f"standard errors of zero. The crossing sits around {thr:.1f}{band}, but "
            "the sign of the underlying advantage is not resolved, so this should be "
            "presented as a marginal case rather than as a threshold."
        )
    return {
        "verdict": "flips",
        "rra_threshold": round(thr, 2),
        "advantage_risk_neutral_eur_ha": round(lo_adv, 1),
        **ci,
        **stats,
        "interpretation": interp.replace("  ", " "),
    }


# --------------------------------------------------------------------------------
# Contract inversion
# --------------------------------------------------------------------------------
#
# `finance.breakeven_human_fraction` already inverts on QUALITY: how much of the
# harvest must clear food grade for this to be worth doing. The complementary
# question is the one a buyer can actually act on - what TERMS would make this
# farmer say yes - and nothing answered it. `offtake.py` scores the offers that
# exist; it cannot derive the offer that would work.
#
# The inversion reuses the draws already taken rather than re-simulating. Only the
# year-2 pulse revenue depends on contract terms, and its structure is known, so a
# hypothetical contract can be repriced on the existing yield, grading and spot-price
# arrays. That makes the whole search a few vectorised passes instead of thousands of
# fresh Monte Carlo runs.


def pulse_total_under_contract(
    sim: dict,
    price_eur_t: float,
    floor_eur_t: float | None,
    volume_share: float,
) -> np.ndarray:
    """Three-year pulse-arm total if `volume_share` were forward contracted.

    The uncontracted remainder stays on the spot prices actually drawn, so a partial
    contract correctly leaves partial exposure. A guaranteed floor replaces the feed
    spot price on the contracted share only.

    For a livestock farm the floor cannot drag the effective feed price BELOW the
    on-farm substitution value, because that farm would simply feed the grain instead
    of selling it. `finance.simulate` applies that same maximum when it builds
    `price_feed`, and the elementwise maximum here reproduces it: `price_feed` already
    carries the substitution value where it was the higher of the two.
    """
    py = sim["pulse_yield"]
    frac = sim["human_fraction"]
    spot_h, spot_f = sim["price_human"], sim["price_feed"]

    v = float(np.clip(volume_share, 0.0, 1.0))
    c_floor = np.maximum(np.full_like(spot_f, float(floor_eur_t)), spot_f) if floor_eur_t else spot_f
    contracted = frac * float(price_eur_t) + (1.0 - frac) * c_floor
    spot = frac * spot_h + (1.0 - frac) * spot_f
    revenue = py * (v * contracted + (1.0 - v) * spot)

    # Swap the revenue term out of the already-assembled pulse total.
    return sim["pulse_total"] - sim["pulse_revenue"] + revenue


def minimum_viable_contract(
    sim: dict,
    rra: float = 2.0,
    volume_shares: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0),
    floor_eur_t: float | None = None,
    price_bounds: tuple[float, float] = (100.0, 2000.0),
) -> dict:
    """The cheapest forward contract that makes the pulse rotation preferred.

    For each contracted volume share, bisect on the contract price until the pulse
    arm's certainty equivalent matches the baseline's at the given risk attitude.
    This is the number a buyer and a farmer can negotiate over, and it is the output
    the rest of the engine was one root-find away from.

    `None` for a share means no price inside `price_bounds` is enough — contracting
    that little volume cannot carry the decision at this risk attitude.
    """
    w = wealth_anchor(sim)
    ara = float(rra) / w
    target = 0.0
    lo_p, hi_p = price_bounds

    def ce_at(price: float, share: float) -> float:
        """Risk-adjusted value of SWITCHING under these terms, per hectare.

        The certainty equivalent of the difference, not of the pulse arm alone — see
        `risk_sharing_diagnostic` for why the arm-level comparison is nearly blind to
        risk attitude and would make these terms insensitive to `rra`.
        """
        under = pulse_total_under_contract(sim, price, floor_eur_t, share)
        return certainty_equivalent(under - sim["baseline_total"], ara)

    rows = []
    for v in volume_shares:
        if ce_at(hi_p, v) < target:
            rows.append({"volume_share": v, "min_contract_price_eur_t": None,
                         "feasible": False})
            continue
        if ce_at(lo_p, v) >= target:
            # Already preferred at the bottom of the search range: report the bound
            # rather than implying precision we do not have.
            rows.append({"volume_share": v, "min_contract_price_eur_t": round(lo_p, 1),
                         "feasible": True, "note": "preferred at or below the search floor"})
            continue
        a, b = lo_p, hi_p
        for _ in range(40):
            mid = 0.5 * (a + b)
            if ce_at(mid, v) >= target:
                b = mid
            else:
                a = mid
        rows.append({"volume_share": v, "min_contract_price_eur_t": round(0.5 * (a + b), 1),
                     "feasible": True})

    feasible = [r for r in rows if r.get("feasible")]
    headline = None
    if feasible:
        best = min(feasible, key=lambda r: r["min_contract_price_eur_t"])
        headline = (
            f"Becomes preferred at a EUR {best['min_contract_price_eur_t']:.0f}/t "
            f"contract on {best['volume_share']:.0%} of expected volume"
        )

    # How much the required price depends on the assumed risk attitude. Reported
    # because `rra` is the one input here that cannot be observed, so the honest
    # presentation is the range rather than a single figure.
    sensitivity = {}
    for probe in (0.0, 4.0):
        a = probe / w
        under = pulse_total_under_contract(sim, hi_p, floor_eur_t, 1.0)
        if certainty_equivalent(under - sim["baseline_total"], a) < 0.0:
            sensitivity[f"rra_{probe:g}"] = None
            continue
        a_lo, b_hi = lo_p, hi_p
        for _ in range(40):
            mid = 0.5 * (a_lo + b_hi)
            u = pulse_total_under_contract(sim, mid, floor_eur_t, 1.0)
            if certainty_equivalent(u - sim["baseline_total"], a) >= 0.0:
                b_hi = mid
            else:
                a_lo = mid
        sensitivity[f"rra_{probe:g}"] = round(0.5 * (a_lo + b_hi), 1)

    return {
        "rra_assumed": float(rra),
        "risk_label": RRA_LABELS.get(float(rra), f"rra={rra}"),
        "floor_eur_t": floor_eur_t,
        "wealth_anchor_eur_ha": round(w, 1),
        "terms": rows,
        "headline": headline,
        "price_sensitivity_full_volume_eur_t": sensitivity,
        "method": (
            "Bisection on contract price until the certainty equivalent of the "
            "DIFFERENCE between the two rotations reaches zero, repricing year-2 "
            "revenue on the Monte Carlo draws already taken. Negative exponential "
            "utility, relative risk aversion anchored on this parcel's own three-year "
            "margin. Method after Hardaker et al. (2004), "
            "doi:10.1111/j.1467-8489.2004.00239.x."
        ),
    }
