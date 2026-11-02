"""The fallback contract with a neighbouring livestock holding, pinned as tests.

The product claim is narrow and has to stay narrow: a downgraded food-grade lot is worth
more to a livestock holding within haulage distance than it is on the commodity feed
market, because that holding is otherwise buying imported soybean meal. These tests
protect the arithmetic of that claim - including the parts that LIMIT it, which is where
a pitch is most likely to overreach.
"""
import numpy as np
import pytest
from app.services import breeders as B
from app.services import finance as F
from app.services import weather


def _sim(floor=None, **kw):
    dept = kw.pop("dept", "28")
    rng = np.random.default_rng(5)
    seasons = [weather.sample_seasons(dept, 800, rng) for _ in range(3)]
    state = rng.bit_generator.state
    rng2 = np.random.default_rng()
    rng2.bit_generator.state = state
    defaults = dict(
        dept=dept, soil="deep_loam",
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        pulse="field_pea", seasons=seasons, rng=rng2, preceding_crop="soft_wheat",
    )
    defaults.update(kw)
    return F.simulate(fallback_feed_floor_eur_t=floor, **defaults)


# --------------------------------------------------------------------------- #
# Pricing: both sides of the trade
# --------------------------------------------------------------------------- #
def test_substitution_value_exceeds_the_feed_spot_price():
    """Why the trade exists at all.

    A tonne of pulse replaces purchased protein meal AND purchased cereal, and avoids
    haulage and trader margin on both, so it is worth more inside a ration than the feed
    market pays for it.
    """
    for pulse in ("field_pea", "fava_bean", "green_lentil"):
        v = B.substitution_value_eur_t(pulse)
        assert v["substitution_value_eur_t"] > v["feed_spot_eur_t"]


def test_offered_price_sits_strictly_between_spot_and_substitution_value():
    """Neither side is given the whole surplus, and neither side is hidden.

    A quoted price at or above the substitution value would mean the breeder pays more
    than the lot is worth to them; at or below spot it would mean the farmer gains
    nothing over simply selling to the feed market.
    """
    for pulse in ("field_pea", "fava_bean", "green_lentil"):
        p = B.offered_price_eur_t(pulse)
        assert p["feed_spot_eur_t"] < p["offered_price_eur_t"] < p["substitution_value_eur_t"]
        assert p["uplift_vs_spot_eur_t"] > 0
        assert p["breeder_margin_eur_t"] > 0


def test_chickpea_has_no_fallback_contract_worth_signing():
    """A limit of the mechanism, found by testing it rather than asserted around it.

    The reasoning changed once the non-GMO premium was wired in from `buyers.json`.
    Before, chickpea's feed spot price (~295 EUR/t) was at or ABOVE its ration value
    (~294), so no holding could outbid the market at all. With the premium the ration
    value rises to ~301 and a holding could outbid it - by 3.2 EUR/t.

    That is still not a contract. Below the stated 5 EUR/t transaction-cost floor the
    premium does not cover sampling, haulage terms and administration on both sides, so
    the engine reports no fallback rather than dressing 3 EUR/t up as de-risking. The
    conclusion survives better data; only the reason for it changed.
    """
    w = B.fallback_is_worth_signing("chickpea")
    assert not w["worth_signing"]
    assert B.fallback_floor_eur_t("chickpea", True) is None
    # It is now a transaction-cost argument, not an impossibility argument.
    assert 0 < w["uplift_vs_spot_eur_t"] < w["min_viable_uplift_eur_t"]
    assert "contract at all" in w["reason"]

    assert B.fallback_is_worth_signing("field_pea")["worth_signing"]
    assert B.fallback_floor_eur_t("field_pea", True) is not None


def test_the_transaction_cost_floor_is_a_named_parameter_not_a_magic_number():
    """It is a judgement about contracting overhead, so it has to be arguable."""
    rules = B.matching_rules()
    assert rules["min_viable_uplift_eur_t"] > 0
    assert "transaction costs" in rules["min_viable_uplift_note"]


def test_the_non_gmo_premium_is_shared_with_the_buyer_book_not_reinvented():
    """Two files must not carry two different answers to the same question.

    The premium is read out of buyers.json, where the project already quotes it, and
    weighted by the MEASURED share of the holding directory that buys non-GMO - a field
    that existed from the first build and that nothing read until now.
    """
    import json
    import pathlib

    v = B.substitution_value_eur_t("field_pea")
    buyers = json.loads(
        pathlib.Path("backend/app/refdata/buyers.json").read_text(encoding="utf-8")
    )
    quoted = next(
        (b["premiums"]["non_gmo_eur_t"] for b in buyers["buyers"]
         if (b.get("premiums") or {}).get("non_gmo_eur_t")),
        None,
    )
    assert quoted is not None
    assert v["non_gmo_premium_eur_t"] == quoted

    # Blended, not all-or-nothing: the share is counted off the directory.
    assert 0.0 < v["non_gmo_share_of_holdings"] < 1.0
    assert v["soybean_meal_standard_eur_t"] < v["soybean_meal_eur_t"]
    assert v["soybean_meal_eur_t"] == pytest.approx(
        v["soybean_meal_standard_eur_t"] + quoted * v["non_gmo_share_of_holdings"], abs=0.2
    )


