"""Tests for the derived-result cache the regional and food views run on.

These lock in the three properties that made those two tabs usable, each of which was
a measured failure before:

1. **Every climate horizon is baked.** The bake used to cover `observed` alone, so the
   food view's horizon selector dropped `/food-demand` onto a live 42-department Monte
   Carlo - 71 seconds per request, which no browser waits for.
2. **A department with no viable pulse is a recorded answer, not a gap.** Departments 81
   and 82 are boulbene at pH 5.9, which blocks every legume. "Absent from the bake" used
   to mean both that and "never baked", so both were re-simulated on every request to
   rediscover a permanent fact.
3. **Nothing heavy runs inside a request.** The assembled responses are memoised, so a
   second call is a lookup.

Property 1 is asserted conditionally on what the local bake actually covers: a
contributor who has only run `make profiles-fast` should get a clear skip, not a
failure. The assertions that hold regardless - the negative-result bookkeeping, the
memoisation, the back-compat of an old single-horizon file - always run.
"""
import time

import pytest
from app.main import app
from app.services import climate, siting
from fastapi.testclient import TestClient

BASE = "/api/v1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# What the bake covers
# --------------------------------------------------------------------------- #
def test_bake_status_reports_the_horizons_it_actually_has():
    st = siting.bake_status()
    assert st["present"], "run `make profiles` - the regional views have no cache"
    assert st["horizons"], "a present bake must cover at least one horizon"
    # Whatever it covers, the observed horizon is the default every other reader
    # (optimiser, commune classifier) depends on.
    assert "observed" in st["horizons"]
    assert st["horizons"]["observed"] >= 38


def test_every_climate_horizon_is_baked():
    """The food view offers all of them, so all of them need a cache behind them."""
    covered = set(siting.bake_status()["horizons"])
    missing = [h for h in climate.horizon_keys() if h not in covered]
    if missing:
        pytest.skip(
            f"bake covers {sorted(covered)}; {missing} would compute live. "
            "Run `make profiles` for the full cache."
        )
    for h in climate.horizon_keys():
        assert siting.profiles(h)["_meta"]["loaded_from"] == "baked", h


# --------------------------------------------------------------------------- #
# The negative result is recorded, not rediscovered
# --------------------------------------------------------------------------- #
def test_a_department_with_no_viable_pulse_is_recorded_rather_than_merely_absent():
    """The distinction that cost 3 s on every food-demand request.

    Every department must be EITHER in the profiles or on the no-viable-pulse list.
    A department in neither is indistinguishable from an incomplete bake, which is
    what sends the endpoint off to re-simulate it.
    """
    from app.config import departments

    prof = siting.profiles("observed")
    if prof["_meta"]["loaded_from"] != "baked":
        pytest.skip("no baked observed horizon to check")
    if not prof["_meta"].get("no_viable_pulse"):
        pytest.skip("bake predates the no-viable-pulse list; re-run `make profiles`")

    baked = set(prof["profiles"])
    unviable = siting.unviable_departments("observed")
    unaccounted = sorted(set(departments()) - baked - unviable)
    assert not unaccounted, (
        f"departments {unaccounted} are in neither the bake nor the no-viable-pulse "
        "list, so every request will re-simulate them"
    )


def test_the_no_viable_pulse_list_and_the_profiles_are_disjoint():
    unviable = siting.unviable_departments("observed")
    baked = set(siting.profiles("observed")["profiles"])
    assert not (unviable & baked), "a department cannot both have and lack a viable pulse"


def test_unviable_departments_really_have_every_pulse_blocked():
    """Guard against the list becoming a dumping ground for bake failures.

    If a department is on it, agronomy must independently agree that every candidate
    pulse is blocked there - otherwise the cache is suppressing a real result.
    """
    from app.config import departments, pulse_crops
    from app.services import agronomy

    unviable = siting.unviable_departments("observed")
    if not unviable:
        pytest.skip("nothing on the list for this bake")
    depts = departments()
    for code in unviable:
        d = depts[code]
        base = (
            ["durum_wheat", "sunflower", "soft_wheat"]
            if d.get("region_code") in {"FRJ2", "FRI1"}
            else ["soft_wheat", "spring_barley", "rapeseed"]
        )
        for pulse in pulse_crops():
            val = agronomy.validate(
                pulse, history=list(base), baseline_rotation=base,
                soil_type=d["dominant_soil"], soil_ph=None, irrigated=False,
            )
            assert val.severity == "blocked", (
                f"{code} is listed as having no viable pulse, but {pulse} is "
                f"{val.severity}, not blocked"
            )


