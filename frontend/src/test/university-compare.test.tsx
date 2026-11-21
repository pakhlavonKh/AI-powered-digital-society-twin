import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildRegistryFixture } from "@/lib/university/fixtures/registry";
import { builtinConfigs, computeFixtureRun } from "@/lib/university/fixtureSource";
import { compareRuns, runCompatibility, summarizeRun } from "@/lib/university/metrics";
import { hasBlocking } from "@/lib/university/scenario";
import type { ScenarioConfig, SimulationRun } from "@/lib/university/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/university/compare",
}));

const { ScenarioComparison } = await import("@/components/university/ScenarioComparison");

const cat = buildRegistryFixture();
const [a, b, c] = builtinConfigs().map((s) => computeFixtureRun(s.config, "builtin_fixture", s.created_at));
const run = (patch: Partial<ScenarioConfig>) => computeFixtureRun({ ...a.config, ...patch }, "session_fixture", "2026-11-21T01:00:00Z");
const codes = (x: SimulationRun, y: SimulationRun) => runCompatibility(x, y).map((f) => `${f.blocking ? "!" : ""}${f.code}`);

describe("scenario differences", () => {
  const cmp = compareRuns(a, b, cat);
  const sa = summarizeRun(a, cat);
  const sb = summarizeRun(b, cat);

  it("report the placement-rate change in percentage points and, separately, as a relative change", () => {
    expect(cmp.placement_rate_pp).toBeCloseTo((sb.placement_rate! - sa.placement_rate!) * 100, 10);
    expect(cmp.placement_rate_rel_pct).toBeCloseTo(((sb.placement_rate! - sa.placement_rate!) / sa.placement_rate!) * 100, 10);
    expect(cmp.placement_rate_pp).not.toBeCloseTo(cmp.placement_rate_rel_pct!, 2);
  });

  it("compute unplaced, placed, capacity and utilization differences as B − A", () => {
    expect(cmp.unplaced_diff).toBe(sb.unplaced - sa.unplaced);
    expect(cmp.placed_diff).toBe(sb.placed - sa.placed);
    expect(cmp.capacity_diff).toBe(sb.capacity_known - sa.capacity_known);
    expect(cmp.utilization_pp).toBeCloseTo((sb.utilization! - sa.utilization!) * 100, 10);
    expect(cmp.first_choice_pp).toBeCloseTo((sb.first_choice_share! - sa.first_choice_share!) * 100, 10);
  });

  it("break differences down consistently by institution, program and preference position", () => {
    expect(cmp.universities.reduce((t, u) => t + u.diff, 0)).toBe(cmp.placed_diff);
    expect(cmp.programs.reduce((t, p) => t + p.diff, 0)).toBe(cmp.placed_diff);
    expect(cmp.preference_rank.reduce((t, r) => t + r.diff, 0)).toBe(cmp.placed_diff);
    for (const p of cmp.programs.filter((x) => x.a_util !== null && x.b_util !== null)) expect(p.util_pp).toBeCloseTo((p.b_util! - p.a_util!) * 100, 10);
  });

  it("classify every matched candidate exactly once", () => {
    const t = cmp.candidates.transitions;
    expect(Object.values(t).reduce((s, n) => s + n, 0)).toBe(cmp.candidates.matched);
    expect(cmp.candidates.matched).toBe(1000);
    expect(t.newly_placed - t.newly_not_placed).toBe(cmp.placed_diff);
    expect(cmp.candidates.changed).toHaveLength(t.moved_program + t.newly_placed + t.newly_not_placed + t.eligibility_changed);
  });

  it("are zero when a run is compared with itself", () => {
    const self = compareRuns(c, c, cat);
    expect([self.placement_rate_pp, self.placed_diff, self.unplaced_diff, self.candidates.changed.length]).toEqual([0, 0, 0, 0]);
    expect(codes(c, c)).toEqual(["same_run"]);
  });
});

describe("scenario compatibility", () => {
  it("accepts runs that differ only in quotas", () => {
    expect(hasBlocking(runCompatibility(a, b))).toBe(false);
    expect(codes(a, b)).toEqual([]);
  });

  it("blocks different admission years, cohorts, snapshots, origins and unfinished runs", () => {
    expect(codes(a, run({ admission_year: 2024 }))).toContain("!year_mismatch");
    expect(codes(a, run({ cohort: { ...a.config.cohort, seed: 7, cohort_id: "fixture-cohort-s7-n1000" } }))).toContain("!cohort_mismatch");
    expect(codes(a, { ...b, provenance: { ...b.provenance, registry_snapshot_id: "sha256:other" } })).toContain("!dataset_mismatch");
    expect(codes(a, { ...b, origin: "api" })).toContain("!origin_mismatch");
    expect(codes(a, { ...b, status: "running" })).toContain("!run_not_completed");
  });

  it("warns, without blocking, about cohort size, seed, engine and institution differences", () => {
    const smaller = run({ cohort: { ...a.config.cohort, size: 400, cohort_id: "fixture-cohort-s42-n400" } });
    expect(codes(a, smaller)).toEqual(["cohort_size_mismatch"]);
    const cmp = compareRuns(a, smaller, cat);
    expect(cmp.candidates).toMatchObject({ matched: 400, only_a: 600, only_b: 0 });
    expect(codes(a, run({ seed: 99 }))).toEqual(["seed_mismatch"]);
    expect(codes(a, { ...b, provenance: { ...b.provenance, engine_version: "v2" } })).toEqual(["engine_mismatch"]);
    expect(codes(a, run({ included_university_keys: [cat.universities[0].university_key] }))).toEqual(["institutions_mismatch"]);
  });
});

describe("comparison view", () => {
  it("shows percentage-point and relative changes separately, with the formula", () => {
    const cmp = compareRuns(a, b, cat);
    render(<ScenarioComparison runA={a} runB={b} catalogue={cat} snapshot={null} />);
    const tile = screen.getByText("Placement rate A → B").closest(".tile") as HTMLElement;
    expect(tile).toHaveTextContent(`${cmp.placement_rate_pp! >= 0 ? "+" : "−"}${Math.abs(cmp.placement_rate_pp!).toFixed(1)} pp`);
    expect(tile).toHaveTextContent(`relative +${cmp.placement_rate_rel_pct!.toFixed(1)}%`);
    const formula = screen.getByLabelText("Comparison formulas");
    expect(formula).toHaveTextContent("Placement rate difference = B − A");
    expect(formula).toHaveTextContent(`Unplaced candidate difference = B unplaced − A unplaced = ${cmp.b.unplaced} − ${cmp.a.unplaced}`);
    const transitions = screen.getByRole("table", { name: /candidates in both runs/ });
    expect(within(transitions).getByText("Not placed in A, placed in B").closest("tr")).toHaveTextContent(String(cmp.candidates.transitions.newly_placed));
  });
});
