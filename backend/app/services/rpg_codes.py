"""Mapping from IGN RPG `code_cultu` / `code_group` to internal crop keys.

Verified against live responses from https://apicarto.ign.fr/api/rpg/v2 , whose
feature properties are: id_parcel, surf_parc, code_cultu, code_group,
culture_d1, culture_d2.

The RPG vocabulary is NOT stable across campaigns, which is the trap here. Checked
against the authoritative tables at
`https://data.geopf.fr/wfs/ows?TYPENAMES=RPG.<year>:codes_cultures`:

  2023  372 codes, with `code_groupe` present
  2024  147 codes, with `code_groupe` ABSENT

The 2024 campaign consolidated the vocabulary and dropped eight codes this module
relies on (BVF, CHA, FFO, J5M, J6S, LEF, MIE, PTF). Three of those map to a crop, so
on 2024 data they would silently stop matching rather than fail. Both vintages are
therefore mapped below, and `unmapped_codes()` exists so a year bump surfaces the
problem instead of quietly losing parcels.
"""
from __future__ import annotations

# Campaign years the API Carto RPG v2 endpoint answers for. 2010 returns HTTP 400.
SUPPORTED_YEARS = (2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015)

# Codes retired in the 2024 vocabulary, with their nearest 2024 equivalent where one
# exists. The forage variants and maize silage were folded into their parents.
RETIRED_IN_2024: dict[str, str | None] = {
    "BVF": None,   # betterave fourragere, folded into BTN
    "CHA": "CHV",  # chanvre renamed
    "FFO": None,   # feverole fourragere, folded into FVL
    "J5M": "JAC",  # jachere by age, replaced by JAC / JNO
    "J6S": "JAC",
    "LEF": None,   # lentille fourragere, folded into LEC
    "MIE": None,   # mais ensilage, folded into MIS
    "PTF": "PTC",  # pomme de terre feculiere, folded into PTC
}

CODE_CULTU_LABELS: dict[str, str] = {
    # --- cereals -----------------------------------------------------------
    "BTH": "Ble tendre d'hiver", "BTP": "Ble tendre de printemps",
    "BDH": "Ble dur d'hiver", "BDP": "Ble dur de printemps",
    "ORH": "Orge d'hiver", "ORP": "Orge de printemps",
    "AVH": "Avoine d'hiver", "AVP": "Avoine de printemps",
    "TTH": "Triticale d'hiver", "TTP": "Triticale de printemps",
    "SGH": "Seigle d'hiver", "EPE": "Epeautre",
    "MIS": "Mais", "MIE": "Mais ensilage", "SBO": "Sorgho",
    # --- oilseeds ----------------------------------------------------------
    "CZH": "Colza d'hiver", "CZP": "Colza de printemps",
    "TRN": "Tournesol", "SOJ": "Soja",
    "LIH": "Lin d'hiver", "LIP": "Lin de printemps",
    # --- grain legumes -----------------------------------------------------
    "PPR": "Pois proteagineux de printemps", "PHI": "Pois proteagineux d'hiver",
    "FVL": "Feverole", "FFO": "Feverole fourragere", "FVP": "Feverole de printemps",
    "LEC": "Lentille cultivee", "LEF": "Lentille fourragere",
    "PCH": "Pois chiche",
    "LDP": "Lupin doux de printemps", "LDH": "Lupin doux d'hiver",
    "PHS": "Pois et haricot secs (alimentation humaine)",
    "PHF": "Pois et haricot frais (alimentation humaine)",
    "MPC": "Melange de proteagineux (pois, lupin, feverole) et de cereales",
    "PAG": "Autre legumineuse a graines (genre non precise)",
    # --- forage legumes ----------------------------------------------------
    "LUZ": "Luzerne", "TRE": "Trefle", "SAI": "Sainfoin", "VES": "Vesce",
    "MLF": "Melange de legumineuses fourrageres",
    "MLC": "Melange legumineuses fourrageres preponderantes et cereales/oleagineux",
    "MLG": "Melange de legumineuses et de graminees fourrageres",
    "CPL": "Fourrage compose de cereales, proteagineux et legumineuses",
    "AFG": "Autre plante fourragere annuelle",
    # --- grassland and other ----------------------------------------------
    "PTR": "Prairie temporaire", "PPH": "Prairie permanente",
    "SPH": "Surface pastorale",
    "BTN": "Betterave non fourragere", "BVF": "Betterave fourragere",
    "PTC": "Pomme de terre de consommation", "PTF": "Pomme de terre feculiere",
    "J5M": "Jachere de 5 ans ou moins", "J6S": "Jachere de 6 ans ou plus",
    "JAC": "Jachere (terre arable)", "JNO": "Jachere noire",
    "SNE": "Surface agricole temporairement non exploitee",
    "CHA": "Chanvre", "CHV": "Chanvre", "CSE": "Chanvre sans etiquette conforme",
    "MOH": "Moha",
    # MLT is Millet, group 4 "Autres cereales", in the 2023 and 2024 tables alike.
    # It was mislabelled here as a legume-cereal mix. The actual legume mixes are
    # MLC / MLF / MLG (forage) and MPC (protein-cereal).
    "MLT": "Millet",
    "SOG": "Sorgho",
    # Sarrasin is a pseudo-cereal (Polygonaceae) and fixes no nitrogen. RPG files it
    # under group 4, "Autres cereales", NOT under proteagineux. It maps to no crop
    # here deliberately.
    "SRS": "Sarrasin",
    "CAG": "Autre cereale ou pseudo-cereale de printemps",
    "MCR": "Melange de cereales d'hiver",
    "MSW": "Culture perenne a forte biomasse (miscanthus, switchgrass)",
    "GRA": "Graminee pure pour gazon ou semences",
    # Vegetables. Present in real arable extracts but outside this engine's scope.
    "CAR": "Carotte", "OIG": "Oignon et echalote",
    "FLA": "Autre legume ou fruit annuel", "FLP": "Autre legume ou fruit perenne",
    "MDI": "Maraichage diversifie",
    # Non-productive features. These are what BCAE 8 counts, and grain legumes
    # explicitly do NOT substitute for them.
    "BOR": "Bordure de champ", "BTA": "Bande tampon",
    "BFS": "Bordure le long d'une foret sans production",
}