# --------------------------------------------------------------------------- #
# Back-compat of the cache file
# --------------------------------------------------------------------------- #
def test_an_old_single_horizon_file_still_loads(tmp_path, monkeypatch):
    """A bake written before the file gained its horizon dimension must still read.

    The observed horizon lived at the top level under `profiles`; the reader has to
    keep finding it there, or an un-rebuilt deployment silently falls back to computing
    everything live.
    """
    import json

    old = {
        "_meta": {"n_simulations": 800},
        "profiles": {
            "28": {
                "dept": "28", "pulse": "green_lentil", "candidates": [],
                "access": {"delta0_eur_ha": 120.0, "food_t_per_ha": 1.0},
                "no_access": {"delta0_eur_ha": -30.0, "food_t_per_ha": 1.0},
            }
        },
    }
    p = tmp_path / "region_profiles.json"
    p.write_text(json.dumps(old), encoding="utf-8")

    monkeypatch.setattr(siting, "PROFILE_PATH", p)
    siting._bake_file.cache_clear()
    siting.profiles.cache_clear()
    try:
        out = siting.profiles("observed")
        assert out["_meta"]["loaded_from"] == "baked"
        assert "28" in out["profiles"]
        assert siting.bake_status()["horizons"] == {"observed": 1}
    finally:
        # Restore the real cache for every test after this one.
        siting._bake_file.cache_clear()
        siting.profiles.cache_clear()


# --------------------------------------------------------------------------- #
# Nothing heavy inside a request
# --------------------------------------------------------------------------- #
def test_classify_is_memoised_on_its_site_list():
    a = siting.classify()
    b = siting.classify()
    assert a is b, "the 18,157-row surface must not be rebuilt per request"
    c = siting.classify(extra_sites=[(0.5, 46.6)])
    assert c is not a, "a different site list is a different surface"
    assert siting.classify(extra_sites=((0.5, 46.6),)) is c, "list and tuple must agree"


def test_food_demand_is_instant_on_every_horizon(client):
    """Each horizon, twice. The second call proves the response itself is cached."""
    covered = set(siting.bake_status()["horizons"])
    for h in climate.horizon_keys():
        if h not in covered:
            continue
        t0 = time.perf_counter()
        r = client.get(f"{BASE}/food-demand", params={"climate_horizon": h})
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["climate_horizon"] == h
        assert d["regions"], f"{h} returned no regions"
        # Generous against CI jitter, but two orders of magnitude under the 71 s the
        # live path cost on a projected horizon.
        assert elapsed < 5.0, f"{h} took {elapsed:.1f} s; is it baked?"


def test_the_food_response_is_served_from_cache_not_recomputed(client):
    client.get(f"{BASE}/food-demand", params={"climate_horizon": "observed"})
    t0 = time.perf_counter()
    r = client.get(f"{BASE}/food-demand", params={"climate_horizon": "observed"})
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    # Serialising the payload is the only work left on a warm cache.
    assert elapsed < 1.0, f"a warm food-demand request took {elapsed:.2f} s"


def test_regional_overview_reports_its_own_serve_time_not_the_cached_one(client):
    """`compute_ms` has to describe THIS request, or it is just a stale constant."""
    client.get(f"{BASE}/regional-overview")
    d = client.get(f"{BASE}/regional-overview").json()
    assert d["compute_ms"] < 50, (
        f"warm regional-overview reported {d['compute_ms']} ms; "
        "compute_ms is probably frozen at the cache-populating call"
    )
    assert len(d["departments"]) >= 38


def test_health_exposes_what_is_cached(client):
    d = client.get("/health").json()
    assert "profile_bake" in d
    assert d["profile_bake"]["present"] is True
    assert "observed" in d["profile_bake"]["horizons"]
    # The warm-up list is what makes a slow first request diagnosable.
    assert any(w.startswith("food-demand:") for w in d["warmed"]), d["warmed"]
    assert "regional-overview" in d["warmed"]
