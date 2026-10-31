"""Frozen request/response contract.

Superset of the blueprint Section 6 schema: every original field name is kept so a
client written against the frozen contract keeps working, with added blocks for the
risk metrics, provenance and uncertainty that the original schema omitted.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SoilType = Literal[
    "deep_loam", "clay_loam", "deep_clay", "shallow_limestone", "sandy", "boulbene"
]
CarbonConvention = Literal["with_luc", "without_luc"]


class Provenance(BaseModel):
    """Where a number came from, so the UI never presents a guess as a measurement."""

    model_config = ConfigDict(extra="forbid")

    source: str
    mode: Literal["live_api", "cached", "reference_table", "model_output", "assumption"]
    retrieved_at: str | None = None
    caveat: str | None = None


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class SimulateRotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_code: str = Field(..., examples=["28"])
    parcel_id: str | None = Field(default=None, examples=["RPG-28-09412"])
    area_ha: float = Field(..., gt=0, le=10000, examples=[45.0])
    soil_type: SoilType = "deep_loam"
    soil_ph: float | None = Field(default=None, ge=3.5, le=9.5)
    has_livestock_ugb_5: bool = False
    irrigated: bool = False
    has_cover_crop: bool = True
    baseline_rotation: list[str] = Field(
        ..., min_length=3, max_length=3, examples=[["soft_wheat", "spring_barley", "rapeseed"]]
    )
    candidate_pulse_year2: str = Field(..., examples=["green_lentil"])
    crop_history: list[str] | None = Field(
        default=None,
        description="Crops grown on the parcel, most recent LAST. Used for return-interval checks.",
    )
    n_simulations: int | None = Field(default=None, ge=200, le=20000)
    selected_buyer_id: str | None = None
    carbon_convention: CarbonConvention = "with_luc"
    random_seed: int | None = None

    @field_validator("department_code")
    @classmethod
    def _dept(cls, v: str) -> str:
        v = v.strip().zfill(2)
        if not (v.isdigit() or v.upper().startswith("2A") or v.upper().startswith("2B")):
            raise ValueError("department_code must be a French department code, e.g. '28'")
        return v


class ParcelLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lon: float = Field(..., ge=-5.5, le=9.8)
    lat: float = Field(..., ge=41.0, le=51.5)
    years: list[int] | None = Field(default=None, description="RPG campaign years to query.")


# --------------------------------------------------------------------------- #
# Response blocks
# --------------------------------------------------------------------------- #
class AgronomicValidation(BaseModel):
    is_valid: bool
    severity: Literal["ok", "caution", "blocked"]
    return_interval_years: int
    observed_gap_years: int | None
    terres_inovia_note: str
    sowing_window: str | None = None
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disease_group: str | None = None
    preceding_crop: str | None = None
    preceding_crop_suitability: float | None = None
    provenance: Provenance


class MLPredictions(BaseModel):
    yield_q15_t_ha: float
    yield_median_t_ha: float
    yield_q85_t_ha: float
    prob_human_grade: float
    prob_human_grade_q15: float
    prob_human_grade_q85: float
    human_grade_fraction_median: float
    expected_protein_pct: float | None = None
    top_drivers: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str
    provenance: Provenance


class GainBreakdown(BaseModel):
    pac_coupled_aid_eur: float
    eco_scheme_uplift_eur: float
    nitrogen_saved_year3_eur: float
    wheat_yield_boost_year3_eur: float
    pulse_gross_revenue_eur: float
    pulse_operational_cost_eur: float
    forgone_baseline_year2_margin_eur: float
    on_farm_feed_substitution_eur: float


class RiskMetrics(BaseModel):
    prob_pulse_beats_baseline: float
    median_delta_eur_ha: float
    delta_q15_eur_ha: float
    delta_q85_eur_ha: float
    cvar_5pct_delta_eur_ha: float
    prob_delta_below_minus_100_eur_ha: float
    breakeven_human_grade_fraction: float | None
    worst_case_delta_eur_ha: float


class Financial3Yr(BaseModel):
    baseline_3yr_net_margin_eur: float
    pulse_rotation_median_eur: float
    pulse_rotation_worst_case_q15_eur: float
    baseline_3yr_q15_eur: float
    baseline_3yr_q85_eur: float
    pulse_rotation_q85_eur: float
    breakdown_year2_year3_gains: GainBreakdown
    risk: RiskMetrics
    cumulative_margin_fan: list[dict[str, Any]]
    n_simulations: int
    provenance: Provenance


class EnvironmentalImpact(BaseModel):
    co2e_saved_tons_total: float
    co2e_saved_tons_q15: float
    co2e_saved_tons_q85: float
    co2e_saved_per_kg_protein: float
    synthetic_n_reduced_kg_total: float
    co2e_from_n_avoided_tons: float
    convention: CarbonConvention
    co2e_saved_tons_other_convention: float
    carbon_abatement_cost_eur_per_tonne: float | None = Field(
        default=None,
        description=(
            "Whole-parcel 3-year financial delta divided by tons of CO2e avoided. "
            "Positive: this many EUR of farm income is given up per tonne of CO2e "
            "avoided, a real abatement cost comparable to an EU ETS or voluntary "
            "credit price. Negative: the rotation already pays for itself AND cuts "
            "carbon, the strongest case a pitch can make. Null when no CO2e is saved."
        ),
    )
    source: str
    provenance: Provenance


class OfftakeContract(BaseModel):
    buyer_id: str
    buyer_name: str
    grade: str
    contract_price_eur_t: float | None
    fallback_feed_price_eur_t: float | None
    floor_guaranteed: bool
    distance_km: float | None
    expected_revenue_eur_ha: float
    expected_revenue_q15_eur_ha: float
    premiums_applied: dict[str, float] = Field(default_factory=dict)
    quality_fit: Literal["comfortable", "tight", "at_risk"]
    optical_sorting_access: bool | None = None
    match_score: float
    notes: str | None = None


class SovereigntyContribution(BaseModel):
    department_code: str
    department_name: str
    current_pulse_share_pct: float
    share_after_this_parcel_pct: float
    parcel_share_of_dept_gap_pct: float
    national_target_pct: float


class SimulateRotationResponse(BaseModel):
    crop_recommended: str
    crop_label_fr: str
    area_ha: float
    agronomic_validation: AgronomicValidation
    ml_predictions_year2: MLPredictions
    financial_3yr_comparison_per_ha: Financial3Yr
    financial_3yr_whole_parcel_eur: dict[str, float]
    environmental_impact: EnvironmentalImpact
    matched_offtake_contracts: list[OfftakeContract]
    sovereignty: SovereigntyContribution
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    compute_ms: float = 0.0


class RankCandidatesResponse(BaseModel):
    department_code: str
    soil_type: str
    ranked: list[dict[str, Any]]
    compute_ms: float = 0.0


class ParcelFeature(BaseModel):
    year: int
    id_parcel: str | None
    surf_parc_ha: float | None
    code_cultu: str | None
    code_group: str | None
    crop_label: str | None
    mapped_crop: str | None
    is_fallow: bool = False


class ParcelLookupResponse(BaseModel):
    found: bool
    department_code: str | None
    geometry: dict[str, Any] | None
    surface_ha: float | None
    history: list[ParcelFeature]
    inferred_rotation: list[str]
    inferred_soil_type: str | None
    provenance: Provenance


class DepartmentOverview(BaseModel):
    department_code: str
    name: str
    region_name: str
    centroid: list[float]
    arable_ha: float
    pulse_ha: float
    pulse_share_pct: float
    target_share_pct: float
    gap_ha: float
    best_pulse: str
    median_margin_gain_eur_ha: float
    prob_gain_positive: float
    conversion_potential_eur: float
    has_optical_sorting_within_80km: bool
    dominant_soil: str


class RegionalOverviewResponse(BaseModel):
    national_current_share_pct: float
    national_target_share_pct: float
    target_year: int
    departments: list[DepartmentOverview]
    total_gap_ha: float
    total_conversion_potential_eur: float
    compute_ms: float = 0.0


class DossierResponse(BaseModel):
    parcel_id: str | None
    generated_at: str
    department: str
    crop: str
    sections: list[dict[str, Any]]
    agronomic_checklist: list[dict[str, Any]]
    financial_summary: dict[str, Any]
    disclaimer: str
