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

# Forward climate horizons. `observed` is the default and reproduces every number the
# engine published before projections existed, so adding this option changes nothing
# unless a caller asks. See refdata/climate_projection.json and services/climate.py.
ClimateHorizon = Literal[
    "observed", "present", "tracc_2030", "tracc_2050", "tracc_2100"
]


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
    # Supplied when the user clicked a real RPG parcel. Haulage distance to the
    # nearest optical sorter is measured from here when present, and from the
    # department centroid when it is not.
    lon: float | None = Field(default=None, ge=-5.5, le=9.8)
    lat: float | None = Field(default=None, ge=41.0, le=51.5)
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
    climate_horizon: ClimateHorizon = "observed"
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
    sorter_haulage_cost_eur: float = 0.0


class RiskMetrics(BaseModel):
    prob_pulse_beats_baseline: float
    median_delta_eur_ha: float
    delta_q15_eur_ha: float
    delta_q85_eur_ha: float
    cvar_5pct_delta_eur_ha: float
    prob_delta_below_minus_100_eur_ha: float
    breakeven_human_grade_fraction: float | None
    worst_case_delta_eur_ha: float
    # Whether the SIGN of this verdict survives the two assumptions a sensitivity
    # audit showed can flip it. A single number reads as a fact; this says when it
    # is one reading among several.
    robustness: dict[str, Any] = Field(default_factory=dict)


class RiskPreference(BaseModel):
    """Applies a risk attitude, rather than only describing the distribution.

    `RiskMetrics` above measures risk; this block prices it. Method is stochastic
    efficiency with respect to a function (SERF), Hardaker et al. (2004).
    """

    method: str
    wealth_anchor_eur_ha: float
    risk_sharing: dict[str, Any]
    serf_curve: list[dict[str, Any]]
    tolerance_threshold: dict[str, Any]
    minimum_viable_contract: dict[str, Any]


class Financial3Yr(BaseModel):
    baseline_3yr_net_margin_eur: float
    pulse_rotation_median_eur: float
    pulse_rotation_worst_case_q15_eur: float
    baseline_3yr_q15_eur: float
    baseline_3yr_q85_eur: float
    pulse_rotation_q85_eur: float
    breakdown_year2_year3_gains: GainBreakdown
    risk: RiskMetrics
    risk_preference: RiskPreference
    precrop_literature_sensitivity: dict[str, Any]
    cumulative_margin_fan: list[dict[str, Any]]
    n_simulations: int
    provenance: Provenance


class SorterAccess(BaseModel):
    """Distance to the nearest optical sorter, and what that distance costs.

    The block that makes "stranded potential" a financial category: a parcel can be
    agronomically ideal, pass food specification, and still lose money purely because
    the nearest industrial cleaner and optical sorter is too far to haul to.
    """

    nearest_unit_name: str | None
    nearest_unit_dept: str | None
    road_km: float | None
    within_range: bool
    max_distance_km: float
    incremental_km_charged: float
    haulage_eur_per_tonne_food: float
    haulage_cost_eur_ha_median: float
    haulage_cost_eur_whole_parcel: float
    is_stranded: bool
    stranded_note: str
    measured_from: Literal["clicked_parcel", "department_centroid"]
    provenance: Provenance


class BreederMatch(BaseModel):
    """One neighbouring livestock holding that can take a downgraded lot.

    The counterparty side of the fallback: what the breeder pays, what they avoid
    paying for imported soybean meal, and whether the trade is inside the haulage
    radius that makes it worth either party's while.
    """

    breeder_id: str
    name: str
    dept: str
    distance_km: float
    herd_type: str
    ugb: int
    annual_protein_meal_demand_t: float
    max_pulse_intake_t: float
    offered_price_eur_t: float
    feed_spot_price_eur_t: float
    uplift_vs_spot_eur_t: float
    breeder_avoided_soy_cost_eur: float
    breeder_avoided_soy_t: float
    absorbs_whole_lot: bool
    note: str


