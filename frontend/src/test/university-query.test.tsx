import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import UniversityPage from "@/app/university/page";

const { v2Mock } = vi.hoisted(() => ({
  v2Mock: vi.fn(),
}));

vi.mock("@/lib/api/v2", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/v2")>("@/lib/api/v2");
  return {
    ...actual,
    v2: v2Mock,
  };
});

vi.mock("@/lib/population", () => ({
  usePopulation: () => ({
    population: { population_id: "pop_tuik_1", label: "TÜİK Sample 2025" },
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="recharts-container">{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Bar: () => <div />,
  LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Line: () => <div />,
  CartesianGrid: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  Tooltip: () => <div />,
}));

const BASE_CATALOG = {
  osym_verified: false,
  rule_fidelity: "hypothetical_simplified",
  disclaimer: "SIMPLIFIED HYPOTHETICAL RULES: test disclaimer.",
  score_types: ["SAY", "EA"],
  rank_thresholds: { engineering: 300000 },
  programs: [
    {
      program_id: "P_FND_CS_FEE",
      university_id: "UNI_FND_A",
      university_name: "Anatolia Foundation University",
      university_type: "foundation",
      province_code: "34",
      department_name: "Computer Engineering",
      degree_level: "bachelor",
      score_type: "SAY",
      baraj_group: "engineering",
      capacity: 40,
      tuition_annual: 320000,
      scholarship_pct: 0,
      university_rank: 45,
      prestige_score: 0.72,
      status: "active",
    },
    {
      program_id: "P_STATE_CS",
      university_id: "UNI_STATE_B",
      university_name: "Marmara Technical (State)",
      university_type: "state",
      province_code: "34",
      department_name: "Computer Engineering",
      degree_level: "bachelor",
      score_type: "SAY",
      baraj_group: "engineering",
      capacity: 60,
      tuition_annual: 0,
      scholarship_pct: 100,
      university_rank: 35,
      prestige_score: 0.80,
      status: "active",
    },
  ],
};

describe("UniversityPage Prompt-Driven Query Studio", () => {
  beforeEach(() => {
    v2Mock.mockReset();
  });

  it("compiles, edits assumptions, runs tuition +30% query, and renders executive answer + generic stats", async () => {
    const planPayload = {
      plan_hash: "planhash1234",
      query_spec: {
        original_prompt: "How many students would apply to this uni if tuition increased by 30%?",
        language: "en",
        intent: "application_demand",
        focus_university_id: "UNI_FND_A",
        focus_university_name: "Anatolia Foundation University",
        focus_program_ids: [],
        focus_department_names: [],
        snapshot_id: null,
        admission_year: 2025,
        levers: {
          target_university_ids: ["UNI_FND_A"],
          tuition_change_pct: 30,
          capacity_change_pct: 0,
          aid_budget_change_pct: 0,
        },
        comparison_variants: [],
        sweep_tuition_pcts: [],
        metrics_requested: ["listed_anywhere", "listed_top_k", "first_choice", "placed"],
        subgroup_dimensions_requested: ["income_band", "scholarship_tier"],
        simulation_mode: "placement",
        cohort_size: 200,
        seed: 42,
        assumptions: [
          { key: "tuition_change_pct", label: "Target tuition change", value: 30, source: "user", editable: true, unit: "%" },
          { key: "rivals_fixed", label: "Rival universities fixed", value: true, source: "default", editable: false },
        ],
        disclaimers: ["osym_verified=false", "coefficients_calibrated=false"],
        confidence: 0.88,
        unresolved_entities: [],
        out_of_scope_reasons: [],
      },
      preference_config: {
        enabled: true,
        elasticity_preset: "medium",
        beta_rank: 2.2,
        beta_cost_by_income: { low: 2.2, middle: 1.25, high: 0.55 },
        beta_home: 0.65,
        beta_fit: 0.85,
        outside_option_threshold: 1.2,
        top_k_definition: 3,
        coefficients_calibrated: false,
        calibration_note: "Synthetic uncalibrated",
      },
      elasticity_presets: {},
      catalog: {
        catalog_source: "standalone_demo_catalog",
        snapshot_id: null,
        admission_year: 2025,
        total_programs: 2,
        targeted_programs: 1,
        rivals_fixed: true,
        universities: [
          { university_id: "UNI_FND_A", university_name: "Anatolia Foundation University", university_type: "foundation" },
          { university_id: "UNI_STATE_B", university_name: "Marmara Technical (State)", university_type: "state" },
        ],
      },
      population_id: null,
      osym_verified: false,
      coefficients_calibrated: false,
      blockers: [],
      warnings: [],
      executable: true,
      disclaimers: [],
    };

    const runPayload = {
      run_id: "uquery_test_1",
      prompt: "How many students would apply to this uni if tuition increased by 30%?",
      intent: "application_demand",
      snapshot_id: null,
      focus_university_id: "UNI_FND_A",
      focus_university_name: "Anatolia Foundation University",
      osym_verified: false,
      coefficients_calibrated: false,
      result_sha256: "c".repeat(64),
      created_at: "2026-11-24T12:00:00Z",
      query_spec: {
        ...planPayload.query_spec,
        levers: { ...planPayload.query_spec.levers, tuition_change_pct: 40 },
      },
      summary: {
        title: "University Simulation: Anatolia Foundation University",
        headline: "Estimated applicants to Anatolia Foundation University (listed anywhere): 118 -> 79 (-39 / -33.1%) (about 68 to 94 across Low/Medium/High sensitivities, central 79).",
        direct_answer: "Defining 'apply' as listing Anatolia Foundation University anywhere in the preference list, applications move 118 -> 79.",
        key_findings: ["Low-income applications fell sharply while rivals stayed fixed."],
        summary_markdown: "# Report\nEstimated applicants: 118 -> 79",
        assumptions: planPayload.query_spec.assumptions,
        caveats: [
          "Uncalibrated behavioral elasticities (coefficients_calibrated=false).",
          "Rivals stay fixed: rival universities do not respond.",
        ],
        generated_by: "deterministic",
        detailed_statistics: [
          {
            id: "headline_kpis",
            title: "Key Simulation Outcomes",
            type: "tiles",
            data: {
              items: [
                { label: "Applicants (listed anywhere)", value: "79", sub: "Baseline 118 (-39)" },
                { label: "1st-choice applicants", value: "21", sub: "Baseline 34 (-13)" },
              ],
            },
          },
          {
            id: "applicants_by_income",
            title: "Applicants by Household Income Band (Baseline vs. Policy)",
            type: "bar_series",
            data: {
              value_label: "Applicants",
              series: [
                { key: "baseline_listed", label: "Baseline", slot: "series-1" },
                { key: "policy_listed", label: "Policy", slot: "series-2" },
              ],
              rows: [
                { category: "low", label: "Low", values: { baseline_listed: 36, policy_listed: 16 } },
                { category: "high", label: "High", values: { baseline_listed: 34, policy_listed: 31 } },
              ],
            },
          },
          {
            id: "applicant_migration",
            title: "Applicant Migration & Competitor Flow",
            type: "flow_summary",
            data: {
              stayed_at_target: 62,
              shifted_within_target: 8,
              shifted_to_rival_uni: 29,
              dropped_out_of_applying: 19,
              newly_attracted: 0,
              top_rival_destinations: [{ university_id: "UNI_STATE_B", university_name: "Marmara Technical (State)", count: 29 }],
            },
          },
        ],
      },
      detailed_statistics: [],
      result: {},
      manifest: { rivals_fixed: true, osym_verified: false, coefficients_calibrated: false },
    };
    runPayload.detailed_statistics = runPayload.summary.detailed_statistics as never[];

    v2Mock.mockImplementation(async (path: string) => {
      if (path === "/placement/programs") return BASE_CATALOG;
      if (path === "/university/query/plan") return planPayload;
      if (path === "/university/query/runs") return runPayload;
      if (path === "/university-registry/status") {
        return { available: false, db_path: "", schema_version: null, snapshots: [], note: "none" };
      }
      return { items: [], total: 0 };
    });

    render(<UniversityPage />);

    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Anatolia Foundation University/i })).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: /Compile Query Plan/i }));

    await waitFor(() => {
      expect(screen.getByText(/Compiled Plan: application_demand/i)).toBeInTheDocument();
    });

    // Edit tuition assumption from 30 to 40 before running
    const tuitionEdit = screen.getByLabelText(/Tuition change \(%\)/i);
    await userEvent.clear(tuitionEdit);
    await userEvent.type(tuitionEdit, "40");

    await userEvent.click(screen.getByRole("button", { name: /Run Counterfactual Simulation/i }));

    await waitFor(() => {
      expect(screen.getByText(/Question-Specific Executive Summary/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Defining 'apply' as listing Anatolia Foundation University/i)).toBeInTheDocument();
    expect(screen.getByText(/Applicants by Household Income Band/i)).toBeInTheDocument();
    const rivalItem = screen.getByText(/29 shifted applicants/i).closest("li");
    expect(rivalItem).toHaveTextContent("Marmara Technical (State): 29 shifted applicants");

    const runCall = v2Mock.mock.calls.find((c) => c[0] === "/university/query/runs" && c[1]?.method === "POST");
    expect(runCall).toBeTruthy();
    expect(runCall![1].body.query_spec.levers.tuition_change_pct).toBe(40);
  });

  it("renders comparison_set variants table for ranking higher/lower questions and handles unresolved blockers", async () => {
    const blockedPlan = {
      plan_hash: "blocked123",
      query_spec: {
        original_prompt: "What happens if Bilkent ranking changes?",
        language: "en",
        intent: "ranking_sensitivity",
        focus_university_id: null,
        focus_university_name: null,
        focus_program_ids: [],
        focus_department_names: [],
        snapshot_id: null,
        admission_year: 2025,
        levers: {},
        comparison_variants: [],
        sweep_tuition_pcts: [],
        metrics_requested: [],
        subgroup_dimensions_requested: [],
        simulation_mode: "placement",
        cohort_size: 200,
        seed: 42,
        assumptions: [],
        disclaimers: [],
        confidence: 0.4,
        unresolved_entities: [
          {
            mention: "Bilkent",
            entity_type: "university",
            reason: "University 'Bilkent' was not found in active catalog.",
            candidates: [{ university_id: "UNI_FND_A", university_name: "Anatolia Foundation University" }],
          },
        ],
        out_of_scope_reasons: [],
      },
      preference_config: {
        enabled: true,
        elasticity_preset: "medium",
        beta_rank: 2.2,
        beta_cost_by_income: { low: 2.2, middle: 1.25, high: 0.55 },
        beta_home: 0.65,
        beta_fit: 0.85,
        outside_option_threshold: 1.2,
        top_k_definition: 3,
        coefficients_calibrated: false,
        calibration_note: "",
      },
      elasticity_presets: {},
      catalog: {
        catalog_source: "standalone_demo_catalog",
        snapshot_id: null,
        admission_year: 2025,
        total_programs: 2,
        targeted_programs: 2,
        rivals_fixed: true,
        universities: [],
      },
      population_id: null,
      osym_verified: false,
      coefficients_calibrated: false,
      blockers: [{ code: "unresolved_university", message: "University 'Bilkent' was not found in active catalog." }],
      warnings: [],
      executable: false,
      disclaimers: [],
    };

    const rankingRun = {
      run_id: "uquery_rank_1",
      prompt: "How would applications and cutoffs change if this uni's ranking got higher or lower?",
      intent: "ranking_sensitivity",
      snapshot_id: null,
      focus_university_id: "UNI_FND_A",
      focus_university_name: "Anatolia Foundation University",
      osym_verified: false,
      coefficients_calibrated: false,
      result_sha256: "d".repeat(64),
      created_at: "2026-11-24T12:05:00Z",
      query_spec: {
        ...blockedPlan.query_spec,
        original_prompt: "How would applications and cutoffs change if this uni's ranking got higher or lower?",
        focus_university_id: "UNI_FND_A",
        focus_university_name: "Anatolia Foundation University",
        unresolved_entities: [],
      },
      summary: {
        title: "University Simulation: Anatolia Foundation University",
        headline: "Exogenous ranking sensitivity: Lower (-20%): 84 | Baseline (0%): 110 | Higher (+20%): 138.",
        direct_answer: "Higher ranking increases listed applications and cutoffs; lower ranking decreases them.",
        key_findings: [],
        summary_markdown: "# Ranking sensitivity",
        assumptions: [],
        caveats: ["Uncalibrated elasticities.", "Rivals stay fixed."],
        generated_by: "deterministic",
        detailed_statistics: [
          {
            id: "variant_comparison",
            title: "Scenario Variant Comparison",
            type: "comparison_set",
            data: {
              variants: [
                { variant_id: "lower", label: "Lower Ranking (-20%)", is_baseline: false, listed_anywhere: 84, listed_anywhere_delta: -26, listed_top_k: 45, first_choice: 15, placed: 28, filled: 28, capacity: 40, mean_cutoff_score: 365.4, target_net_revenue: 8960000 },
                { variant_id: "baseline", label: "Baseline (0%)", is_baseline: true, listed_anywhere: 110, listed_anywhere_delta: 0, listed_top_k: 61, first_choice: 24, placed: 35, filled: 35, capacity: 40, mean_cutoff_score: 382.1, target_net_revenue: 11200000 },
                { variant_id: "higher", label: "Higher Ranking (+20%)", is_baseline: false, listed_anywhere: 138, listed_anywhere_delta: 28, listed_top_k: 82, first_choice: 34, placed: 40, filled: 40, capacity: 40, mean_cutoff_score: 401.8, target_net_revenue: 12800000 },
              ],
            },
          },
        ],
      },
      detailed_statistics: [],
      result: {},
      manifest: {},
    };
    rankingRun.detailed_statistics = rankingRun.summary.detailed_statistics as never[];

    v2Mock.mockImplementation(async (path: string) => {
      if (path === "/placement/programs") return BASE_CATALOG;
      if (path === "/university/query/plan") return blockedPlan;
      if (path === "/university/query/runs/uquery_rank_1") return rankingRun;
      if (path === "/university/query/runs") {
        return {
          items: [
            {
              run_id: "uquery_rank_1",
              prompt: rankingRun.prompt,
              intent: "ranking_sensitivity",
              snapshot_id: null,
              focus_university_id: "UNI_FND_A",
              focus_university_name: "Anatolia Foundation University",
              osym_verified: false,
              coefficients_calibrated: false,
              headline: rankingRun.summary.headline,
              direct_answer: rankingRun.summary.direct_answer,
              created_at: "2026-11-24T12:05:00Z",
            },
          ],
          total: 1,
        };
      }
      return { items: [], total: 0 };
    });

    render(<UniversityPage />);

    await waitFor(() => {
      expect(screen.getByText(/Recent University Question Runs/i)).toBeInTheDocument();
    });

    // Compile a query that returns an unresolved entity blocker
    await userEvent.click(screen.getByRole("button", { name: /Compile Query Plan/i }));
    await waitFor(() => {
      expect(screen.getByText(/Blocked — clarification needed before running/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /Run Counterfactual Simulation/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Use Anatolia Foundation University/i })).toBeInTheDocument();

    // Load saved ranking comparison run from history
    await userEvent.click(screen.getByRole("button", { name: /Inspect/i }));
    await waitFor(() => {
      expect(screen.getByText(/Scenario Variant Comparison/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Lower Ranking \(-20%\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Higher Ranking \(\+20%\)/i)).toBeInTheDocument();
    expect(screen.getByText("401.80")).toBeInTheDocument();
  });

  it("loads SQLite snapshot universities and admission years when a snapshot is chosen", async () => {
    v2Mock.mockImplementation(async (path: string) => {
      if (path === "/placement/programs") return BASE_CATALOG;
      if (path === "/university-registry/status") {
        return {
          available: true,
          db_path: "university.sqlite3",
          schema_version: 4,
          snapshots: [
            {
              snapshot_id: "snap_2025",
              source_filename: "yok_atlas_2025.xlsx",
              imported_at: "2026-11-24T10:00:00Z",
              verification_status: "imported_unverified",
              counts: { universities: 2, programs: 10, open_quality_issues: 0 },
              admission_years: [2024, 2025],
            },
          ],
          note: "ok",
        };
      }
      if (path === "/university-registry/snapshots/snap_2025/universities") {
        return {
          snapshot_id: "snap_2025",
          items: [
            {
              university_id: "UNI_SQL_1",
              university_key: "ankara_uni",
              university_name: "Ankara State SQLite Uni",
              university_type: "state",
              program_count: 5,
            },
          ],
        };
      }
      return { items: [], total: 0 };
    });

    render(<UniversityPage />);

    // Auto-selects the newest imported SQLite snapshot as soon as registry status loads
    await waitFor(() => {
      expect(screen.getByRole("option", { name: /Ankara State SQLite Uni/i })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByText(/Advanced query options/i));
    expect(screen.getByRole("option", { name: /SQLite: yok_atlas_2025\.xlsx/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Catalog source/i)).toHaveValue("snap_2025");
    expect(screen.getByLabelText(/Admission year/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2025" })).toBeInTheDocument();
  });
});
