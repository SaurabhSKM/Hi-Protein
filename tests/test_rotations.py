"""The baseline rotation a pulse is compared against.

The year-2 crop of the baseline rotation is the one the pulse displaces, and its
forgone margin is the largest single term in the three-year difference the engine
reports. It used to be a hard-coded constant in three code paths, unreachable from the
regional, food and climate tabs and absent from every sensitivity audit. Swapping that
one crop moved the median difference by -237 to +511 EUR/ha on test cases and flipped
the sign of the recommendation on three of eight.

These tests pin the two properties that keep the replacement honest:

1. The comparator comes from the department's own Agreste area shares, not a constant.
2. Every comparator is a crop the engine has a REAL yield baseline for, and where that
   differs from the department's most widely grown alternative, the response says so.
"""
import pytest
from app.config import crop, crops, departments
from app.services import ml, rotations


def test_every_department_resolves_to_a_three_crop_rotation():
    for code in departments():
        rot = rotations.baseline_rotation(code)
        assert len(rot) == 3, code
        for c in rot:
            assert c in crops(), (code, c)


def test_no_pulse_ever_appears_in_a_baseline_rotation():
    """A legume in the baseline would make the comparison a pulse-versus-pulse one and
    would also hand the baseline arm the eco-scheme diversification uplift."""
    for code in departments():
        for c in rotations.baseline_rotation(code):
            assert not crop(c).get("is_legume"), (code, c)


def test_displaced_crop_always_has_a_measured_yield_baseline():
    """The whole point of the derivation.

    A comparator resting on `crop_reference_table` is a hand-written national constant
    with no departmental signal - the same number in every department on a given soil.
    Since its margin dominates the result, a flat comparator would manufacture a
    department-to-department pattern that is an artefact of the fallback.
    """
    for code, d in departments().items():
        y2 = rotations.displaced_crop(code)
        _, src = ml.baseline_yield(y2, code, d["dominant_soil"])
        assert src != "crop_reference_table", (code, y2, src)


def test_year1_is_a_cereal_so_the_preceding_crop_table_applies():
    for code in departments():
        y1 = rotations.baseline_rotation(code)[0]
        assert crop(y1).get("family") == "cereal", (code, y1)


def test_the_rotation_is_derived_per_department_not_a_constant():
    """The derivation must be live, which is NOT the same as it disagreeing a lot.

    This test originally required fewer than half the departments to match the old
    hard-coded rotation. That stopped being the right check when year 2 changed from
    "largest remaining crop by area" to "least-profitable remaining cereal": the
    corrected rule reproduces the old constant in most departments, because spring
    barley genuinely IS the weakest priceable cereal nearly everywhere. Agreeing with
    the previous guess is a validation of that guess, not evidence the derivation died.

    So the check is now that the table is genuinely derived rather than falling back,
    and that it still disagrees somewhere - which is what would actually be lost if the
    derivation broke.
    """
    codes = list(departments())
    derived = {tuple(rotations.baseline_rotation(c)) for c in codes}
    assert len(derived) > 1, "every department got the same rotation"

    # Derived, not the legacy fallback path, for the large majority.
    sources = [rotations._table().get(c, {}).get("source") for c in codes]
    n_derived = sum(s == "agreste_department_area_share" for s in sources)
    assert n_derived > len(codes) * 0.8, f"only {n_derived}/{len(codes)} genuinely derived"

    # And it must still differ from the old constant somewhere, or the department
    # signal is doing no work at all.
    legacy = tuple(rotations.LEGACY_ROTATION)
    n_differ = sum(tuple(rotations.baseline_rotation(c)) != legacy for c in codes)
    assert n_differ >= 5, f"only {n_differ} departments differ from the old constant"


def test_year_two_is_the_weakest_cereal_not_the_biggest_crop():
    """The counterfactual that decides the whole regional map.

    Selecting the displaced crop by AREA put rapeseed in the year-2 slot across
    northern France, which collapsed the map from 21 profitable departments to 4. It is
    the wrong counterfactual twice over: a farmer giving a slot to a pulse drops their
    weakest crop, not their second-best one, and rapeseed is itself the break crop a
    pulse is meant to become - the two also share Sclerotinia sclerotiorum.
    """
    from app.config import crop

    offenders, forced = [], []
    for code in departments():
        rec = rotations._table().get(code) or {}
        if rec.get("source") != "agreste_department_area_share":
            continue
        y2 = rotations.displaced_crop(code)
        rot = rotations.baseline_rotation(code)
        # DISTINCT cereals: year 3 falls back to year 1 where no third crop qualifies,
        # so counting the list double-counts soft wheat.
        spare = {c for c in rot if crop(c).get("family") == "cereal" and c != rot[0]}
        if crop(y2).get("family") != "cereal":
            (offenders if spare else forced).append((code, y2))

    # An oilseed may only occupy the displaced slot when there is no spare cereal.
    assert not offenders, f"oilseed displaced despite a spare cereal: {offenders}"

    # Where it IS forced, it must be disclosed - a pulse measured against the break
    # crop is a harsher comparison than elsewhere, and six departments are in that
    # position because spring barley falls below the minimum slot share.
    assert forced, "expected some departments with only one priceable cereal"
    for code, _y2 in forced:
        cav = rotations.caveat(code)
        assert cav, f"{code}: oilseed comparator with no caveat"
        assert "break crop" in cav, code


