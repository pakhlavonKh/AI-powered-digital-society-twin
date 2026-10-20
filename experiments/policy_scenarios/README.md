# SocietyTwin: Policy Scenarios & Scenario Engine Module

**Module Assigned To:** Pakhlavon  
**Scope:** Scenario Definition, Policy Configuration, Mobility Evidence Research & Contract Validation  
**Reference Scenario:** Public Transportation Fare Increase in Ankara (`transport_fare_001`)  
**Implementation Status:** Implemented & Verified (M1, M2, M3 complete with 26 passing tests)

---

## 1. What This Module Does & Why It Exists

The **Scenario Engine** provides an independent, reusable subsystem that defines, configures, validates, and loads public policy simulation scenarios for SocietyTwin.

While the **Synthetic Population** answers:
> *"Who lives in our simulated society?"*

The **Scenario Engine** answers:
> *"What policy situation and survey questions are we asking this society to respond to?"*

It decouples policy parameters and survey instruments from both the demographic generator and the LLM runtime. This ensures that researchers can test new scenarios (e.g., electricity tariffs, transit fare increases, municipal subsidies) without altering population tables or hardcoding prompts into execution scripts.

---

## 2. Directory Organization

```text
experiments/policy_scenarios/
├── README.md                                  # This documentation
├── research/
│   ├── mobility_evidence_register.csv        # Evidence register (observed, derived, missing)
│   └── transport_data_notes.md               # Tariff structures, UKOME rules & missing attribute analysis
├── scenarios/
│   └── transport_fare_001.yaml               # Reference 20% Ankara transit fare increase scenario
└── fixtures/
    ├── sample_residents.json                 # Synthetic resident test records (demographics + missing attributes)
    └── sample_agent_responses.json           # Example valid, invalid, and refused AI agent responses
```

The core Python implementation is located in **`src/scenarios/`**:
```text
src/scenarios/
├── __init__.py                               # Clean public API
├── schema.py                                 # Pydantic data models with strict validation
├── loader.py                                 # YAML/JSON scenario loader with diagnostic errors
├── eligibility.py                            # Resident eligibility evaluator & population filter
├── prompt_renderer.py                        # Safe prompt builder (no seed or private metadata leakage)
└── response_validator.py                     # Deterministic LLM response validator (zero model calls)
```

Tests are located in **`tests/test_scenarios/`**:
- `test_schema.py`: Schema validation, bounds, forbidden extra fields, and duplicate IDs.
- `test_loader.py`: File parsing, syntax diagnostics, and roundtrip serialization.
- `test_eligibility.py`: Single resident evaluation and batch population diagnostics.
- `test_response_validator.py`: JSON parsing, markdown code fences, illegal choices, and refusal handling.
- `test_prompt_renderer.py`: Persona context formatting and privacy preservation.

---

## 3. Reference Scenario: `transport_fare_001`

- **Intervention:** A hypothetical 20% increase in the standard electronic single-ride transit fare in Ankara (EGO bus, Ankaray, and Metro).
- **Baseline Tariff:** 21.00 TL (derived from the official August 2024 UKOME tariff for Ankara EGO).
- **Proposed Tariff:** 25.20 TL (+20.0%).
- **Crucial Concession Guard:** Explicitly specifies that discounted student fares (10.50 TL) and statutory free concession for citizens aged 65+ (under Law No. 4736) are separate categories and **not** silently converted to standard adult fares.
- **Questions:**
  - `q1_usage_change`: How the individual's transit trip frequency would adjust.
  - `q2_policy_support`: Whether the individual supports or opposes the tariff adjustment.

---

## 4. How to Create a New Scenario

To define a new policy scenario (e.g., a household electricity price adjustment or a student transit subsidy):