CODE_CULTU_TO_CROP: dict[str, str] = {
    "BTH": "soft_wheat", "BTP": "soft_wheat",
    "BDH": "durum_wheat", "BDP": "durum_wheat",
    "ORH": "winter_barley", "ORP": "spring_barley",
    "MIS": "grain_maize", "MIE": "grain_maize",
    "SBO": "grain_maize", "SOG": "grain_maize",
    "CZH": "rapeseed", "CZP": "rapeseed",
    "TRN": "sunflower",
    "SOJ": "soybean",
    "PPR": "field_pea", "PHI": "winter_pea",
    "PHS": "field_pea",
    "FVL": "fava_bean", "FFO": "fava_bean", "FVP": "fava_bean",
    "LEC": "green_lentil", "LEF": "green_lentil",
    "PCH": "chickpea",
    "LUZ": "alfalfa", "SAI": "alfalfa", "TRE": "alfalfa",
    "MLF": "alfalfa", "MLG": "alfalfa",
    # Fallow is a land USE, not a crop, but it has to reach the rotation history:
    # the BCAE 8 warning and the "nothing displaced" economics both depend on
    # knowing a campaign was idle. Dropping it silently lost that.
    "JAC": "fallow", "JNO": "fallow", "SNE": "fallow",
    "J5M": "fallow", "J6S": "fallow",
    # An unnamed grain legume. No yield or price can be predicted for it, but a past
    # declaration still has to count toward the Aphanomyces interval.
    "PAG": "other_legume", "MPC": "other_legume",
}

# Codes that mean "no crop is established here". Relevant because an idle hectare is
# the cheapest land to convert to a nitrogen-fixing legume: there is no standing crop
# whose margin the pulse has to beat.
FALLOW_CODES = frozenset({"J5M", "J6S", "JAC", "JNO", "SNE"})

# Non-productive features declared on arable land. BCAE 8 of the PAC 2023-2027
# requires a share of non-productive area, and a grain legume does not count toward
# it, so these hectares are not available for conversion.
NON_PRODUCTIVE_CODES = frozenset({"BOR", "BTA", "BFS", "GRA", "MSW"})


def is_non_productive(code_cultu: str | None) -> bool:
    return bool(code_cultu) and code_cultu.upper() in NON_PRODUCTIVE_CODES


# RPG `code_group` is the coarse crop group, used when code_cultu is unmapped.
#
# A correction worth recording, because the obvious inference is wrong: the 2024
# CODE TABLE (RPG.2024:codes_cultures) dropped `code_groupe`, but the 2024 PARCEL
# layer did not. RPG.2024:parcelles_graphiques still carries `code_group` on every
# feature (verified non-null on 100/100 sampled Beauce parcels, alongside a new
# `cat_cult_p` field). So this fallback keeps working on 2024 data; what is lost is
# only the human-readable `libelle_groupe`. The actual constraint here is simply that
# API Carto RPG v2 serves campaigns 2015-2023, so this client never sees 2024.
CODE_GROUP_TO_CROP: dict[str, str] = {
    "1": "soft_wheat", "2": "grain_maize", "3": "spring_barley", "4": "soft_wheat",
    "5": "rapeseed", "6": "sunflower", "7": "rapeseed", "8": "field_pea",
    # Group 11 is "Gel (surfaces gelees sans production)": set-aside and fallow. It is
    # arable land temporarily out of production, so it maps to fallow rather than
    # being discarded as non-arable.
    "11": "fallow",
    "15": "green_lentil", "16": "alfalfa", "19": "alfalfa",
}

# code_group values that are not arable rotation crops at all.
NON_ARABLE_GROUPS = frozenset(
    {"17", "18", "20", "21", "22", "23", "25", "26", "27", "28"}
)


def label_for(code_cultu: str | None) -> str | None:
    if not code_cultu:
        return None
    return CODE_CULTU_LABELS.get(code_cultu.upper(), code_cultu)


def crop_for(code_cultu: str | None, code_group: str | None = None) -> str | None:
    """Best-effort mapping of an RPG parcel declaration to an internal crop key."""
    if code_cultu:
        code = code_cultu.upper()
        hit = CODE_CULTU_TO_CROP.get(code)
        if hit:
            return hit
        # A retired code may have a live successor that is mapped.
        successor = RETIRED_IN_2024.get(code)
        if successor and successor in CODE_CULTU_TO_CROP:
            return CODE_CULTU_TO_CROP[successor]
    if code_group:
        g = str(code_group).strip()
        if g in NON_ARABLE_GROUPS:
            return None
        return CODE_GROUP_TO_CROP.get(g)
    return None


def is_fallow(code_cultu: str | None) -> bool:
    return bool(code_cultu) and code_cultu.upper() in FALLOW_CODES


def unmapped_codes(codes: list[str] | set[str]) -> list[str]:
    """Codes this module knows nothing about.

    Call it with the distinct `code_cultu` values of a real extract before trusting a
    new campaign year. It is the guard that turns a silent vocabulary change into a
    visible one.
    """
    known = set(CODE_CULTU_LABELS)
    return sorted({c.upper() for c in codes if c} - known)
