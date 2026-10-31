"""Deterministic agronomic rule engine (Terres Inovia style screening).

The correction that matters here versus a naive per-species rule: soil-borne
disease return intervals apply across the whole HOST GROUP, not the single
species. Aphanomyces euteiches carries over between pea, lentil and alfalfa, so
"lentil after pea" must be flagged exactly as hard as "pea after pea".
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..config import crop, crops, rules, soils
from ..schemas import AgronomicValidation, Provenance

_HYDRO_RANK = {"very_low": 0, "low": 1, "medium": 2, "high": 3}
_TOLERANCE_RANK = {"very_low": 0, "low": 1, "medium": 2, "high": 3}


def _disease_group_for(crop_key: str) -> tuple[str | None, dict]:
    rr = rules()["disease_groups"]
    spec = crop(crop_key)
    gname = spec.get("disease_group")
    if gname and gname in rr:
        return gname, rr[gname]
    for name, grp in rr.items():
        if crop_key in grp.get("host_crops", []):
            return name, grp
    return None, {}


def required_interval(crop_key: str) -> int:
    """Minimum years between two host crops of this crop's disease group."""
    _, grp = _disease_group_for(crop_key)
    if grp:
        return int(grp.get("min_return_interval_years", crop(crop_key)["return_interval_years"]))
    return int(crop(crop_key)["return_interval_years"])


def _gap_to_last_host(history: list[str], crop_key: str) -> tuple[int | None, str | None]:
    """Years since the most recent host (or partial host) of the disease group.

    `history` is ordered oldest first, most recent LAST, one entry per campaign.
    A gap of 1 means the host was grown in the immediately preceding campaign.
    """
    _, grp = _disease_group_for(crop_key)
    hosts = set(grp.get("host_crops", [])) | {crop_key}
    partials = set(grp.get("partial_hosts", []))
    for offset, past in enumerate(reversed(history), start=1):
        if past in hosts:
            return offset, past
        if past in partials:
            return offset, past
    return None, None


