import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { allocateFixture } from "@/lib/university/fixtures/allocator";
import { buildCohort } from "@/lib/university/fixtures/candidates";
import { buildRegistryFixture } from "@/lib/university/fixtures/registry";
import { builtinConfigs, computeFixtureRun } from "@/lib/university/fixtureSource";
import { runIntegrity, summarizeRun } from "@/lib/university/metrics";
import type { Assignment, SimulationRun } from "@/lib/university/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/university/results",
}));

const { ResultsOverview } = await import("@/components/university/ResultsOverview");
const { UnplacedCandidates } = await import("@/components/university/UnplacedCandidates");
const { PlacementCharts } = await import("@/components/university/PlacementCharts");

const cat = buildRegistryFixture();
const cohort = buildCohort(42, 1000);
const [a, b, c] = builtinConfigs().map((s) => computeFixtureRun(s.config, "builtin_fixture", s.created_at));
const types = new Map(cohort.candidates.map((x) => [x.candidate_id, x.score_type]));

/** A small hand-built run whose expected numbers are known exactly. */
function tinyRun(assignments: Assignment[], capacities: SimulationRun["capacities"]): SimulationRun {
  return { ...a, run_id: "tiny", assignments, capacities, findings: [] };
}
const placed = (id: string, code: string, pos: number): Assignment => ({ candidate_id: id, status: "placed", program_code: code, preference_position: pos, reason_code: null, reason: null, evaluated: null });
const other = (id: string, status: "unplaced" | "ineligible", reason: string | null = null): Assignment => ({ candidate_id: id, status, program_code: null, preference_position: null, reason_code: reason ? "x" : null, reason, evaluated: null });

describe("placement metrics", () => {
  const [p1, p2] = cat.programs;
  const run = tinyRun(
    [placed("c1", p1.program_code, 1), placed("c2", p1.program_code, 2), placed("c3", p2.program_code, 1), other("c4", "unplaced"), other("c5", "ineligible"), other("c6", "ineligible")],
    [{ program_code: p1.program_code, base_quota: 2, capacity: 2, placed: 2 }, { program_code: p2.program_code, base_quota: null, capacity: null, placed: 1 }],
  );
  const s = summarizeRun(run, cat);

  it("reconcile totals and use eligible candidates as the placement-rate denominator", () => {
    expect(s).toMatchObject({ total: 6, placed: 3, unplaced: 1, ineligible: 2, eligible: 4, reconciles: true });
    expect(s.placement_rate).toBe(3 / 4); // not 3/6: ineligible candidates are excluded
  });

  it("count preference ranks among placed candidates only", () => {
    expect(s.preference_rank).toEqual([{ position: 1, count: 2 }, { position: 2, count: 1 }]);
    expect(s.first_choice_share).toBeCloseTo(2 / 3);
  });

  it("exclude unknown capacities from capacity totals instead of treating them as zero", () => {
    expect(s.capacity_known).toBe(2);
    expect(s.programs_unknown_capacity).toBe(1);
    expect(s.utilization).toBe(1);
    expect(s.remaining_capacity).toBe(0);
    const uni2 = s.by_program.find((p) => p.program_code === p2.program_code)!;
    expect(uni2.capacity).toBeNull();
  });

  it("flag placements exceeding capacity and never cap them", () => {
    const over = tinyRun([placed("c1", p1.program_code, 1), placed("c2", p1.program_code, 1), placed("c3", p1.program_code, 1)],
      [{ program_code: p1.program_code, base_quota: 2, capacity: 2, placed: 3 }]);
    const so = summarizeRun(over, cat);
    expect(so.over_capacity).toEqual([{ program_code: p1.program_code, capacity: 2, placed: 3 }]);
    expect(so.occupied_seats).toBe(3);
    expect(runIntegrity(over, cat).map((f) => f.code)).toContain("over_capacity");
    render(<ResultsOverview s={so} />);
    expect(screen.getByRole("alert")).toHaveTextContent(`${p1.program_code} (3 > 2)`);
  });

  it("report unreconciled totals and missing provenance", () => {
    const broken = { ...tinyRun([placed("c1", "999999999", 1)], []), provenance: { ...a.provenance, engine: "", engine_version: null } };
    const codes = runIntegrity(broken, cat).map((f) => f.code);
    expect(codes).toEqual(expect.arrayContaining(["invalid_preference_reference", "missing_provenance"]));
  });
});