def test_wiring_the_premium_in_raised_the_fallback_without_rescuing_the_bad_year():
    """The honest magnitude check, re-run after the improvement.

    Grounding the counterfactual in the premium the project already quotes raises the
    farmer's uplift, as it should. It does not come close to the 298 EUR/ha swing the
    project brief claimed, and the sensitivity audit shows nothing does.
    """
    floor = B.fallback_floor_eur_t("field_pea", True)
    without, with_c = _sim(floor=None), _sim(floor=floor)

    def cvar(sim):
        d = sim["delta"]
        return float(d[d <= np.quantile(d, 0.15)].mean())

    gain = cvar(with_c) - cvar(without)
    assert gain > 0
    assert gain < 150, "if this ever approaches 298 EUR/ha, re-read Chapter 7"


def test_the_surplus_split_adds_up():
    """The farmer's uplift and the breeder's margin must exhaust the surplus exactly."""
    p = B.offered_price_eur_t("field_pea")
    surplus = p["substitution_value_eur_t"] - p["feed_spot_eur_t"]
    assert p["uplift_vs_spot_eur_t"] + p["breeder_margin_eur_t"] == pytest.approx(
        surplus, abs=0.2
    )
    assert p["uplift_vs_spot_eur_t"] == pytest.approx(
        surplus * p["farmer_share_of_surplus"], abs=0.2
    )


def test_a_protein_rich_pulse_substitutes_more_soybean_meal():
    """Fava bean is 26.5 percent protein and field pea 22, so it displaces more meal."""
    fava = B.substitution_value_eur_t("fava_bean")
    pea = B.substitution_value_eur_t("field_pea")
    assert fava["a_soymeal"] > pea["a_soymeal"]


def test_import_substitution_is_protein_equivalent_not_tonne_for_tonne():
    """Soybean meal is 46 percent protein and a pulse is 20-26, so a tonne is not a tonne.

    Claiming tonne-for-tonne displacement would roughly double the headline, which is
    exactly the kind of flattering arithmetic the carbon module already refuses.
    """
    out = B.region_import_substitution("28", 100.0, "field_pea")
    assert out["imported_soybean_meal_displaced_t"] < 100.0
    assert out["imported_soybean_meal_displaced_t"] > 0.0


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
def test_holdings_outside_the_radius_are_dropped_not_stretched():
    rules = B.matching_rules()
    m = B.match(
        pulse="field_pea", dept_code="28", point=(1.5, 48.3), downgraded_lot_t=60.0
    )
    for match in m["matches"]:
        assert match["distance_km"] <= rules["max_haul_km"]


def test_a_near_miss_is_explained_rather_than_reported_as_nothing():
    """"Nearest holding is 26 km, radius is 25" is a different fact from "none exist".

    Reported because the first is a negotiable constraint and the second is not, and a
    user staring at an empty list cannot tell which they are looking at.
    """
    m = B.match(
        pulse="field_pea", dept_code="", point=(2.9, 42.6), downgraded_lot_t=50.0
    )
    assert "nearest_holding_km" in m
    if not m["available"]:
        assert m["nearest_holding_km"] is None or m["nearest_holding_km"] > m["radius_km"]


def test_inclusion_caps_are_enforced_so_a_big_lot_cannot_all_be_placed():
    """Raw pulses carry anti-nutritional factors; a herd cannot eat an unlimited share.

    The engine has to say when a lot is too big for its neighbours rather than quietly
    assuming an infinite local sink, which would be the easy way to make the fear-killer
    look stronger than it is.
    """
    small = B.match(
        pulse="field_pea", dept_code="28", point=(1.5, 48.3), downgraded_lot_t=5.0
    )
    huge = B.match(
        pulse="field_pea", dept_code="28", point=(1.5, 48.3), downgraded_lot_t=50000.0
    )
    if small["available"]:
        assert small["whole_lot_placeable"]
    if huge["available"]:
        assert not huge["whole_lot_placeable"]
        assert huge["placed_t"] < 50000.0
        assert not any(m["absorbs_whole_lot"] for m in huge["matches"])