def validate(
    crop_key: str,
    *,
    history: list[str] | None,
    baseline_rotation: list[str],
    soil_type: str,
    soil_ph: float | None,
    irrigated: bool = False,
) -> AgronomicValidation:
    spec = crop(crop_key)
    rr = rules()
    soil = soils()[soil_type]
    ph = soil_ph if soil_ph is not None else soil["ph"]

    gname, grp = _disease_group_for(crop_key)
    interval = required_interval(crop_key)

    hist = list(history or [])
    gap, last_host = _gap_to_last_host(hist, crop_key)

    blocking: list[str] = []
    warnings: list[str] = []

    # --- return interval ---------------------------------------------------
    if gap is not None and gap < interval:
        partials = set(grp.get("partial_hosts", []))
        is_partial = last_host in partials
        eff = int(grp.get("partial_host_interval_years", interval)) if is_partial else interval
        if gap < eff:
            msg = (
                f"{spec['label_fr']} would return only {gap} year(s) after "
                f"{crops()[last_host]['label_fr'] if last_host in crops() else last_host}, "
                f"a host of {grp.get('pathogen', gname)}. Minimum interval is {eff} years."
            )
            if grp.get("severity") == "high":
                blocking.append(msg)
            else:
                warnings.append(msg)

    # --- soil pH -----------------------------------------------------------
    ph_min, ph_max = spec.get("soil_ph_min"), spec.get("soil_ph_max")
    if ph_min is not None and ph < ph_min:
        blocking.append(
            f"Soil pH {ph:.1f} is below the {ph_min:.1f} minimum for {spec['label_fr']}; "
            "nodulation and therefore nitrogen fixation will be poor without liming."
        )
    if ph_max is not None and ph > ph_max:
        warnings.append(
            f"Soil pH {ph:.1f} is above {ph_max:.1f}; expect iron-deficiency chlorosis risk."
        )

    # --- hydromorphy -------------------------------------------------------
    tol = spec.get("hydromorphy_tolerance")
    if tol is not None and (
        _HYDRO_RANK.get(soil["hydromorphy"], 1) > _TOLERANCE_RANK.get(tol, 1)
    ):
            msg = (
                f"{soil['label_fr']} has {soil['hydromorphy']} hydromorphy while "
                f"{spec['label_fr']} tolerates only {tol}. Waterlogging at emergence is "
                "the most common cause of total crop failure here."
            )
            if _HYDRO_RANK.get(soil["hydromorphy"], 1) - _TOLERANCE_RANK.get(tol, 1) >= 2:
                blocking.append(msg)
            else:
                warnings.append(msg)

    # --- drought / shallow soil -------------------------------------------
    ru = soil["reserve_utile_mm"]
    if ru < 90 and spec.get("drought_sensitivity") in {"high", "medium"} and not irrigated:
        warnings.append(
            f"Plant-available water capacity is only {ru:.0f} mm. {spec['label_fr']} is "
            f"{spec['drought_sensitivity']}ly drought sensitive; yields will be volatile "
            "without irrigation."
        )
    if spec.get("needs_irrigation") and not irrigated:
        warnings.append(
            f"{spec['label_fr']} normally requires irrigation in France; a rain-fed crop "
            "carries a materially higher failure probability than the model's median."
        )

    # --- stoniness, relevant to low-cut harvest ---------------------------
    if crop_key in {"green_lentil", "chickpea"} and soil["stoniness_pct"] > 15:
        warnings.append(
            f"Stoniness {soil['stoniness_pct']:.0f}% complicates the very low cutting height "
            "that lentil and chickpea harvest requires; budget for a flexible cutter bar."
        )

    # --- preceding crop ----------------------------------------------------
    preceding = hist[-1] if hist else (baseline_rotation[0] if baseline_rotation else None)
    suit_table = rr["preceding_crop_suitability"].get(crop_key, {})
    suitability = suit_table.get(preceding) if preceding else None
    if suitability is not None and suitability < 0.85:
        warnings.append(
            f"{crops().get(preceding, {}).get('label_fr', preceding)} is a mediocre preceding "
            f"crop for {spec['label_fr']} (suitability {suitability:.2f}); the yield "
            "expectation below already carries this penalty."
        )

    # BCAE 8 of the PAC 2023-2027 requires a share of non-productive area. Fallow
    # counts toward it and a grain legume explicitly does not, so converting idle land
    # is the cheapest move agronomically and a compliance problem administratively.
    if preceding == "fallow" or "fallow" in hist:
        warnings.append(
            "This land is declared fallow. A pulse planted here displaces no crop "
            "margin, which is why the economics look strong, but fallow counts toward "
            "the BCAE 8 non-productive area requirement and a grain legume does not. "
            "Check the farm still meets BCAE 8 before converting."
        )

    window = rr["sowing_windows"].get(crop_key)
    sowing = None
    if window:
        sowing = f"Sow {window['start']} to {window['end']}. {window['note_fr']}"

    severity = "blocked" if blocking else ("caution" if warnings else "ok")
    note_bits: list[str] = []
    if preceding:
        note_bits.append(
            f"Preceding crop: {crops().get(preceding, {}).get('label_fr', preceding)}."
        )
    if sowing:
        note_bits.append(sowing)
    if gname and grp:
        if gap is None:
            note_bits.append(
                f"No {grp.get('pathogen', gname)} host found in the recorded history: low risk."
            )
        else:
            note_bits.append(
                f"Last {grp.get('pathogen', gname)} host {gap} year(s) ago; "
                f"{interval} years required."
            )
        if gname == "aphanomyces":
            note_bits.append(rr["disease_groups"]["aphanomyces"]["note"])

    return AgronomicValidation(
        is_valid=not blocking,
        severity=severity,
        return_interval_years=interval,
        observed_gap_years=gap,
        terres_inovia_note=" ".join(note_bits),
        sowing_window=sowing,
        blocking_reasons=blocking,
        warnings=warnings,
        disease_group=gname,
        preceding_crop=preceding,
        preceding_crop_suitability=suitability,
        provenance=Provenance(
            source="Terres Inovia crop return intervals and soil suitability guidance (Cap Proteines+)",
            mode="reference_table",
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            caveat=(
                "Screening aid only. A soil Aphanomyces test is the only reliable way to clear "
                "a plot for pea, and no rule table substitutes for a field visit."
            ),
        ),
    )


def suitability_multiplier(crop_key: str, preceding: str | None) -> float:
    table = rules()["preceding_crop_suitability"].get(crop_key, {})
    if preceding is None:
        return 1.0
    return float(table.get(preceding, 0.95))
