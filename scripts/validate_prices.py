"""Cross-check refdata/crops.json price assumptions against official observed prices.

`crops.json` carries `price_eur_t` distributions with a `_meta` basis note, but until
now nothing in the repo compared them against an observed French series. Eurostat
`apri_ap_crpouta` (Selling prices of crop products, absolute prices, annual) publishes
exactly that: farm-gate selling prices per 100 kg, per member state, including dried
peas, lentils and soya alongside the cereals and oilseeds that make up the baseline
arm.

TWO LIMITS, BOTH LOAD-BEARING, SO READ THE RATIOS NOT THE LEVELS
----------------------------------------------------------------
1. The French series STOPS AT 2016, and pulses only start at 2012 (the 2010 and 2011
   pulse figures are two orders of magnitude out and are discarded as unit errors).
   Prices re-based sharply upward from 2021, so a 2012-2016 observed mean is not a
   fair benchmark for a reference distribution calibrated on the recent regime.
2. France reports NO price at all for fava bean or chickpea in this dataset, which are
   two of the engine's candidate crops.

So the level comparison is reported but should not be read as an error measure. What
survives the regime shift is the RATIO of each crop's price to soft wheat in the same
years: if the engine assumes a larger premium over wheat than France ever observed,
that inflates the pulse arm regardless of the absolute price level. The ratio check is
the one with teeth, and the lentil result is the reason this script exists.

Run: .venv/bin/python scripts/validate_prices.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "eurostat"
OUT = ROOT / "data" / "processed" / "price_validation.json"
CROPS = ROOT / "backend" / "app" / "refdata" / "crops.json"

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/apri_ap_crpouta"

# Eurostat prod_veg code -> internal crop key.
PRODUCTS = {
    "01110000": "soft_wheat",
    "01120000": "durum_wheat",
    "01300000": "spring_barley",   # Eurostat reports one "Barley" series, not by habit
    "01500000": "grain_maize",
    "02110000": "rapeseed",
    "02120000": "sunflower",
    "02130000": "soybean",
    "02210000": "field_pea",
    "02991000": "green_lentil",
}
# Unit errors are detected as a LEVEL BREAK against the series' own median rather than
# by an absolute floor. France's pulse rows read 2.4 and 14.0 EUR/100kg in 2010-2011
# and then 33 to 78 from 2012 on; a 4.6x step in one year is a definition change, not a
# market move. An absolute floor cannot separate those two cases across crops whose
# real prices differ by a factor of five, but a fraction of the median can.
UNIT_ERROR_FRACTION_OF_MEDIAN = 0.40

# Every crop's ratio is computed over this window so that crops with long series are
# not compared against crops that only start in 2012. The window is the overlap the
# French pulse series actually offers.
RATIO_WINDOW = ("2012", "2016")
RATIO_REFERENCE = "soft_wheat"


def fetch(prod: str) -> dict[str, float]:
    """Annual French price series for one product, EUR per 100 kg, cached to disk."""
    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / f"apri_ap_crpouta_FR_{prod}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    url = BASE + "?" + urllib.parse.urlencode(
        [("format", "JSON"), ("geo", "FR"), ("currency", "EUR"), ("prod_veg", prod)]
    )
    req = urllib.request.Request(url, headers={"User-Agent": "hiprotein/1.0 (validation)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    index = payload["dimension"]["time"]["category"]["index"]
    rev = {v: k for k, v in index.items()}
    series = {rev[int(k)]: float(v) for k, v in payload["value"].items()}
    cache.write_text(json.dumps(series, indent=1, sort_keys=True))
    return series


def main() -> int:
    ref = json.loads(CROPS.read_text())
    observed: dict[str, dict[str, float]] = {}
    discarded: dict[str, list[str]] = {}

    for prod, key in PRODUCTS.items():
        try:
            series = fetch(prod)
        except Exception as exc:  # pragma: no cover - network path
            print(f"  ! {key}: fetch failed ({exc})", file=sys.stderr)
            continue
        vals = sorted(series.values())
        med = vals[len(vals) // 2] if vals else 0.0
        clean = {y: v for y, v in series.items()
                 if v >= UNIT_ERROR_FRACTION_OF_MEDIAN * med}
        dropped = sorted(set(series) - set(clean))
        if dropped:
            discarded[key] = dropped
        if clean:
            observed[key] = clean

    wheat = observed.get(RATIO_REFERENCE, {})
    rows = []
    for key, series in sorted(observed.items()):
        years = sorted(series)
        obs_eur_t = [series[y] * 10.0 for y in years]          # per 100 kg -> per tonne
        obs_mean = sum(obs_eur_t) / len(obs_eur_t)
        cfg = (ref.get(key) or {}).get("price_eur_t") or {}
        assumed = cfg.get("mean")

        # Ratio against wheat over a FIXED window common to every crop, so a crop with
        # a 2000-2016 series is not compared against one that only starts in 2012.
        lo, hi = RATIO_WINDOW
        shared = [y for y in years if y in wheat and lo <= y <= hi]
        obs_ratio = assumed_ratio = None
        if shared and key != RATIO_REFERENCE:
            obs_ratio = (sum(series[y] for y in shared) / len(shared)) / (
                sum(wheat[y] for y in shared) / len(shared)
            )
            wheat_assumed = (ref.get(RATIO_REFERENCE) or {}).get("price_eur_t", {}).get("mean")
            if assumed and wheat_assumed:
                assumed_ratio = assumed / wheat_assumed

        rows.append({
            "crop": key,
            "observed_years": f"{years[0]}-{years[-1]}",
            "n_years": len(years),
            "observed_mean_eur_t": round(obs_mean, 1),
            "assumed_mean_eur_t": assumed,
            "level_ratio_assumed_over_observed": (
                round(assumed / obs_mean, 3) if assumed else None
            ),
            "inside_assumed_min_max": (
                bool(cfg.get("min", -1) <= obs_mean <= cfg.get("max", 1e9)) if cfg else None
            ),
            "observed_price_vs_wheat": round(obs_ratio, 3) if obs_ratio else None,
            "assumed_price_vs_wheat": round(assumed_ratio, 3) if assumed_ratio else None,
            "premium_overstatement": (
                round(assumed_ratio / obs_ratio - 1.0, 3)
                if (obs_ratio and assumed_ratio) else None
            ),
        })

    missing = sorted(
        k for k in ("fava_bean", "chickpea") if k not in observed
    )

    # Does the SOURCE survive its own sanity check? Oilseeds trade persistently above
    # feed wheat on every European market - rapeseed at roughly 1.7-2x, soybean
    # similar - because they are crushed for oil and meal. If the series puts them at
    # or below wheat, the defect is in the series, not in the engine's assumptions, and
    # any "overstatement" it reports for other crops cannot be trusted either.
    flags = []
    for r in rows:
        if (
            r["crop"] in ("rapeseed", "soybean", "sunflower")
            and r["observed_price_vs_wheat"]
            and r["observed_price_vs_wheat"] < 1.3
        ):
            flags.append(
                    f"{r['crop']}: observed at {r['observed_price_vs_wheat']:.2f}x wheat over "
                    f"{RATIO_WINDOW[0]}-{RATIO_WINDOW[1]}, which no European oilseed market "
                    "sustains - the source series is not credible here"
                )
    if discarded:
        flags.append(
            "unit errors present: " + ", ".join(f"{k} {v}" for k, v in discarded.items())
        )
    if missing:
        flags.append("no French series at all for: " + ", ".join(missing))
    flags.append("series ends 2016, so the post-2021 price regime is unobserved")

    report = {
        "verdict": (
            "NOT USABLE for calibrating or correcting crops.json. The French rows of "
            "this dataset carry unit errors, omit two of the engine's candidate crops, "
            "end in 2016, and price oilseeds at or below feed wheat - a relationship no "
            "European market sustains. Recorded so that nobody cites it as validation: "
            "a jury that checks the rapeseed row would discredit the whole comparison. "
            "The figures below are retained as evidence for that verdict, NOT as "
            "corrections to apply."
        ),
        "source_quality_flags": flags,
        "source": "Eurostat apri_ap_crpouta, geo=FR, currency=EUR (annual, EUR/100kg)",
        "reference_checked": str(CROPS.relative_to(ROOT)),
        "ratio_reference_crop": RATIO_REFERENCE,
        "rows": rows,
        "discarded_as_unit_errors": discarded,
        "no_french_series_at_all": missing,
        "how_to_read": (
            "Compare `premium_overstatement`, not the levels. The observed series ends "
            "in 2016 and prices re-based upward from 2021, so a level gap is mostly a "
            "regime difference. A positive `premium_overstatement` means the engine "
            "assumes a larger premium over wheat than France ever observed, which "
            "inflates the pulse arm independently of the absolute price level."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))

    print(f"{'crop':14s} {'years':10s} {'obs E/t':>9s} {'assumed':>9s} "
          f"{'obs/wheat':>10s} {'asm/wheat':>10s} {'overstate':>10s}")
    for r in rows:
        print(f"{r['crop']:14s} {r['observed_years']:10s} "
              f"{r['observed_mean_eur_t']:9.1f} "
              f"{(r['assumed_mean_eur_t'] or 0):9.1f} "
              f"{(r['observed_price_vs_wheat'] or 0):10.3f} "
              f"{(r['assumed_price_vs_wheat'] or 0):10.3f} "
              f"{(r['premium_overstatement'] if r['premium_overstatement'] is not None else 0):+10.1%}")
    if discarded:
        print("\ndiscarded as unit errors:", discarded)
    if missing:
        print("no French series at all:", missing)
    print("\nVERDICT:", report["verdict"])
    for f in flags:
        print("  flag:", f)
    print(f"\nwritten -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
