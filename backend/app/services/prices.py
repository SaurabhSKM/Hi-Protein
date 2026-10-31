"""Correlated price draws.

The correlation matters more than the marginal distributions. Yield and price are
negatively correlated: a season that cuts French and European yields lifts the price,
which partly offsets the farmer's loss. Drawing them independently, as a naive Monte
Carlo does, overstates downside risk by roughly the size of that hedge, and a model
that overstates risk is as useless to a planting decision as one that hides it.
"""
from __future__ import annotations

import numpy as np

from ..config import crop, load_ref

# Yield-price correlation, per crop family. Strongest for crops traded on a deep
# European market where a French yield shock moves the whole balance sheet; weakest
# for niche pulses whose price is set by import competition and contract grids.
YIELD_PRICE_RHO = {
    "cereal": -0.40,
    "oilseed": -0.30,
    "pulse": -0.18,
    "forage_legume": -0.10,
}


def _lognormal(rng, spec: dict, n: int, z: np.ndarray | None = None) -> np.ndarray:
    mean, sd = float(spec["mean"]), float(spec["sd"])
    # A degenerate spec is legitimate: fallow land has no price and no revenue.
    # A lognormal cannot represent zero, so short-circuit rather than divide by it.
    if mean <= 0.0:
        return np.zeros(n)
    sigma = max(sd / mean, 1e-6)
    mu = np.log(mean) - 0.5 * sigma**2
    zz = rng.standard_normal(n) if z is None else z
    draw = np.exp(mu + sigma * zz)
    return np.clip(draw, spec.get("min", mean * 0.4), spec.get("max", mean * 3.0))


def price_draw(
    rng: np.random.Generator,
    crop_key: str,
    n: int,
    *,
    yield_z: np.ndarray | None = None,
    feed: bool = False,
) -> np.ndarray:
    """Draw a farm-gate price, negatively correlated with the yield shock."""
    spec = crop(crop_key)
    key = "feed_price_eur_t" if (feed and "feed_price_eur_t" in spec) else "price_eur_t"
    p = spec[key]
    rho = YIELD_PRICE_RHO.get(spec.get("family", "cereal"), -0.25)
    if yield_z is None:
        z = rng.standard_normal(n)
    else:
        # Build a price shock with the target correlation to the yield shock.
        z = rho * yield_z + np.sqrt(max(1.0 - rho**2, 0.0)) * rng.standard_normal(n)
    return _lognormal(rng, p, n, z)


def cost_draw(rng: np.random.Generator, crop_key: str, n: int) -> np.ndarray:
    """Operational charges per hectare. Input-cost driven, not yield driven."""
    return _lognormal(rng, crop(crop_key)["op_cost_eur_ha"], n)


def feed_substitution_value(
    rng: np.random.Generator, crop_key: str, n: int
) -> np.ndarray:
    """On-farm replacement value of a downgraded lot, EUR/t.

    Higher than the feed spot price because feeding your own crop replaces purchased
    protein meal AND purchased cereal, and avoids haulage and trader margin on both.
    """
    ref = load_ref("feed_substitution")
    sub = ref["substitution"].get(crop_key)
    if not sub:
        return price_draw(rng, crop_key, n, feed=True)
    rp = ref["reference_prices_eur_t"]
    # One shared shock: meal and cereal prices move together with the grain complex.
    z = rng.standard_normal(n)
    meal = _lognormal(rng, rp["soybean_meal_48"], n, z)
    wheat = _lognormal(rng, rp["feed_wheat"], n, 0.7 * z + 0.714 * rng.standard_normal(n))
    return sub["a_soymeal"] * meal + sub["a_cereal"] * wheat + ref["avoided_logistics_eur_t"]
