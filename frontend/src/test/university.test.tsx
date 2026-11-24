import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/university",
}));

const v2Mock = vi.fn();
vi.mock("@/lib/api/v2", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/v2")>("@/lib/api/v2");
  return { ...actual, v2: v2Mock };
});

vi.mock("@/lib/population", () => ({
  usePopulation: () => ({
    items: [],
    population: null,
    missingId: null,
    usingDefault: false,
    loading: false,
    error: null,
    select: vi.fn(),
  }),
  withPop: (p: string) => p,
}));

const { default: UniversityPage } = await import("@/app/university/page");
const { RetentionTrajectoryChart, TuitionSweepChart } = await import("@/components/university/UniversityCharts");

describe("University Decision & Placement Studio page", () => {
  beforeEach(() => {
    v2Mock.mockReset();
    v2Mock.mockImplementation(async (path: string) => {
      if (path === "/placement/programs") {
        return {
          osym_verified: false,
          rule_fidelity: "hypothetical_simplified",
          disclaimer: "SIMPLIFIED HYPOTHETICAL RULES: test disclaimer.",
          score_types: ["SAY", "EA"],
          rank_thresholds: { engineering: 300000 },
          programs: [],
        };
      }
      if (path === "/placement/runs" || path === "/university/runs") {
        return { items: [], total: 0 };
      }
      return {};
    });
  });

  it("renders hypothetical disclaimer badge and allows switching to Multi-Semester tab", async () => {
    render(<UniversityPage />);

    await waitFor(() => {
      expect(screen.getByText(/SIMPLIFIED HYPOTHETICAL RULES: test disclaimer\./)).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: /Customize Parameters/i }));
    expect(screen.getByText("osym_verified: false")).toBeInTheDocument();

    const multiTab = screen.getByRole("tab", { name: /2\. Multi-Semester Policy Dynamics/i });
    await userEvent.click(multiTab);

    expect(screen.getByText(/Multi-Semester Policy Controls/i)).toBeInTheDocument();
    expect(screen.getByText("coefficients_calibrated: false")).toBeInTheDocument();
  });

  it("renders accessible table twins for trajectory and tuition sensitivity charts", async () => {
    render(
      <RetentionTrajectoryChart
        baseline={[{
          semester: 0, mean_active_students: 200, p05_active_students: 200, p95_active_students: 200,
          mean_paused_stop_out: 0, mean_transferred: 0, mean_withdrawn_dropout: 0, mean_graduated: 0,
          mean_retention_rate: 1.0, mean_gpa: 2.7, mean_waitlisted: 0, mean_net_tuition_revenue: 0, mean_aid_disbursed: 0,
        }]}
        policy={[{
          semester: 0, mean_active_students: 196, p05_active_students: 192, p95_active_students: 199,
          mean_paused_stop_out: 2, mean_transferred: 4, mean_withdrawn_dropout: 2, mean_graduated: 0,
          mean_retention_rate: 0.98, mean_gpa: 2.68, mean_waitlisted: 0, mean_net_tuition_revenue: 1200000, mean_aid_disbursed: 50000,
        }]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Show table" }));
    expect(screen.getByText("Term 0")).toBeInTheDocument();
    expect(screen.getByText("196.0")).toBeInTheDocument();

    render(
      <TuitionSweepChart
        rows={[{
          tuition_change_pct: 20, aid_budget_change_pct: 0, mean_retention_rate: 0.945, retention_delta_vs_zero: -0.02,
          mean_withdrawn_dropout: 3, mean_paused_stop_out: 5, mean_net_tuition_revenue: 3500000, mean_aid_disbursed: 100000,
        }]}
      />,
    );
    const buttons = screen.getAllByRole("button", { name: "Show table" });
    await userEvent.click(buttons[buttons.length - 1]);
    expect(screen.getByText("94.50%")).toBeInTheDocument();
  });

  it("runs counterfactual placement, triggers handoff to multi-semester run, and executes tuition sweep", async () => {
    v2Mock.mockImplementation(async (path: string, opts?: { method?: string }) => {
      if (path === "/placement/programs") {
        return {
          osym_verified: false, rule_fidelity: "hypothetical_simplified",
          disclaimer: "SIMPLIFIED / HYPOTHETICAL RULES test.", score_types: ["SAY"],
          rank_thresholds: { engineering: 300000 }, programs: [],
        };
      }
      if (path === "/placement/runs" && opts?.method === "POST") {
        return {
          run_id: "uplace-abc", scenario_id: null, population_id: null,
          osym_verified: false, rule_fidelity: "hypothetical_simplified",
          disclaimer: "SIMPLIFIED / HYPOTHETICAL RULES test.",
          result_sha256: "h1", created_at: "2026-11-21T12:00:00Z",
          summary: {
            title: "Placement Summary", headline: "42 placed", key_findings: [],
            summary_markdown: "", osym_verified: false, rule_fidelity: "hypothetical_simplified", disclaimer: "SIMPLIFIED",
          },
          result: {
            placement_result: {
              manifest: {},
              aggregate_metrics: { placed_count: 42, placement_rate: 0.7, first_choice_rate: 0.5, first_choice_count: 30, seat_utilization_rate: 0.9, total_filled: 42, total_capacity: 46 },
              program_outcomes: [],
            },
            comparison: {
              baseline_result_sha256: "b", policy_result_sha256: "p", candidates_sha256: "c",
              osym_verified: false, rule_fidelity: "hypothetical_simplified", disclaimer: "SIMPLIFIED",
              metric_deltas: {},
              transitions: { total_candidates: 60, same_program: 35, improved_preference: 2, worsened_preference: 1, newly_placed: 4, displaced_to_unplaced: 2, remained_unplaced: 16, eligibility_changed: 0 },
              program_deltas: [{
                program_id: "PRG_CS", baseline_capacity: 20, policy_capacity: 17, capacity_delta: -3,
                baseline_filled: 20, policy_filled: 17, filled_delta: -3,
                baseline_cutoff_score: 410.5, policy_cutoff_score: 418.2, cutoff_score_delta: 7.7, first_choice_delta: 0,
              }],
            },
            handoff: { student_count: 42, source_result_sha256: "h1" },
            demographic_source: "standalone_test_fixture",
            admitted_count: 42,
          },
        };
      }
      if (path === "/university/runs" && opts?.method === "POST") {
        return {
          run_id: "univ-xyz", scenario_id: null, placement_run_id: "uplace-abc",
          osym_verified: false, coefficients_calibrated: false,
          disclaimer: "SYNTHETIC / UNCALIBRATED PROTOTYPE test.",
          result_sha256: "h2", created_at: "2026-11-21T12:01:00Z",
          summary: {
            title: "CRN Report", headline: "Retention changed by -1.20 pp", key_findings: [],
            summary_markdown: "", osym_verified: false, coefficients_calibrated: false, disclaimer: "SYNTHETIC",
          },
          comparison: {
            replications: 8, osym_verified: false, coefficients_calibrated: false, disclaimer: "SYNTHETIC",
            policy_effects: {
              cumulative_retention_rate: { baseline_mean: 0.96, policy_mean: 0.948, mean: -0.012, std: 0.004, p05: -0.02, p50: -0.012, p95: -0.005 },
              final_withdrawn_dropout: { baseline_mean: 2, policy_mean: 4, mean: 2, std: 0.5, p05: 1, p50: 2, p95: 3 },
              final_paused_stop_out: { baseline_mean: 1, policy_mean: 2, mean: 1, std: 0.5, p05: 0, p50: 1, p95: 2 },
              total_net_tuition_revenue: { baseline_mean: 2000000, policy_mean: 2300000, mean: 300000, std: 50000, p05: 200000, p50: 300000, p95: 400000 },
            },
            baseline_trajectory: [{ semester: 0, mean_active_students: 42, p05_active_students: 42, p95_active_students: 42, mean_paused_stop_out: 0, mean_transferred: 0, mean_withdrawn_dropout: 0, mean_graduated: 0, mean_retention_rate: 1, mean_gpa: 2.6, mean_waitlisted: 0, mean_net_tuition_revenue: 0, mean_aid_disbursed: 0 }],
            policy_trajectory: [{ semester: 0, mean_active_students: 42, p05_active_students: 42, p95_active_students: 42, mean_paused_stop_out: 0, mean_transferred: 0, mean_withdrawn_dropout: 0, mean_graduated: 0, mean_retention_rate: 1, mean_gpa: 2.6, mean_waitlisted: 0, mean_net_tuition_revenue: 0, mean_aid_disbursed: 0 }],
          },
        };
      }
      if (path === "/university/sweep" && opts?.method === "POST") {
        return {
          placement_run_id: "uplace-abc", cohort_size: 42, semester_count: 4, replications: 8,
          osym_verified: false, coefficients_calibrated: false, disclaimer: "SYNTHETIC",
          rows: [{
            tuition_change_pct: 20, aid_budget_change_pct: 0, mean_retention_rate: 0.94, retention_delta_vs_zero: -0.02,
            mean_withdrawn_dropout: 3, mean_paused_stop_out: 2, mean_net_tuition_revenue: 2100000, mean_aid_disbursed: 50000,
          }],
        };
      }
      return { items: [], total: 0 };
    });

    render(<UniversityPage />);
    await userEvent.click(screen.getByRole("button", { name: /Customize Parameters/i }));
    await userEvent.click(screen.getByRole("button", { name: /Run Counterfactual Placement/i }));

    await waitFor(() => {
      expect(screen.getByText(/Placement Results \(uplace-abc\)/)).toBeInTheDocument();
    });
    expect(screen.getByText("PRG_CS")).toBeInTheDocument();
    expect(screen.getByText("+7.70")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Handoff Admitted Cohort \(42\)/i }));
    await waitFor(() => {
      expect(screen.getByText(/Multi-Semester Policy Impact \(univ-xyz\)/)).toBeInTheDocument();
    });
    expect(screen.getByText("-1.20 pp")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Run 0–30% Tuition Sweep/i }));
    await waitFor(() => {
      expect(screen.getByText(/Tuition Sensitivity Sweep/i)).toBeInTheDocument();
    });
  });

  it("handles null telemetry without coercing to zero and renders Tuition sweep table", async () => {
    v2Mock.mockImplementation(async (path: string) => {
      if (path === "/placement/programs") {
        return {
          osym_verified: false,
          rule_fidelity: "hypothetical_simplified",
          disclaimer: "SIMPLIFIED HYPOTHETICAL RULES: test disclaimer.",
          score_types: ["SAY"],
          rank_thresholds: {},
          programs: [],
        };
      }
      if (path === "/university/runs") {
        return {
          items: [{
            run_id: "univ-nulls",
            scenario_id: null,
            placement_run_id: null,
            osym_verified: false,
            coefficients_calibrated: false,
            result_sha256: "b".repeat(64),
            created_at: "2026-10-20T00:00:00Z",
            summary: {
              title: "Partial", headline: "Partial metrics test", key_findings: [], summary_markdown: "Partial",
              osym_verified: false, coefficients_calibrated: false, disclaimer: "M2_DISCLAIMER",
            },
          }],
          total: 1,
        };
      }
      if (path === "/university/runs/univ-nulls") {
        return {
          run_id: "univ-nulls",
          scenario_id: null,
          placement_run_id: null,
          osym_verified: false,
          coefficients_calibrated: false,
          result_sha256: "b".repeat(64),
          created_at: "2026-10-20T00:00:00Z",
          summary: {
            title: "Partial", headline: "Partial metrics test", key_findings: [], summary_markdown: "Partial",
            osym_verified: false, coefficients_calibrated: false, disclaimer: "M2_DISCLAIMER",
          },
          comparison: {
            replications: 2, osym_verified: false, coefficients_calibrated: false, disclaimer: "M2_DISCLAIMER",
            policy_effects: {
              cumulative_retention_rate: { baseline_mean: null, policy_mean: null, mean: null, std: null, p05: null, p50: null, p95: null },
              total_net_tuition_revenue: { baseline_mean: null, policy_mean: null, mean: null, std: null, p05: null, p50: null, p95: null },
            },
            baseline_trajectory: [],
            policy_trajectory: [],
          },
        };
      }
      return { items: [], total: 0 };
    });

    render(<UniversityPage />);
    await userEvent.click(screen.getByRole("button", { name: /Customize Parameters/i }));
    await userEvent.click(screen.getByRole("tab", { name: /2\. Multi-Semester Policy Dynamics/i }));
    await waitFor(() => {
      expect(screen.getByText(/Multi-Semester Policy Impact \(univ-nulls\)/)).toBeInTheDocument();
    });
    expect(screen.getByText("M2_DISCLAIMER")).toBeInTheDocument();
    expect(screen.queryByText("+0.00 pp")).not.toBeInTheDocument();
  });
});