1. Create a YAML file in `scenarios/` (e.g. `scenarios/energy_subsidy_001.yaml`).
2. Follow the required schema structure:
   ```yaml
   scenario_id: energy_subsidy_001
   version: "1.0.0"
   name: Low-Income Electricity Subsidy
   description: "A hypothetical municipal energy relief program..."
   location:
     province_code: "06"
     province_name: Ankara
   metadata:
     hypothetical: true
     source_note: "Derived from EPDK residential energy tariffs."
   policy:
     category: energy
     type: subsidy
     parameters:
       baseline_fare: 2.50 # unit tariff
       currency: TL
   target_population:
     minimum_age: 18
     province_codes: ["06"]
     adult_only: true
     required_attributes: ["age", "province_code"]
   questions:
     - id: q1_budget_impact
       text: "How significantly would this subsidy affect your monthly household budget?"
       type: single_choice
       options:
         - id: significant_relief
           label: "Significant financial relief"
         - id: minor_relief
           label: "Minor relief"
         - id: no_impact
           label: "No noticeable impact"
       allow_other: false
       ask_rationale: true
   ```
3. Load and validate programmatically:
   ```python
   from scenarios import load_scenario

   scenario = load_scenario("scenarios/energy_subsidy_001.yaml")
   print(f"Loaded scenario: {scenario.name} (ID: {scenario.scenario_id})")
   ```

---

## 5. How to Run the Automated Tests

From the repository root with the project virtual environment activated:

```powershell
.\.venv\Scripts\pytest tests/test_scenarios/ -v
```

All 26 tests run in under 0.5 seconds without making any external network requests or LLM API calls.

---

## 6. Assumptions & Current Scientific Limitations

1. **Unobserved Mobility Attributes:**
   Official TÜİK demographic records (ADNKS 2025) do not record individual transit trip frequencies, Ankarakart tap histories, or personal automobile access. These are documented in `research/mobility_evidence_register.csv` as **MISSING**.
2. **No False Fabrication:**
   The eligibility engine does not fabricate unobserved travel habits. If a scenario requires personal car access, residents without this attribute are marked with status `CANNOT_EVALUATE` rather than being assigned arbitrary fake values.
3. **Hypothetical Responses vs. Real Public Behavior:**
   Simulated responses produced by AI agents conditioned on these scenarios are exploratory model outputs, not empirical forecasts of Turkish public opinion.

---

## 7. Integration Contract for the Population & Runtime Developers

### For the Synthetic Population Developer:
The Scenario Engine accepts resident dictionaries conforming to the following keys:
- `resident_id` or `synthetic_id`: Unique identifier (string).
- `age`: Integer (0–120).
- `province_code`: Two-digit string (e.g. `"06"`).
- `sex` / `gender`: `"male"` or `"female"`.
- `marital_status`: String (e.g. `"never_married"`, `"married"`, `"divorced"`, `"widowed"`).
- `education_level`: String.
- Missing attributes should be represented as `None` or `"unavailable"`, which our eligibility engine handles explicitly.

### For the Simulation / Runtime Developer (MatrAIx):
To run a scenario against a cohort of personas:
```python
from scenarios import load_scenario, filter_population, render_scenario_prompt, validate_agent_response

# 1. Load validated scenario
scenario = load_scenario("experiments/policy_scenarios/scenarios/transport_fare_001.yaml")

# 2. Filter cohort records
filter_result = filter_population(synthetic_residents, scenario)
eligible_residents = filter_result.eligible_records

# 3. For each eligible resident, render prompts
for resident in eligible_residents:
    system_prompt, user_prompt = render_scenario_prompt(scenario, resident)
    
    # 4. Pass to LLM / MatrAIx agent...
    # raw_agent_response = agent.run(system_prompt, user_prompt)

    # 5. Validate the structured answer (rejects hallucinations, missing answers, out-of-spec choices)
    envelope = validate_agent_response(raw_agent_response, scenario, resident_id=resident["synthetic_id"])
    if envelope.is_valid():
        print(f"Recorded answer for {envelope.resident_id}: {envelope.answers}")
    else:
        print(f"Validation failed for {envelope.resident_id}: {envelope.errors}")
```
