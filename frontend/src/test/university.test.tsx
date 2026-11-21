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
});