class BreederFallback(BaseModel):
    """The fear-killer, priced on both sides of the trade."""

    available: bool
    search_radius_km: float
    nearest_holding_km: float | None = None
    holdings_within_radius: int = 0
    downgraded_lot_t_median: float
    matches: list[BreederMatch] = Field(default_factory=list)
    best_offered_price_eur_t: float | None = None
    feed_spot_price_eur_t: float | None = None
    worth_signing: dict[str, Any] = Field(default_factory=dict)
    cvar_without_fallback_eur_ha: float | None = None
    cvar_with_fallback_eur_ha: float | None = None
    cvar_improvement_eur_ha: float | None = None
    median_without_fallback_eur_ha: float | None = None
    median_with_fallback_eur_ha: float | None = None
    headline: str
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


class FoodOutcome(BaseModel):
    """What of this harvest people in France actually eat.

    The block the brief asks for. Tonnes grown is not the answer: a lot has to clear
    retail specification (`human_grade_fraction`, from the quality model) and the crop
    has to have a human-food outlet at all (`food_market_share`, structural). Both
    apply, and multiplying them is what separates food from feed.
    """

    harvest_tonnes_median: float = Field(
        default=0.0,
        description=(
            "Median total harvest, for scale. Note that this does NOT equal the food "
            "plus feed medians added together - medians do not add. The split is exact "
            "per simulated draw; only its quantiles are reported."
        ),
    )
    food_grade_tonnes_median: float
    food_grade_tonnes_q15: float
    food_grade_tonnes_q85: float
    food_market_share: float
    human_grade_fraction_median: float
    prob_human_grade: float

    food_grade_protein_tonnes_median: float
    people_fed_at_current_intake: float
    people_fed_at_recommended_intake: float

    feed_fallback_tonnes_median: float
    food_grade_price_premium_eur_t: float | None = Field(
        default=None,
        description=(
            "Food price minus the feed floor, per tonne. The single most consequential "
            "number in the model: it is what the grading probability is multiplying."
        ),
    )
    value_at_risk_from_grading_eur_ha: float | None = Field(
        default=None,
        description=(
            "Yield x premium x (1 - P_human): the revenue per hectare that grading risk "
            "puts in play, as opposed to price or yield risk."
        ),
    )

    imported_pulse_displaced_tonnes: float
    import_origin_displaced: str | None = None
    transport_co2e_saved_tonnes: float = 0.0

    crop_food_note: str | None = None
    provenance: Provenance


class ClimateContext(BaseModel):
    """Which climate the figures above were computed in."""

    horizon: str
    label_en: str | None = None
    label_fr: str | None = None
    warming_level_c: float | None = None
    total_shift_applied_c: float
    window_catchup_applied_c: float
    notes: str | None = None
    provenance: Provenance


class SovereigntyContribution(BaseModel):
    department_code: str
    department_name: str
    current_pulse_share_pct: float
    share_after_this_parcel_pct: float
    parcel_share_of_dept_gap_pct: float
    national_target_pct: float
    # Added because `national_target_pct` alone was being read as the official PSN
    # target, which it is not: the PSN sets 8 percent of SAU including permanent
    # grassland, over a baseline that is 53 percent forage legumes. The fields below
    # say which denominator is in use and what the official target actually is.
    target_basis: str | None = None
    target_denominator: str | None = None
    official_psn_target: dict[str, Any] | None = None
    food_tier_self_sufficiency_pct: float | None = None


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
    food_outcome: FoodOutcome | None = None
    climate_context: ClimateContext | None = None
    sorter_access: SorterAccess | None = None
    breeder_fallback: BreederFallback | None = None
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
    # Infrastructure, split out from economics. A department can be profitable at zero
    # haulage and loss-making at the distance it actually has, and that distinction is
    # the only one a capital grant can act on.
    # "Best fit" is only an honest label when something fits. In Oise every one of the
    # six candidates loses money (-168 to -918 EUR/ha) and the engine still called
    # soybean its "best fit", which an agronomist reads as a recommendation.
    any_candidate_profitable: bool = True
    n_candidates_profitable: int = 0
    # WHICH crop the pulse was compared against, and whether that crop is the one this
    # department actually grows most of. The year-2 comparator's forgone margin is the
    # largest single term in `median_margin_gain_eur_ha`, and on this tab it is not
    # user-selectable, so stating it is the only way a reader can judge the number.
    baseline_rotation: list[str] = Field(default_factory=list)
    displaced_year2_crop: str | None = None
    baseline_rotation_caveat: str | None = None
    sorter_road_km: float | None = None
    haulage_cost_eur_ha: float = 0.0
    margin_gain_if_served_eur_ha: float | None = None
    is_infrastructure_limited: bool = False
    stranded_communes: int = 0
    stranded_ha: float = 0.0
    convertible_ha: float = 0.0
    n_communes: int = 0


