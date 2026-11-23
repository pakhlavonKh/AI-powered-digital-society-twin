"""Behavioral Benchmark Research Interface (K5) — ``src/societytwin/validation/behavioral.py``.

Provides interface specifications and benchmark data structures for behavioral, stated-preference,
and policy scenario validation (e.g. Ankara public transit fare increases) without fabricating
ground truth.

Core principles:
- Explicit evidence typology: Every benchmark is classified into exactly one evidence type:
  ``observed_behavior | survey_response | literature_estimate | hypothetical_assumption``.
- Stated intention is NOT equivalent to observed ridership decrease: Models explicitly enforce
  comparability warnings and forbid equating stated responses with revealed elasticities.
- Honest handling of the validation gap: When no empirical reference exists at target geography
  or for the specific intervention, the benchmark is marked ``status="unavailable"`` with an
  explicit ``unavailability_reason``. Zero numbers are fabricated.
- Purely deterministic and reproducible: Hash-verified metadata, validated Pydantic models,
  no network or paid LLM calls in validation logic.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt

from societytwin.common import canonical_hash
from societytwin.national.dependencies import TypedModel

BENCHMARK_SCHEMA_VERSION = "behavioral-benchmark-k5-v1"

EvidenceType = Literal[
    "observed_behavior",
    "survey_response",
    "literature_estimate",
    "hypothetical_assumption",
]

BenchmarkStatus = Literal[
    "available",
    "unavailable",
    "insufficient_metadata",
]


class BenchmarkProvenance(TypedModel):
    """Bibliographic, administrative, and geographical provenance of a behavioral benchmark."""

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    publisher_agency: str = Field(min_length=1)
    publication_year: StrictInt | str | None = None
    citation: str = Field(min_length=1)
    url: str | None = None
    geography: str = Field(min_length=1, description="ISO, NUTS, or provincial code (e.g. '06', 'TR51', 'TR', 'GLOBAL')")
    geography_name: str = Field(min_length=1)
    sample_size: StrictInt | None = None
    sample_denominator: str = Field(min_length=1)
    collection_method: str = Field(min_length=1)


class MeasurementDefinition(TypedModel):
    """Precise operational definition and units of the measured behavioral quantity."""

    metric_name: str = Field(min_length=1)
    metric_unit: str = Field(min_length=1)
    target_variable: str = Field(min_length=1)
    formula_or_description: str = Field(min_length=1)


class ComparabilityNotes(TypedModel):
    """Contextual limitations and comparability constraints relative to the policy scenario."""

    scenario_id: str = Field(min_length=1)
    applicability_scope: str = Field(min_length=1)
    is_direct_ground_truth: StrictBool = False
    stated_vs_revealed_distinction: str = Field(
        min_length=1,
        description=(
            "Explicit documentation of whether this benchmark measures stated intentions or revealed "
            "physical behavior, highlighting known hypothetical bias and asset constraints."
        ),
    )
    limitations: tuple[str, ...] = ()


class BenchmarkSpec(TypedModel):
    """Specification of an individual behavioral or scenario benchmark.

    Interface-only model: Can represent an available empirical/literature reference
    or an explicitly documented 'unavailable' state where no ground truth exists.
    """

    benchmark_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    status: BenchmarkStatus
    evidence_type: EvidenceType
    provenance: BenchmarkProvenance
    measurement: MeasurementDefinition
    comparability: ComparabilityNotes
    observed_value: float | None = None
    observed_range: tuple[float, float] | None = None
    unavailability_reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.status == "available" and (self.observed_value is not None or self.observed_range is not None)

    @property
    def is_ground_truth(self) -> bool:
        return self.evidence_type == "observed_behavior" and self.comparability.is_direct_ground_truth


class BenchmarkBundle(TypedModel):
    """A collection of behavioral benchmarks associated with a specific scenario."""

    schema_version: Literal["behavioral-benchmark-k5-v1"] = BENCHMARK_SCHEMA_VERSION
    bundle_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    benchmarks: tuple[BenchmarkSpec, ...]

    @property
    def bundle_fingerprint(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def get_benchmark(self, benchmark_id: str) -> BenchmarkSpec:
        for b in self.benchmarks:
            if b.benchmark_id == benchmark_id:
                return b
        raise KeyError(f"Benchmark {benchmark_id!r} not found in bundle. Available: {[b.benchmark_id for b in self.benchmarks]}")

    def available_benchmarks(self) -> tuple[BenchmarkSpec, ...]:
        return tuple(b for b in self.benchmarks if b.status == "available")

    def unavailable_benchmarks(self) -> tuple[BenchmarkSpec, ...]:
        return tuple(b for b in self.benchmarks if b.status == "unavailable")

    def by_evidence_type(self, evidence_type: EvidenceType) -> tuple[BenchmarkSpec, ...]:
        return tuple(b for b in self.benchmarks if b.evidence_type == evidence_type)

    def to_markdown(self) -> str:
        """Render a comprehensive Markdown inventory of behavioral benchmarks."""
        lines = [
            f"# Behavioral Benchmark Inventory — `{self.bundle_id}`",
            "",
            f"- **Scenario ID:** `{self.scenario_id}`",
            f"- **Title:** {self.title}",
            f"- **Description:** {self.description}",
            f"- **Total Benchmarks:** {len(self.benchmarks)} "
            f"(`available={len(self.available_benchmarks())}`, `unavailable={len(self.unavailable_benchmarks())}`)",
            "",
            "## Benchmark Specifications & Evidence Typology",
            "",
            "| Benchmark ID | Evidence Type | Status | Geography | Metric | Benchmark Value / Range | Ground Truth? |",
            "|---|---|---|---|---|---:|:---:|",
        ]

        for b in self.benchmarks:
            val_str = "Unavailable"
            if b.observed_value is not None:
                val_str = f"{b.observed_value:g} {b.measurement.metric_unit}"
            elif b.observed_range is not None:
                val_str = f"[{b.observed_range[0]:g}, {b.observed_range[1]:g}] {b.measurement.metric_unit}"

            gt_str = "YES" if b.is_ground_truth else "NO"
            lines.append(
                f"| `{b.benchmark_id}` | `{b.evidence_type}` | **`{b.status.upper()}`** | "
                f"`{b.provenance.geography}` | `{b.measurement.metric_name}` | {val_str} | {gt_str} |"
            )

        lines.extend([
            "",
            "## Detailed Benchmark Profiles & Validation Notes",
            "",
        ])

        for b in self.benchmarks:
            lines.extend([
                f"### `{b.benchmark_id}`: {b.name}",
                f"- **Evidence Type:** `{b.evidence_type}` (Status: **`{b.status.upper()}`**)",
                f"- **Publisher / Agency:** {b.provenance.publisher_agency} ({b.provenance.publication_year or 'N/A'})",
                f"- **Citation:** *{b.provenance.citation}*",
            ])
            if b.provenance.url:
                lines.append(f"- **Reference URL:** [{b.provenance.url}]({b.provenance.url})")
            lines.extend([
                f"- **Geography / Denominator:** `{b.provenance.geography}` ({b.provenance.geography_name}) / {b.provenance.sample_denominator}",
                f"- **Measurement Definition:** {b.measurement.formula_or_description} (Unit: `{b.measurement.metric_unit}`)",
                f"- **Stated vs. Revealed Distinction:** {b.comparability.stated_vs_revealed_distinction}",
            ])
            if b.unavailability_reason:
                lines.append(f"- **Unavailability Reason:** > {b.unavailability_reason}")
            if b.comparability.limitations:
                lines.append("- **Limitations:**")
                for lim in b.comparability.limitations:
                    lines.append(f"  - {lim}")
            lines.append("")

        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Canonical Ankara 20% Fare Increase Benchmark Bundle
# -----------------------------------------------------------------------------

def get_ankara_transit_fare_bundle() -> BenchmarkBundle:
    """Construct the canonical behavioral benchmark bundle for the Ankara 20% fare increase scenario.

    Scenario Context:
    - Hypothetical 20% increase in standard public transit fares in Ankara (from 21.00 TL to 25.20 TL
      in the August 2024 UKOME tariff base; or 40.00 TL to 48.00 TL in 2026 tariff base).
    - Concessions for students and seniors (65+ free transit under Law No. 4736) remain subsidized.

    Evidence Inventory:
    1. ankara_ego_observed_elasticity: UNAVAILABLE (EGO publishes raw boardings, not econometric elasticities).
    2. literature_transit_fare_elasticity: AVAILABLE (Litman / TRRL meta-estimates: e_p in [-0.50, -0.20]).
    3. ankara_stated_travel_intention: UNAVAILABLE (No representative pre-policy stated preference survey).
    4. tuik_tr51_household_transport_expenditure_share: AVAILABLE (TÜİK HBA: 23.6% of expenditure in TR51).
    5. auap_ankara_transit_modal_split: AVAILABLE (AUAP 2038 / SKUP baseline: ~32% transit modal split).
    6. hypothetical_agent_fare_reduction_assumption: AVAILABLE (Hypothetical simulation assumption).
    """
    benchmarks: list[BenchmarkSpec] = [
        # 1. Observed Ridership Elasticity in Ankara (UNAVAILABLE)
        BenchmarkSpec(
            benchmark_id="ankara_ego_observed_elasticity",
            name="Ankara EGO Observed Transit Fare Elasticity of Demand",
            scenario_id="transport_fare_001",
            status="unavailable",
            evidence_type="observed_behavior",
            provenance=BenchmarkProvenance(
                source_id="ego_annual_reports",
                title="EGO Genel Müdürlüğü Faaliyet Raporları ve Biniş İstatistikleri",
                publisher_agency="Ankara Büyükşehir Belediyesi (ABB) / EGO Genel Müdürlüğü",
                publication_year=2024,
                citation="EGO Genel Müdürlüğü, 2024 Yılı İdare Faaliyet Raporu ve UKOME Bilet Fiyat Tarifeleri.",
                url="https://www.ego.gov.tr/tr/kategori/17/raporlar-ve-istatistikler",
                geography="06",
                geography_name="Ankara Metropolitan Municipality",
                sample_size=None,
                sample_denominator="All electronic smartcard validations across EGO Bus, Metro, and Ankaray",
                collection_method="Automated Fare Collection (AFC) system turnstile transaction logs",
            ),
            measurement=MeasurementDefinition(
                metric_name="fare_elasticity_of_demand",
                metric_unit="elasticity_coefficient",
                target_variable="ridership_change_ratio",
                formula_or_description="Percentage change in transit boardings divided by percentage change in real fare: (dQ / Q) / (dP / P).",
            ),
            comparability=ComparabilityNotes(
                scenario_id="transport_fare_001",
                applicability_scope="Revealed public transit demand in Ankara.",
                is_direct_ground_truth=True,
                stated_vs_revealed_distinction=(
                    "Measures actual physical boarding card validations. Completely distinct from stated intentions. "
                    "However, no isolated econometric elasticity estimate has been computed or released by the agency."
                ),
                limitations=(
                    "EGO publishes aggregate annual and daily passenger boardings, but does not publish econometric fare elasticity estimates.",
                    "Tariff adjustments in Ankara occur during high macroeconomic inflation (>60% CPI), making nominal fare changes lag general inflation.",
                    "Raw boarding numbers are heavily confounded by student semester calendars, fuel price fluctuations, and post-pandemic recovery.",
                    "No demographic persona breakdowns (ridership by age, income, trip purpose) are available in published EGO statistics.",
                ),
            ),
            observed_value=None,
            observed_range=None,
            unavailability_reason=(
                "Ankara EGO General Directorate publishes aggregate annual and daily passenger boardings, but does not publish "
                "econometric fare elasticity models or micro-data isolating the effect of tariff adjustments from macroeconomic inflation "
                "and seasonal confounders. No empirical observed elasticity number can be verified without fabricating ground truth."
            ),
        ),

        # 2. International / National Literature Estimate of Transit Fare Elasticity (AVAILABLE)
        BenchmarkSpec(
            benchmark_id="literature_transit_fare_elasticity",
            name="Literature Meta-Estimate of Urban Transit Fare Elasticity",
            scenario_id="transport_fare_001",
            status="available",
            evidence_type="literature_estimate",
            provenance=BenchmarkProvenance(
                source_id="litman_vtpi_2023",
                title="Transit Price Elasticities and Cross-Elasticities: Understanding Transport Demand",
                publisher_agency="Victoria Transport Policy Institute (VTPI) / UK Transport Research Laboratory (TRRL)",
                publication_year=2023,
                citation="Litman, T. (2023). Transit Price Elasticities and Cross-Elasticities. Victoria Transport Policy Institute; and Webster & Bly (TRRL Report 920).",
                url="https://www.vtpi.org/tranelas.pdf",
                geography="GLOBAL",
                geography_name="Global Meta-Analysis of Urban Transit Systems",
                sample_size=None,
                sample_denominator="Meta-analysis across over 100 empirical transit fare elasticity studies",
                collection_method="Econometric meta-analysis of time-series and cross-sectional fare elasticity studies",
            ),
            measurement=MeasurementDefinition(
                metric_name="short_run_fare_elasticity",
                metric_unit="elasticity_coefficient",
                target_variable="ridership_percentage_change",
                formula_or_description=(
                    "Standard short-run urban transit fare elasticity: e_p = (% change in ridership) / (% change in fare). "
                    "Typically -0.33 (the Simpson-Curtin rule: a 10% fare increase causes a 3.3% ridership drop). "
                    "For a 20% fare increase, implied short-run ridership drop is approximately -4.0% to -8.0%."
                ),
            ),
            comparability=ComparabilityNotes(
                scenario_id="transport_fare_001",
                applicability_scope="Theoretical and comparative benchmark for urban transit demand response.",
                is_direct_ground_truth=False,
                stated_vs_revealed_distinction=(
                    "Synthesizes revealed-preference econometric studies across global metropolitan areas. "
                    "Serves as an empirical reference point for physical behavior, but is NOT an Ankara-specific observation."
                ),
                limitations=(
                    "Global literature estimates reflect stable economic conditions and mature transit networks, not Ankara's high-inflation environment.",
                    "Elasticity varies substantially across trip purposes (peak commute e_p ~ -0.15, off-peak discretionary e_p ~ -0.40 to -0.60).",
                    "Does not account for Turkey's statutory concessions (65+ free transit, student flat monthly passes).",
                ),
            ),
            observed_value=-0.33,
            observed_range=(-0.50, -0.20),
            unavailability_reason=None,
        ),

        # 3. Ankara Stated Travel Intentions Pre-Policy Survey (UNAVAILABLE)
        BenchmarkSpec(
            benchmark_id="ankara_stated_travel_intention",
            name="Ankara Representative Stated Travel Intentions Survey (20% Fare Increase)",
            scenario_id="transport_fare_001",
            status="unavailable",
            evidence_type="survey_response",
            provenance=BenchmarkProvenance(
                source_id="ankara_hypothetical_survey_gap",
                title="Representative Public Opinion Survey on Proposed UKOME 20% Fare Adjustment",
                publisher_agency="None (Unconducted / Unpublished)",
                publication_year=None,
                citation="No published scientific pre-policy stated preference survey on the specific 20% fare adjustment in Ankara.",
                url=None,
                geography="06",
                geography_name="Ankara Province",
                sample_size=None,
                sample_denominator="Random stratified sample of Ankara adult public transit users",
                collection_method="Stated preference (SP) questionnaire / contingent valuation",
            ),
            measurement=MeasurementDefinition(
                metric_name="stated_ridership_reduction_share",
                metric_unit="percent",
                target_variable="q1_usage_change_distribution",
                formula_or_description="Percentage of surveyed transit users stating they would reduce trips or switch modes following a 20% fare increase.",
            ),
            comparability=ComparabilityNotes(
                scenario_id="transport_fare_001",
                applicability_scope="Hypothetical survey benchmark directly matching the scenario prompt.",
                is_direct_ground_truth=False,
                stated_vs_revealed_distinction=(
                    "STATED INTENTION IS NOT EQUIVALENT TO REVEALED RIDERSHIP DECREASE. "
                    "In stated preference surveys, respondents consistently overstate their intention to reduce usage or walk "
                    "as a protest expression against tariff hikes (hypothetical bias). When the tariff takes effect, captive riders "
                    "with no car access and long commute distances almost entirely continue using transit."
                ),
                limitations=(
                    "No representative pre-policy stated preference survey was commissioned or publicly archived for this specific intervention.",
                    "Stated intention surveys suffer from hypothetical bias, social desirability, and protest response bias.",
                ),
            ),
            observed_value=None,
            observed_range=None,
            unavailability_reason=(
                "No representative pre-policy stated preference survey measuring public transit intention changes for the "
                "specific 2024 UKOME 20% tariff increase (from 21.00 TL to 25.20 TL) exists in the public domain. "
                "The validation engine refuses to fabricate a survey benchmark."
            ),
        ),

        # 4. TÜİK TR51 Household Budget Survey Transportation Expenditure Share (AVAILABLE)
        BenchmarkSpec(
            benchmark_id="tuik_tr51_household_transport_expenditure_share",
            name="TÜİK TR51 (Ankara) Household Transportation Expenditure Share",
            scenario_id="transport_fare_001",
            status="available",
            evidence_type="survey_response",
            provenance=BenchmarkProvenance(
                source_id="tuik_hba_tr51_2024",
                title="Hanehalkı Tüketim Harcaması (Bölgesel), 2022-2024",
                publisher_agency="Türkiye İstatistik Kurumu (TÜİK)",
                publication_year=2024,
                citation="TÜİK Haber Bülteni, Sayı: 49635, Hanehalkı Tüketim Harcaması (Bölgesel) 2022-2024 (TR51 Ankara).",
                url="https://data.tuik.gov.tr/Bulten/Index?p=Hanehalki-Tuketim-Harcamasi-(Bolgesel)-2022-2024-49635",
                geography="TR51",
                geography_name="Ankara (NUTS-2 Region)",
                sample_size=None,
                sample_denominator="Representative sample of private households in Ankara keeping monthly expense diaries",
                collection_method="Household Budget Survey (HBA) diary and questionnaire over one-month reference period",
            ),
            measurement=MeasurementDefinition(
                metric_name="transport_expenditure_share_pct",
                metric_unit="percent",
                target_variable="coicop_07_transport_share",
                formula_or_description="Percentage of total household consumption expenditure allocated to COICOP 07 (Transportation): 23.6%.",
            ),
            comparability=ComparabilityNotes(
                scenario_id="transport_fare_001",
                applicability_scope="Economic context for transportation price sensitivity in Ankara households.",
                is_direct_ground_truth=False,
                stated_vs_revealed_distinction=(
                    "Measures recorded household financial expenditure (revealed cash outlays), not transit trip elasticity. "
                    "Demonstrates that transportation accounts for nearly a quarter (23.6%) of Ankara household budgets, "
                    "the second highest regional share in Turkey, explaining high public sensitivity to fare changes."
                ),
                limitations=(
                    "COICOP 07 aggregates private vehicle purchases, motor fuel, vehicle maintenance, and public transit fares.",
                    "Cannot isolate public bus/metro fare expenses from private automobile fuel costs.",
                    "Does not measure physical trips or mode switching behavior.",
                ),
            ),
            observed_value=23.6,
            observed_range=(22.0, 25.0),
            unavailability_reason=None,
        ),

        # 5. Ankara Transportation Master Plan (AUAP / SKUP) Modal Split (AVAILABLE)
        BenchmarkSpec(
            benchmark_id="auap_ankara_transit_modal_split",
            name="Ankara Transportation Master Plan Public Transit Modal Split Baseline",
            scenario_id="transport_fare_001",
            status="available",
            evidence_type="survey_response",
            provenance=BenchmarkProvenance(
                source_id="auap_skup_ankara",
                title="Ankara Sürdürülebilir Kentsel Ulaşım Planı (SKUP Ankara) & AUAP 2038",
                publisher_agency="Ankara Büyükşehir Belediyesi / Gazi Üniversitesi Ulaşım Planlama Grubu",
                publication_year=2024,
                citation="Ankara Büyükşehir Belediyesi EGO Genel Müdürlüğü, SKUP Ankara 2050 ve AUAP 2038 Tür Dağılımı Verileri.",
                url="https://www.ego.gov.tr/tr/haber/5643/skup-ankara-projesi",
                geography="06",
                geography_name="Ankara Metropolitan Area",
                sample_size=35000,
                sample_denominator="Comprehensive metropolitan household travel survey (AUAP sample)",
                collection_method="Face-to-face household travel survey with 24-hour travel diaries",
            ),
            measurement=MeasurementDefinition(
                metric_name="public_transit_modal_share",
                metric_unit="share_0_to_1",
                target_variable="modal_split_public_transit",
                formula_or_description="Proportion of daily mechanized and non-motorized urban trips conducted via public transit (EGO bus, metro, Ankaray): ~0.32 (32%).",
            ),
            comparability=ComparabilityNotes(
                scenario_id="transport_fare_001",
                applicability_scope="Structural baseline modal split in Ankara.",
                is_direct_ground_truth=False,
                stated_vs_revealed_distinction=(
                    "Measures recorded cross-sectional trip choices under prevailing fare regimes, not dynamic elasticity. "
                    "Establishes that approximately one third of all trips in Ankara rely on public transit."
                ),
                limitations=(
                    "Reflects cross-sectional travel habits, not marginal shifts after a single tariff adjustment.",
                    "Includes walking, private car, dolmuş, and school/work service shuttles in the modal denominator.",
                ),
            ),
            observed_value=0.32,
            observed_range=(0.30, 0.35),
            unavailability_reason=None,
        ),

        # 6. Hypothetical Agent Scenario Assumption (AVAILABLE as explicit simulation assumption)
        BenchmarkSpec(
            benchmark_id="hypothetical_agent_fare_reduction_assumption",
            name="Scenario Design Hypothetical Travel Adjustment Option Distribution",
            scenario_id="transport_fare_001",
            status="available",
            evidence_type="hypothetical_assumption",
            provenance=BenchmarkProvenance(
                source_id="societytwin_scenario_fare_001",
                title="SocietyTwin Scenario Definition: Ankara Public Transportation Fare Increase",
                publisher_agency="SocietyTwin Scenario Module (Pakhlavon / Koray)",
                publication_year=2024,
                citation="SocietyTwin Project, experiments/policy_scenarios/scenarios/transport_fare_001.yaml.",
                url="file:///c:/Users/Korai/Desktop/engineering%20design/main/experiments/policy_scenarios/scenarios/transport_fare_001.yaml",
                geography="06",
                geography_name="Ankara",
                sample_size=1000,
                sample_denominator="Calibrated synthetic adult Ankara population",
                collection_method="Controlled agentic LLM prompt simulation over persona attributes",
            ),
            measurement=MeasurementDefinition(
                metric_name="discrete_choice_distribution",
                metric_unit="categorical_shares",
                target_variable="q1_usage_change",
                formula_or_description=(
                    "Categorical distribution over five options: maintain_usage, reduce_optional_trips, "
                    "switch_to_walking, switch_to_private_car_or_taxi, unsure."
                ),
            ),
            comparability=ComparabilityNotes(
                scenario_id="transport_fare_001",
                applicability_scope="Prompted scenario simulation options.",
                is_direct_ground_truth=False,
                stated_vs_revealed_distinction=(
                    "ENTIRELY HYPOTHETICAL SIMULATION CONSTRUCT. Agent choices represent simulated reasoning "
                    "conditioned on persona prompts, NOT observed human behavior. Under no circumstances should "
                    "simulated agent distributions be presented as empirical ground truth."
                ),
                limitations=(
                    "Simulated LLM responses reflect model prior beliefs, persona prompting, and temperature settings.",
                    "No empirical ground truth calibration exists for this hypothetical response distribution.",
                ),
            ),
            observed_value=None,
            observed_range=None,
            unavailability_reason=None,
        ),
    ]

    return BenchmarkBundle(
        bundle_id="ankara_transit_fare_increase_20pct_bundle",
        scenario_id="transport_fare_001",
        title="Ankara 20% Public Transit Fare Increase Behavioral Benchmark Bundle",
        description=(
            "Behavioral and economic benchmark specifications for evaluating synthetic persona responses "
            "to a hypothetical 20% fare increase in Ankara, documenting empirical availability and the validation gap."
        ),
        benchmarks=tuple(benchmarks),
    )
