"""Nitrogen carry-over must stay inside physically defensible bounds."""
import numpy as np
from app.services import nitrogen as N


def test_credit_scales_with_yield_but_sublinearly():
    lo = float(N.residue_n_credit("field_pea", 1.8, "deep_loam"))
    hi = float(N.residue_n_credit("field_pea", 3.6, "deep_loam"))
    assert lo < hi
    assert hi < 2.0 * lo  # damped, not proportional


def test_credit_never_exceeds_absolute_bound():
    v = N.residue_n_credit("fava_bean", 99.0, "deep_loam", autumn_winter_rain_mm=0.0)
    assert float(v) <= 70.0


def test_shallow_soil_mineralises_less_than_deep_loam():
    deep = float(N.residue_n_credit("field_pea", 3.6, "deep_loam"))
    shallow = float(N.residue_n_credit("field_pea", 3.6, "shallow_limestone"))
    assert shallow < deep


def test_wet_autumn_without_cover_crop_leaches_more():
    dry = float(N.residue_n_credit("field_pea", 3.6, "sandy", autumn_winter_rain_mm=180, has_cover_crop=True))
    wet = float(N.residue_n_credit("field_pea", 3.6, "sandy", autumn_winter_rain_mm=480, has_cover_crop=False))
    assert wet < dry


def test_saving_capped_at_share_of_wheat_dose():
    capped = float(N.capped_n_saving_kg(200.0, "soft_wheat"))
    assert capped <= 0.35 * 180.0 + 1e-6


def test_lentil_leaves_less_than_fava_bean():
    """Lentil produces little biomass, so its break-crop gain must be smaller."""
    lentil = float(N.following_yield_boost("green_lentil", 1.45))
    fava = float(N.following_yield_boost("fava_bean", 3.4))
    assert lentil < fava
    assert lentil <= 0.9 and fava <= 0.9


def test_failed_legume_delivers_less_boost():
    good = float(N.following_yield_boost("field_pea", 3.6))
    failed = float(N.following_yield_boost("field_pea", 0.9))
    assert failed < good


def test_n_price_draw_within_bounds():
    rng = np.random.default_rng(0)
    p = N.n_price_draw(rng, 5000)
    assert p.min() >= 0.70 and p.max() <= 2.60