describe("fixture runs", () => {
  it("never exceed capacity, reconcile, and respond to quota changes in the expected direction", () => {
    const [sa, sb, sc] = [a, b, c].map((r) => summarizeRun(r, cat, types));
    for (const s of [sa, sb, sc]) {
      expect(s.over_capacity).toEqual([]);
      expect(s.reconciles).toBe(true);
      expect(s.total).toBe(1000);
    }
    expect(sb.placed).toBeGreaterThanOrEqual(sa.placed);
    expect(sc.placed).toBeLessThanOrEqual(sa.placed);
    expect(sa.eligible).toBe(sb.eligible); // quotas do not change eligibility in the fixture
  });

  it("are deterministic for a seed", () => {
    const again = allocateFixture(a.config, cat, cohort.candidates, cohort.preferences);
    expect(again.assignments).toEqual(a.assignments);
  });

  it("only place candidates into programs matching their score type", () => {
    const byCode = new Map(cat.programs.map((p) => [p.program_code, p]));
    const fold = (t: string | null) => (t ?? "").replace("Ö", "O").replace("İ", "I");
    for (const x of a.assignments.filter((y) => y.status === "placed")) {
      expect(fold(byCode.get(x.program_code!)!.score_type)).toBe(types.get(x.candidate_id));
    }
  });

  it("chart preference ranking counts that sum to the placed total", () => {
    const s = summarizeRun(a, cat, types);
    expect(s.preference_rank.reduce((t, r) => t + r.count, 0)).toBe(s.placed);
    const manual = new Map<number, number>();
    for (const x of a.assignments) if (x.status === "placed") manual.set(x.preference_position!, (manual.get(x.preference_position!) ?? 0) + 1);
    for (const r of s.preference_rank) expect(r.count).toBe(manual.get(r.position) ?? 0);
  });
});

describe("results components", () => {
  it("state the placement-rate formula with its denominator", () => {
    const s = summarizeRun(a, cat, types);
    render(<ResultsOverview s={s} />);
    const formula = screen.getByLabelText("Placement rate formula");
    expect(formula).toHaveTextContent(`${s.placed} ÷ ${s.eligible} × 100 = ${((s.placed / s.eligible) * 100).toFixed(1)}%`);
    expect(formula).toHaveTextContent(`The ${s.ineligible} candidate(s) the simulation marked ineligible`);
    expect(screen.getByText("Totals reconcile")).toBeInTheDocument();
  });

  it("list unplaced candidates with the simulation's reason, and ineligible ones on request", async () => {
    const user = userEvent.setup();
    const s = summarizeRun(a, cat, types);
    render(<UnplacedCandidates run={a} cohort={cohort} snapshot={null} />);
    const table = screen.getByRole("table", { name: new RegExp(`${s.unplaced} synthetic candidates without a placement`) });
    expect(within(table).getAllByRole("row")).toHaveLength(26);
    expect(within(table).getAllByText(/Every eligible preference was already full/).length).toBe(25);
    await user.click(screen.getByRole("checkbox", { name: /Include \d+ ineligible/ }));
    expect(screen.getByRole("table", { name: new RegExp(`${s.unplaced + s.ineligible} synthetic candidates`) })).toBeInTheDocument();
  });

  it("say so when the simulation gave no reason, instead of inventing one", () => {
    const run = tinyRun([other(cohort.candidates[0].candidate_id, "unplaced", null)], []);
    render(<UnplacedCandidates run={run} cohort={cohort} snapshot={null} />);
    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("Not available")).toBeInTheDocument();
  });

  it("show empty-data states instead of empty charts", () => {
    const empty = summarizeRun(tinyRun([other("c1", "ineligible")], []), cat);
    render(<PlacementCharts s={empty} origin="fixture" />);
    expect(screen.getByText("No candidate was placed, so there is no preference ranking.")).toBeInTheDocument();
    expect(screen.getAllByText("Fixture data").length).toBeGreaterThan(0);
  });
});