def test_every_match_reports_what_the_breeder_gains():
    """The counterparty is not allowed to be an implied, costless sink."""
    m = B.match(
        pulse="field_pea", dept_code="28", point=(1.5, 48.3), downgraded_lot_t=40.0
    )
    for match in m["matches"]:
        assert match["breeder_avoided_soy_t"] >= 0
        assert match["breeder_avoided_soy_cost_eur"] >= 0
        assert match["ugb"] > 0
        assert match["max_pulse_intake_t"] > 0


def test_the_directory_declares_what_is_real_about_it():
    """A generated directory that did not say so would be the worst kind of claim."""
    from app.config import load_ref

    meta = load_ref("breeders")["_meta"]
    assert "ILLUSTRATIVE" in meta["status"]
    assert meta["what_is_real"] and meta["what_is_not_real"]
    assert meta["seed"]


def test_directory_covers_every_modelled_department():
    from app.config import departments, load_ref

    covered = {b["dept"] for b in load_ref("breeders")["breeders"]}
    assert set(departments()) <= covered


# --------------------------------------------------------------------------- #
# Effect on risk
# --------------------------------------------------------------------------- #
def test_the_fallback_floor_can_only_help_the_farmer():
    """It is a FLOOR, not a replacement.

    If the open feed market pays better in a given draw the farmer sells there, so no
    simulated path may ever be worse with the contract than without it.
    """
    floor = B.fallback_floor_eur_t("field_pea", True)
    without = _sim(floor=None)
    with_c = _sim(floor=floor)
    assert np.all(with_c["delta"] >= without["delta"] - 1e-6)
    assert float(np.median(with_c["delta"])) > float(np.median(without["delta"]))


def test_the_fallback_is_a_broad_uplift_not_concentrated_tail_insurance():
    """A correction to the obvious story, measured rather than assumed.

    The intuitive pitch is that this is downside insurance: a bad year downgrades more
    of the lot, the contract prices the downgraded fraction, so the value should
    concentrate in the left tail. Measured on 800 paths it does not. The loss tail is
    driven mostly by LOW YIELD, and a low-yield year has fewer tonnes to downgrade, so
    poor grading and poor yield offset each other almost exactly in downgraded tonnage -
    1.49 t/ha in the worst 15 percent against 1.54 t/ha overall.

    The result is a near-flat uplift of roughly 46 EUR/ha, marginally larger in the tail
    than on average. Real, and worth having, but it is a revenue floor rather than
    insurance, and the engine should not be allowed to drift into claiming otherwise.
    """
    floor = B.fallback_floor_eur_t("field_pea", True)
    without, with_c = _sim(floor=None), _sim(floor=floor)
    gain = with_c["delta"] - without["delta"]
    tail = without["delta"] <= np.quantile(without["delta"], 0.15)

    assert gain.mean() > 0
    assert gain[tail].mean() > 0
    # Tail gain at least as large as average, but not dramatically so.
    assert gain[tail].mean() >= gain.mean() * 0.95
    assert gain[tail].mean() <= gain.mean() * 1.5, (
        "if this ever becomes strongly tail-concentrated the narrative above needs "
        "rewriting, not the assertion loosening"
    )


def test_a_floor_below_the_spot_price_changes_nothing():
    """Guards the max(): a worthless contract must not be allowed to look like one."""
    without = _sim(floor=None)
    useless = _sim(floor=1.0)
    assert np.allclose(without["delta"], useless["delta"])


def test_the_api_block_reports_a_controlled_before_and_after():
    """Same draws, one difference. Otherwise the comparison is weather, not contract."""
    floor = B.fallback_floor_eur_t("field_pea", True)
    without, with_c = _sim(floor=None), _sim(floor=floor)
    out = B.summarise_for_api(
        pulse="field_pea", dept_code="28", point=None, downgraded_lot_t=60.0,
        sim_without=without, sim_with=with_c, crop_label="Pois proteagineux",
    )
    assert out["cvar_with_fallback_eur_ha"] > out["cvar_without_fallback_eur_ha"]
    assert out["cvar_improvement_eur_ha"] == pytest.approx(
        out["cvar_with_fallback_eur_ha"] - out["cvar_without_fallback_eur_ha"], abs=0.2
    )
    assert out["best_offered_price_eur_t"] > out["feed_spot_price_eur_t"]
    assert out["headline"]


def test_headline_states_the_magnitude_it_actually_found():
    """Prevents the obvious temptation: a fixed heroic sentence that the numbers deny."""
    small = B.headline(
        available=True, cvar_without=-120.0, cvar_with=-80.0, crop_label="Lentille"
    )
    assert "40" in small
    flip = B.headline(
        available=True, cvar_without=-240.0, cvar_with=58.0, crop_label="Lentille"
    )
    assert "GAINS" in flip
    none = B.headline(
        available=False, cvar_without=None, cvar_with=None, crop_label="Lentille",
        nearest_km=41.0, radius_km=25.0,
    )
    assert "41" in none and "25" in none
