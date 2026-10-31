"""RPG vocabulary handling.

The RPG code list is not stable across campaigns: the 2024 table has 147 codes
against 372 in 2023 and drops eight this project relies on. These tests pin the
behaviour that keeps a year bump from silently losing parcels.
"""
from app.services import rpg_codes as R


def test_retired_2024_codes_still_resolve_through_their_successor():
    """FFO, LEF and MIE vanish in 2024; their parents must still answer."""
    assert R.crop_for("FFO") == "fava_bean"
    assert R.crop_for("LEF") == "green_lentil"
    assert R.crop_for("MIE") == "grain_maize"
    assert R.crop_for("PTF") is None  # potato is not a rotation crop here, but known
    assert "PTF" in R.CODE_CULTU_LABELS


def test_every_retired_code_is_still_labelled():
    for code in R.RETIRED_IN_2024:
        assert code in R.CODE_CULTU_LABELS, code


def test_2024_vocabulary_is_mapped():
    """Codes that only exist from 2024 onward."""
    assert R.crop_for("FVP") == "fava_bean"
    assert R.crop_for("PHS") == "field_pea"
    assert R.crop_for("PHI") == "winter_pea"
    assert R.crop_for("PPR") == "field_pea"
    for code in ("JAC", "JNO", "SNE", "CHV"):
        assert code in R.CODE_CULTU_LABELS, code


def test_fallow_and_non_productive_are_distinguished():
    """Idle land is the cheapest conversion target; BCAE 8 strips are not available."""
    assert R.is_fallow("JAC") and R.is_fallow("JNO") and R.is_fallow("J6S")
    assert not R.is_fallow("BTH")
    assert R.is_non_productive("BTA") and R.is_non_productive("BOR")
    assert not R.is_non_productive("JAC")


def test_fallow_reaches_the_inferred_rotation():
    """A fallow campaign must survive into the history, not be silently dropped.

    The BCAE 8 warning and the "nothing displaced" economics both depend on knowing a
    campaign was idle. An earlier version mapped these to None and lost it.
    """
    for code in ("JAC", "JNO", "SNE", "J5M", "J6S"):
        assert R.crop_for(code) == "fallow", code
    # Group 11 is "Gel (surfaces gelees sans production)", i.e. set-aside.
    assert R.crop_for("UNKNOWNCODE", "11") == "fallow"
    assert "11" not in R.NON_ARABLE_GROUPS


def test_buckwheat_is_not_treated_as_a_protein_crop():
    """Sarrasin is a pseudo-cereal in Polygonaceae and fixes no nitrogen.

    RPG files it under group 4, "Autres cereales", not under proteagineux.
    """
    assert R.CODE_CULTU_LABELS["SRS"] == "Sarrasin"
    assert R.crop_for("SRS") is None


def test_unmapped_codes_guard_flags_the_unknown():
    assert R.unmapped_codes(["BTH", "FVP", "JAC"]) == []
    assert R.unmapped_codes(["BTH", "ZZZ", "QQQ"]) == ["QQQ", "ZZZ"]


def test_codes_seen_in_real_beauce_extract_all_resolve():
    """The 37 distinct codes observed in 1,000 live RPG 2023 parcels in Beauce.

    Pinned as a literal so the test does not depend on the network.
    """
    observed = [
        "BTH", "ORH", "ORP", "CZH", "MIS", "TRN", "SOJ", "PPR", "PHI", "FVL",
        "LEC", "PCH", "LUZ", "TRE", "PTR", "PPH", "BTN", "PTC", "JAC", "JNO",
        "SNE", "J5M", "J6S", "BOR", "BTA", "BFS", "GRA", "MSW", "CAR", "OIG",
        "FLA", "CAG", "MCR", "SOG", "SRS", "EPE", "MLT",
    ]
    assert R.unmapped_codes(observed) == []


def test_non_arable_group_never_maps_to_a_crop():
    """A permanent-grassland group must not be read as an arable rotation entry."""
    assert R.crop_for(None, "18") is None
    assert R.crop_for("UNKNOWNCODE", "18") is None
    assert R.crop_for("UNKNOWNCODE", "1") == "soft_wheat"


def test_supported_years_excludes_2010_and_2024():
    """API Carto answers 2015-2023; 2010 returns HTTP 400 and 2024 is not served."""
    assert 2010 not in R.SUPPORTED_YEARS
    assert 2024 not in R.SUPPORTED_YEARS
    assert max(R.SUPPORTED_YEARS) == 2023
    assert min(R.SUPPORTED_YEARS) == 2015


def test_real_six_year_fallow_history_resolves():
    """A real Beauce parcel declared J6S every campaign from 2015 to 2020.

    Found live via API Carto, pinned here so the test needs no network.
    """
    history = ["J6S"] * 6
    assert R.unmapped_codes(history) == []
    assert [R.crop_for(c) for c in history] == ["fallow"] * 6
    assert all(R.is_fallow(c) for c in history)


def test_mlt_is_millet_not_a_legume_mix():
    """MLT is Millet in the 2023 and 2024 official tables, group 4 Autres cereales.

    It was mislabelled here as a legume-cereal mix in every vintage. The actual
    legume mixes are MLC / MLF / MLG (forage) and MPC (protein-cereal), so a wrong
    label here would have shown a user millet as a nitrogen-fixing precedent.
    """
    assert R.CODE_CULTU_LABELS["MLT"] == "Millet"
    assert R.crop_for("MLT") is None
    assert R.crop_for("MPC") == "other_legume"
    assert R.crop_for("MLF") == "alfalfa"


def test_unnamed_grain_legume_codes_reach_the_history():
    """PAG declares a grain legume without naming the genus.

    It cannot be priced or predicted, but a past declaration still has to count
    toward the Aphanomyces interval, so it must not be dropped.
    """
    assert R.crop_for("PAG") == "other_legume"
    assert R.CODE_CULTU_LABELS["PAG"].startswith("Autre legumineuse")


def test_code_tables_are_internally_consistent():
    """Guards the class of bug that a duplicate dict key hides.

    Every crop mapping must have a label, and every target must exist in the crop
    reference data, or the API returns a crop the rest of the engine cannot price.
    """
    from app.config import crops

    missing_label = [c for c in R.CODE_CULTU_TO_CROP if c not in R.CODE_CULTU_LABELS]
    assert missing_label == []

    bad_target = sorted({v for v in R.CODE_CULTU_TO_CROP.values() if v not in crops()})
    assert bad_target == []

    bad_group = sorted({v for v in R.CODE_GROUP_TO_CROP.values() if v not in crops()})
    assert bad_group == []

    # A code cannot be both a crop and a non-productive feature.
    assert not (set(R.CODE_CULTU_TO_CROP) & R.NON_PRODUCTIVE_CODES)
    # Every fallow code must map to the fallow land use, and nothing else may.
    assert {c for c, v in R.CODE_CULTU_TO_CROP.items() if v == "fallow"} == set(R.FALLOW_CODES)


def test_refdata_json_has_no_duplicate_keys():
    """json.loads silently keeps the last of a duplicated key, so check explicitly."""
    import json
    from pathlib import Path

    from app.config import REFDATA_DIR

    for f in sorted(Path(REFDATA_DIR).glob("*.json")):
        dupes: list[str] = []

        def hook(pairs, _d=dupes):
            seen: set[str] = set()
            for k, _v in pairs:
                if k in seen:
                    _d.append(k)
                seen.add(k)
            return dict(pairs)

        json.loads(f.read_text(encoding="utf-8"), object_pairs_hook=hook)
        assert dupes == [], f"{f.name}: duplicate keys {dupes}"
