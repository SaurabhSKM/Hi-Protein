"""Bake the per-department economics the siting optimiser runs on.

The optimiser needs, for every department, the three-year margin advantage of its
best-fitting pulse at zero incremental haulage - with and without optical sorting
access, because the grading hazard model steps at the access threshold. From those two
numbers every (commune, candidate site) pair is an exact closed-form shift, because
haulage is linear in tonnes of food-grade harvest.

That is 42 departments x up to 6 pulses x 2 access states of paired Monte Carlo, which
is about a minute per climate horizon. Doing it at request time would make the regional
view unusable, and doing it at startup would make the server slow to boot, so it is
baked here and the service loads it from disk. `siting.profiles()` falls back to
computing a lower-resolution version live if this file is missing, so nothing breaks
without it - it is just slow enough that a browser gives up first.

Every climate horizon is baked, not only the observed one. The food view lets a reader
switch horizon, and a horizon with no cache behind it sent that endpoint down the live
path: 42 departments x 6 pulses, about 71 seconds, on every request. Five horizons take
roughly six minutes here and turn all of them into dictionary lookups.

Run: python scripts/build_region_profiles.py [n_simulations] [horizon ...]
Writes: data/processed/region_profiles.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.services import siting  # noqa: E402


def main() -> int:
    n_sim = int(sys.argv[1]) if len(sys.argv) > 1 else 800
    horizons = sys.argv[2:] or None
    t0 = time.perf_counter()
    data = siting.build_all_horizons(n_sim=n_sim, horizons=horizons, verbose=True)
    data["_meta"]["built_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data["_meta"]["build_seconds"] = round(time.perf_counter() - t0, 1)

    siting.PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    siting.PROFILE_PATH.write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {siting.PROFILE_PATH}")
    print(f"  {n_sim} paths per department, {data['_meta']['build_seconds']} s total")
    for h, rows in data["horizons"].items():
        pos = sum(1 for p in rows.values() if p["access"]["delta0_eur_ha"] > 0)
        nv = data["_meta"]["no_viable_pulse"].get(h, [])
        print(
            f"  {h:12s} {len(rows):3d} profiles, {pos} beat cereals with sorting access"
            + (f", no viable pulse in {','.join(nv)}" if nv else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
