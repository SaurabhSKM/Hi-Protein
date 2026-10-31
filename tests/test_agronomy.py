"""The agronomic rules are the part a farmer can get hurt by, so they are pinned."""
from app.services import agronomy as ag


def test_aphanomyces_blocks_lentil_after_pea():
    """The interval applies across the HOST GROUP, not just the same species."""
    v = ag.validate(
        "green_lentil", history=["soft_wheat", "field_pea", "spring_barley"],
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        soil_type="deep_loam", soil_ph=None,
    )
    assert v.is_valid is False
    assert v.severity == "blocked"
    assert v.observed_gap_years == 2
    assert v.return_interval_years >= 6
    assert any("Aphanomyces" in r for r in v.blocking_reasons)


def test_long_gap_is_allowed():
    v = ag.validate(
        "green_lentil",
        history=["field_pea", "soft_wheat", "rapeseed", "soft_wheat", "winter_barley", "soft_wheat"],
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
        soil_type="deep_loam", soil_ph=None,
    )
    assert v.is_valid is True
    assert v.observed_gap_years == 6


def test_acid_waterlogged_soil_blocks_pea():
    v = ag.validate(
        "field_pea", history=["soft_wheat"], baseline_rotation=["soft_wheat"],
        soil_type="boulbene", soil_ph=None,
    )
    assert v.is_valid is False
    assert any("pH" in r for r in v.blocking_reasons)


def test_deep_clay_blocks_lentil_but_limestone_does_not():
    kw = dict(
        history=["soft_wheat", "rapeseed", "soft_wheat", "winter_barley", "soft_wheat", "rapeseed"],
        baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"], soil_ph=None,
    )
    assert ag.validate("green_lentil", soil_type="deep_clay", **kw).is_valid is False
    assert ag.validate("green_lentil", soil_type="shallow_limestone", **kw).is_valid is True


def test_required_interval_uses_disease_group_not_species():
    assert ag.required_interval("green_lentil") >= 6  # pulled up by the pea group
    assert ag.required_interval("fava_bean") == 4


def test_preceding_crop_suitability_penalises_legume_before_legume():
    assert ag.suitability_multiplier("field_pea", "soft_wheat") == 1.0
    assert ag.suitability_multiplier("field_pea", "field_pea") < 0.6


def test_fallow_conversion_warns_about_bcae8():
    """Fallow counts toward the BCAE 8 non-productive requirement; a legume does not."""
    v = ag.validate(
        "field_pea", history=["fallow", "fallow"],
        baseline_rotation=["soft_wheat", "fallow", "rapeseed"],
        soil_type="deep_loam", soil_ph=None,
    )
    assert v.is_valid is True
    assert any("BCAE 8" in w for w in v.warnings)


def test_fallow_is_a_good_preceding_crop():
    """No shared pathogen, clean seedbed, a season of weed biomass mineralising."""
    assert ag.suitability_multiplier("field_pea", "fallow") > 1.0
    assert ag.suitability_multiplier("green_lentil", "fallow") > 1.0


def test_unnamed_legume_in_history_still_blocks_a_pea():
    """An RPG PAG declaration two campaigns ago must block pea and lentil.

    This is the cautious reading of a missing genus label: Aphanomyces has no
    chemical control and decade-long inoculum persistence, so a plot is not cleared
    on the strength of an absent crop name. Before PAG was mapped, this exact
    history looked clean.
    """
    hist = ["soft_wheat", "other_legume", "winter_barley"]
    kw = dict(baseline_rotation=["soft_wheat", "spring_barley", "rapeseed"],
              soil_type="deep_loam", soil_ph=None)
    assert ag.validate("field_pea", history=hist, **kw).severity == "blocked"
    assert ag.validate("green_lentil", history=hist, **kw).severity == "blocked"
    # Different disease groups, so these stay clear.
    assert ag.validate("fava_bean", history=hist, **kw).is_valid is True
    assert ag.validate("chickpea", history=hist, **kw).is_valid is True


def test_other_legume_is_an_aphanomyces_host():
    assert "other_legume" in ag.rules()["disease_groups"]["aphanomyces"]["host_crops"]