class RegionalOverviewResponse(BaseModel):
    national_current_share_pct: float
    national_target_share_pct: float
    target_year: int
    departments: list[DepartmentOverview]
    total_gap_ha: float
    total_conversion_potential_eur: float
    surface_totals: dict[str, Any] = Field(default_factory=dict)
    stranded_band: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance | None = None
    compute_ms: float = 0.0


class SorterOptimiseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: int = Field(default=1, ge=1, le=26, description="New optical sorters to site.")
    department_code: str | None = None
    region_code: str | None = None
    min_site_population: int = Field(default=2000, ge=200, le=50000)
    verify_milp: bool = Field(
        default=False,
        description=(
            "Also solve the problem exactly with HiGHS and report the gap. Adds a few "
            "seconds; the greedy answer alone returns in well under a second."
        ),
    )


class RegionFoodBalance(BaseModel):
    """One region's population, what it eats, and what its farms could grade for food."""

    region_code: str
    region_name: str
    population_millions: float
    current_demand_t: float
    recommended_demand_t: float
    suppliable_food_grade_t: float
    coverage_of_current_demand_pct: float | None
    coverage_of_recommended_demand_pct: float | None
    deficit_vs_current_t: float
    deficit_vs_recommended_t: float
    collective_catering_t: float
    school_catering_t: float
    covers_collective_catering: bool
    catering_coverage_pct: float | None
    departments: list[dict[str, Any]] = Field(default_factory=list)
    best_pulse: str | None = None
    has_optical_sorting: bool = True


class FoodDemandResponse(BaseModel):
    """The demand side of the brief: the proteins people in France will eat.

    Supply here is a POTENTIAL, not a forecast: it is what the region's gap-to-target
    hectares would grade for human food at the engine's own modelled yields. It answers
    "if the 2030 area target were met here, would this region feed itself" - which is
    the question a Region can actually act on.
    """

    national: dict[str, Any]
    regions: list[RegionFoodBalance]
    climate_horizon: str
    supply_basis: str
    total_suppliable_food_grade_t: float
    total_current_demand_t: float
    total_recommended_demand_t: float
    finding: str
    provenance: Provenance
    compute_ms: float = 0.0


class ClimateOutlookRow(BaseModel):
    horizon: str
    label_en: str | None
    warming_level_c: float | None
    total_shift_applied_c: float
    yield_median_t_ha: float
    prob_human_grade: float
    human_grade_fraction_median: float
    food_grade_tonnes_per_ha: float
    median_delta_eur_ha: float
    prob_gain_positive: float
    may_days_above_20c: float
    jun_heat_days_30c: float
    harvest_rain_mm: float
    drought_stress_index: float


class ClimateOutlookResponse(BaseModel):
    """How one parcel's answer changes as the climate moves - the 'tomorrow' clause."""

    department_code: str
    crop: str
    soil_type: str
    rows: list[ClimateOutlookRow]
    sensitivities: list[dict[str, Any]]
    method: str
    caveat: str
    window_catchup_c: float
    finding: str
    provenance: Provenance
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
