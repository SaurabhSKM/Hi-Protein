"""Does this verdict survive its own assumptions?

The engine reports a median three-year margin difference as a single number, and users
read a single number as a fact. It is not one: it sits on top of assumptions that a
sensitivity audit (`scripts/sensitivity_audit.py`) showed can flip the SIGN of the
answer on a marginal field. Measured there:

* the grading base pass rate, pushed +/-0.15, flips the verdict on 2 of 3 test fields;
* the haulage rate, across its OWN published 0.32-0.58 EUR/t/km range, moves stranded
  land from 2,680 to 6,178 communes;
* the road detour factor, 1.0 to 1.6, moves it from 2,691 to 5,994.

Reporting the central answer without saying which of those it survives leaves the user
to discover the fragility themselves, usually by being contradicted. So each response
now carries a verdict-robustness block: the answer is re-derived at the edges of the
assumptions that matter, and the response states plainly whether the recommendation
holds throughout or flips.

This does not remove an assumption. It stops the OUTPUT of an assumption being
presented as a measurement, which is the next best thing and is cheap.

Deliberately NOT a full re-simulation. Both perturbations are repriced on the draws
already taken, so the cost is a handful of vectorised operations rather than another
2,000-path Monte Carlo per request.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..config import load_ref


def _haulage_band() -> tuple[float, float, float]:
    h = load_ref("logistics")["haulage"]
    lo, hi = h["eur_per_tonne_km_range"]
    return float(lo), float(h["eur_per_tonne_km"]), float(hi)


def _detour_band() -> tuple[float, float]:
    """Plausible spread on the detour factor, which is a flat guess standing in for
    routed distance. 1.0 is the straight-line floor (no detour at all, impossible but
    a hard bound); 1.6 is a hilly-terrain upper case."""
    return 1.0, 1.6


def grading_sensitivity(sim: dict, *, delta: float = 0.15) -> dict[str, Any]:
    """Re-price the margin with the food-grade fraction shifted up and down.

    The grading hazard model has no observational labels anywhere in French open data,
    so a +/-0.15 band on the realised food fraction is the honest expression of how
    little is pinned down. Repriced on the draws already taken: the only thing that
    changes is how much of each sampled harvest is paid the food price.
    """
    py = sim["pulse_yield"]
    ph, pf = sim["price_human"], sim["price_feed"]
    frac = sim["human_fraction"]
    haul_per_t = float(sim["haulage_eur_per_t_food"])
    base = sim["delta"]

    out = {}
    for label, shift in (("low", -delta), ("central", 0.0), ("high", +delta)):
        f2 = np.clip(frac + shift, 0.0, 1.0)
        # Revenue and haulage both move with the fraction; everything else is unchanged.
        d_rev = py * (f2 - frac) * (ph - pf)
        d_haul = py * (f2 - frac) * haul_per_t
        d = base + d_rev - d_haul
        out[label] = round(float(np.median(d)), 1)
    return out


def haulage_sensitivity(sim: dict, sorter_road_km: float | None) -> dict[str, Any]:
    """Re-price the margin across the published haulage rate and detour spread.

    Both parameters enter the margin through the same term - euros per tonne of
    food-grade harvest - so the extremes are the cheap rate at no detour and the dear
    rate over a hilly route.
    """
    lo_rate, mid_rate, hi_rate = _haulage_band()
    lo_det, hi_det = _detour_band()
    radius = float(load_ref("logistics")["haulage"]["local_collection_radius_km"])
    det_mid = float(load_ref("logistics")["haulage"]["road_detour_factor"])

    base = sim["delta"]
    t_food = sim["pulse_yield"] * sim["human_fraction"]
    charged_now = float(sim["haulage_eur_per_t_food"])

    if sorter_road_km is None or not np.isfinite(sorter_road_km):
        v = round(float(np.median(base)), 1)
        return {"low": v, "central": v, "high": v, "binding": False}

    # Undo the detour factor to recover the straight-line distance, then re-apply.
    straight = float(sorter_road_km) / det_mid

    def repriced(rate: float, detour: float) -> float:
        km = max(straight * detour - radius, 0.0)
        return round(float(np.median(base + t_food * (charged_now - km * rate))), 1)

    return {
        # Cheap haulage, no detour: the most favourable reading of the two parameters.
        "low": repriced(hi_rate, hi_det),
        "central": round(float(np.median(base)), 1),
        "high": repriced(lo_rate, lo_det),
        "binding": bool(charged_now > 0.0),
        "rate_range_eur_t_km": [lo_rate, hi_rate],
        "detour_range": [lo_det, hi_det],
    }


def assess(sim: dict, sorter_road_km: float | None) -> dict[str, Any]:
    """Whether the recommendation survives the assumptions that can move its sign."""
    grading = grading_sensitivity(sim)
    haulage = haulage_sensitivity(sim, sorter_road_km)

    values = [grading["low"], grading["high"], haulage["low"], haulage["high"]]
    central = round(float(np.median(sim["delta"])), 1)
    lo, hi = min(values + [central]), max(values + [central])
    flips = (lo < 0) != (hi < 0)

    drivers = []
    if (grading["low"] < 0) != (grading["high"] < 0):
        drivers.append("the food-grade pass rate, which has no observational labels")
    if (haulage["low"] < 0) != (haulage["high"] < 0):
        drivers.append("the haulage rate and road detour factor")

    if not flips:
        verdict = (
            f"Holds. The recommendation stays {'positive' if central >= 0 else 'negative'} "
            f"across the full plausible range of both assumptions that could move it "
            f"({lo:+.0f} to {hi:+.0f} EUR/ha)."
        )
    else:
        verdict = (
            f"FRAGILE. The sign of this answer is not robust: across the plausible range "
            f"it runs from {lo:+.0f} to {hi:+.0f} EUR/ha, so the recommendation changes "
            f"depending on " + " and ".join(drivers) + ". Treat the central figure as "
            "one reading, not a result."
        )

    return {
        "central_eur_ha": central,
        "range_low_eur_ha": lo,
        "range_high_eur_ha": hi,
        "verdict_is_robust": not flips,
        "verdict": verdict,
        "grading_pass_rate_pm_0_15": grading,
        "haulage_across_published_range": haulage,
        "method": (
            "Both perturbations are repriced on the Monte Carlo draws already taken, not "
            "re-simulated, so this costs a few vectorised operations rather than another "
            "2,000 paths. The grading band is +/-0.15 on the realised food fraction; the "
            "haulage band is the published 0.32-0.58 EUR/t/km rate crossed with a "
            "1.0-1.6 detour factor. Ranges from scripts/sensitivity_audit.py."
        ),
    }