def test_caveat_fires_exactly_when_something_is_worth_disclosing():
    """Honesty check: the warning must not be decorative, and must not be missing.

    The caveat has TWO independent triggers, and this test originally knew only the
    first:

      1. the department's dominant alternative crop has no yield series, so the
         comparator is the best-evidenced crop rather than the most grown one;
      2. the department has only one priceable cereal, so the pulse is measured against
         its OILSEED break crop - a harsher comparison, and one that sits badly
         agronomically since a pulse is meant to become the break crop.

    Trigger 2 was added when the displaced-crop rule changed from "largest by area" to
    "weakest spare cereal". Before that fix rapeseed was displaced nearly everywhere by
    design, so there was nothing distinctive to flag; now it happens in six departments
    and Haut-Rhin was getting no warning at all.
    """
    flagged, silent = [], []
    for code, d in departments().items():
        c = rotations.caveat(code)
        rec = rotations._table().get(code, {})
        has_gap = "dominant_alternative_not_priceable" in rec
        y2 = rotations.displaced_crop(code)
        forced_oilseed = crop(y2).get("family") == "oilseed"

        if has_gap:
            assert c, code
            gap = rec["dominant_alternative_not_priceable"]
            # Named by its French label, as every other caveat in the API does.
            assert crop(gap["crop"])["label_fr"] in c, code
            # The flagged crop must genuinely be unpriceable here.
            _, src = ml.baseline_yield(gap["crop"], code, d["dominant_soil"])
            assert src == "crop_reference_table", (code, gap["crop"], src)
            flagged.append(code)
        elif forced_oilseed:
            assert c and "break crop" in c, code
            flagged.append(code)
        else:
            assert c is None, (code, c)
            silent.append(code)
    # Both branches must be exercised, or this test is only checking one of them.
    assert flagged and silent


def test_provenance_states_the_displaced_crop_and_its_area_share():
    p = rotations.provenance("21")
    assert p["displaced_year2_crop"] == p["baseline_rotation"][1]
    assert p["source"] == "agreste_department_area_share"
    assert p["displaced_year2_crop"] in p["area_share_pct"]
    assert 0 < p["rotation_coverage_pct"] <= 100


def test_unknown_department_falls_back_rather_than_raising():
    assert rotations.baseline_rotation("ZZ") == rotations.LEGACY_ROTATION


@pytest.mark.parametrize("dept", ["21", "28", "45", "91"])
def test_derived_rotation_runs_through_the_whole_engine(dept):
    """The rotation has to be simulable, not merely well-formed."""
    from app.schemas import SimulateRotationRequest
    from app.services import orchestrator

    d = departments()[dept]
    req = SimulateRotationRequest(
        department_code=dept, area_ha=40.0, soil_type=d["dominant_soil"],
        baseline_rotation=rotations.baseline_rotation(dept),
        candidate_pulse_year2="field_pea", n_simulations=300, random_seed=7,
    )
    r = orchestrator.run(req)
    assert r.financial_3yr_comparison_per_ha.risk.median_delta_eur_ha is not None
    # The displaced crop must be named in the assumptions, because a reader cannot
    # judge the number without knowing what it was compared against.
    y2_label = crops()[rotations.displaced_crop(dept)]["label_fr"]
    assert any(y2_label in a for a in r.assumptions), r.assumptions


def test_a_weak_comparator_is_flagged_loudly_on_the_farmer_path():
    """Winter barley has no yield series, so choosing it must warn - it used to be
    silent, because `ml.baseline_caveat` was only ever applied to the pulse."""
    from app.schemas import SimulateRotationRequest
    from app.services import orchestrator

    req = SimulateRotationRequest(
        department_code="21", area_ha=40.0, soil_type="shallow_limestone",
        baseline_rotation=["soft_wheat", "winter_barley", "rapeseed"],
        candidate_pulse_year2="winter_pea", n_simulations=300, random_seed=7,
    )
    r = orchestrator.run(req)
    assert any("WEAK COMPARATOR" in a for a in r.assumptions), r.assumptions
