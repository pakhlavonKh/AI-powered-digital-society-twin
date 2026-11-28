import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  candidateDetail, candidateRows, candidateStateFromParams, candidateStateToParams, cohortRanks, preferenceViews, queryCandidateRows, type CandidateUrlState,
} from "@/lib/university/candidates";
import { buildCohort, cohortId, UNKNOWN_PROGRAM_CODE } from "@/lib/university/fixtures/candidates";
import { buildRegistryFixture } from "@/lib/university/fixtures/registry";
import { createFixtureSource } from "@/lib/university/fixtureSource";
import type { CandidateQuery, Cohort } from "@/lib/university/types";
import { CONTRACT_SCORE_TYPES } from "@/lib/university/util";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/university/candidates",
}));

const { UniversitySourceProvider } = await import("@/lib/university/context");
const { CandidateExplorer } = await import("@/components/university/CandidateExplorer");
const { CandidateDetails } = await import("@/components/university/CandidateDetails");

const cat = buildRegistryFixture();
const cohort = buildCohort(42, 1000);
const source = createFixtureSource({ persist: false });
const runs = await source.listRuns();
const baseline = await source.getRun(runs[0].run_id);
const q = (patch: Partial<CandidateQuery> = {}): CandidateQuery => ({
  cohort_id: cohort.manifest.cohort_id, search: "", score_types: [], proxy_min: null, proxy_max: null, status: null, eligibility: null, provinces: [],
  run_id: null, sort: "proxy", direction: "desc", offset: 0, limit: 25, ...patch,
});

describe("synthetic candidate fixture", () => {
  it("is reproducible with a fixed seed and a larger cohort extends a smaller one", () => {
    const small = buildCohort(42, 50);
    expect(small.candidates).toEqual(cohort.candidates.slice(0, 50));
    expect(small.preferences).toEqual(cohort.preferences.filter((p) => Number(p.candidate_id.slice(-8)) <= 50));
    expect(buildCohort(43, 50).candidates).not.toEqual(small.candidates);
  });

  it("uses stable synthetic IDs, contract score types and no personal data", () => {
    cohort.candidates.forEach((c, i) => expect(c.candidate_id).toBe(`candidate-${String(i + 1).padStart(8, "0")}`));
    for (const c of cohort.candidates) {
      expect(Object.keys(c).sort()).toEqual(["achievement", "age", "annual_budget_try", "candidate_id", "educational_interests", "home_location", "score_type"]);
      expect(CONTRACT_SCORE_TYPES).toContain(c.score_type);
      expect(c.home_location).toBeNull();
      expect(c.annual_budget_try).toBeNull();
      expect(c.achievement!.value).toBeGreaterThanOrEqual(0);
      expect(c.achievement!.value).toBeLessThanOrEqual(10000);
    }
    expect(cohort.manifest.origin).toBe("fixture");
  });

  it("references fixture programs, except the one deliberately unknown code", () => {
    const codes = new Set(cat.programs.map((p) => p.program_code));
    const bad = cohort.preferences.filter((p) => !codes.has(p.program_id));
    expect(bad.length).toBeGreaterThan(0);
    expect(new Set(bad.map((p) => p.program_id))).toEqual(new Set([UNKNOWN_PROGRAM_CODE]));
  });

  it("follows the handoff's structural rules: unique programs and contiguous positions per candidate", () => {
    const by = new Map<string, { pos: number[]; prog: string[] }>();
    for (const p of cohort.preferences) {
      const e = by.get(p.candidate_id) ?? { pos: [], prog: [] };
      e.pos.push(p.position);
      e.prog.push(p.program_id);
      by.set(p.candidate_id, e);
    }
    for (const { pos, prog } of by.values()) {
      expect([...pos].sort((a, b) => a - b)).toEqual(pos.map((_, i) => i + 1));
      expect(new Set(prog).size).toBe(prog.length);
    }
  });
});

describe("candidate listing", () => {
  const rows = candidateRows(cohort, cat, baseline);

  it("ranks by proxy with shared ranks for ties", () => {
    const tiny: Cohort = { ...cohort, candidates: [
      { ...cohort.candidates[0], candidate_id: "a", achievement: { kind: "k", value: 10, scale: "" } },
      { ...cohort.candidates[0], candidate_id: "b", achievement: { kind: "k", value: 30, scale: "" } },
      { ...cohort.candidates[0], candidate_id: "c", achievement: { kind: "k", value: 30, scale: "" } },
      { ...cohort.candidates[0], candidate_id: "d", achievement: null },
    ] };
    expect([...cohortRanks(tiny).entries()]).toEqual([["a", 3], ["b", 1], ["c", 1], ["d", null]]);
  });

  it("filters by ID, score type, proxy range and placement status", () => {
    expect(queryCandidateRows(rows, q({ search: "candidate-00000042" }), cohort).items.map((r) => r.candidate.candidate_id)).toEqual(["candidate-00000042"]);
    const ea = queryCandidateRows(rows, q({ score_types: ["EA"], limit: 2000 }), cohort);
    expect(ea.total_matching).toBe(cohort.candidates.filter((c) => c.score_type === "EA").length);
    const range = queryCandidateRows(rows, q({ proxy_min: 4000, proxy_max: 5000, limit: 2000 }), cohort);
    expect(range.items.every((r) => r.candidate.achievement!.value >= 4000 && r.candidate.achievement!.value <= 5000)).toBe(true);
    const placed = queryCandidateRows(rows, q({ run_id: baseline.run_id, status: "placed", limit: 2000 }), cohort);
    expect(placed.total_matching).toBe(baseline.assignments.filter((a) => a.status === "placed").length);
    // status needs a run: without one it is ignored rather than producing an empty list
    expect(queryCandidateRows(rows, q({ status: "placed" }), cohort).total_matching).toBe(1000);
  });

  it("filters by eligibility from the run, and combines it with placement status", () => {
    const by = (s: string) => baseline.assignments.filter((a) => a.status === s).length;
    const runRows = candidateRows(cohort, cat, baseline);
    expect(queryCandidateRows(runRows, q({ run_id: baseline.run_id, eligibility: "eligible", limit: 2000 }), cohort).total_matching).toBe(by("placed") + by("unplaced"));
    expect(queryCandidateRows(runRows, q({ run_id: baseline.run_id, eligibility: "ineligible", limit: 2000 }), cohort).total_matching).toBe(by("ineligible"));
    expect(queryCandidateRows(runRows, q({ run_id: baseline.run_id, eligibility: "eligible", status: "unplaced", limit: 2000 }), cohort).total_matching).toBe(by("unplaced"));
    expect(queryCandidateRows(runRows, q({ eligibility: "ineligible" }), cohort).total_matching).toBe(1000);
  });

  it("offers a province filter only when the cohort records home locations", () => {
    expect(queryCandidateRows(rows, q(), cohort).provinces).toEqual([]);
    const located = rows.map((r, i) => ({ ...r, candidate: { ...r.candidate, home_location: i % 2 ? "Ankara" : i % 3 ? "İzmir" : null } }));
    const page = queryCandidateRows(located, q({ provinces: ["Ankara"], limit: 2000 }), cohort);
    expect(page.provinces.map((f) => f.value).sort()).toEqual(["Ankara", "İzmir"]);
    expect(page.total_matching).toBe(500);
    expect(page.items.every((r) => r.candidate.home_location === "Ankara")).toBe(true);
  });

  it("sorts by proxy or rank deterministically", () => {
    const byProxy = queryCandidateRows(rows, q({ limit: 2000 }), cohort).items.map((r) => r.candidate.achievement!.value);
    expect(byProxy).toEqual([...byProxy].sort((a, b) => b - a));
    const byRank = queryCandidateRows(rows, q({ sort: "rank", direction: "asc", limit: 2000 }), cohort).items.map((r) => r.cohort_rank!);
    expect(byRank).toEqual([...byRank].sort((a, b) => a - b));
  });

  it("keeps preference order even when the handoff lists them out of order", () => {
    const id = cohort.preferences.find((p) => p.position === 3)!.candidate_id;
    const shuffled: Cohort = { ...cohort, preferences: [...cohort.preferences].reverse() };
    const d = candidateDetail(shuffled, cat, baseline, id)!;
    expect(d.preferences.map((p) => p.position)).toEqual(d.preferences.map((_, i) => i + 1));
    const views = preferenceViews(d, cat, d.row.assignment);
    expect(views.map((v) => v.position)).toEqual(views.map((_, i) => i + 1));
  });

  it("round-trips filters through the URL", () => {
    const s: CandidateUrlState = { search: "x", score_types: ["SAY"], proxy_min: 10, proxy_max: 20, status: "unplaced", eligibility: "eligible", provinces: ["Ankara"],
      sort: "rank", direction: "asc", page: 3, size: 50 };
    expect(candidateStateFromParams(candidateStateToParams(s, new URLSearchParams("run=r1")))).toEqual(s);
  });
});

describe("candidate details", () => {
  it("lists preferences in rank order with the run's outcome and placement", async () => {
    const placed = baseline.assignments.find((a) => a.status === "placed" && (a.preference_position ?? 0) >= 2)!;
    render(<UniversitySourceProvider source={source}><CandidateDetails cohortId={cohortId(42, 1000)} candidateId={placed.candidate_id} runId={baseline.run_id} catalogue={cat} onClose={() => {}} /></UniversitySourceProvider>);
    const list = await screen.findByRole("table", { name: "Ranked preferences" });
    const items = within(list).getAllByRole("row").slice(1);
    expect(items.map((li) => li.getAttribute("aria-label")?.split(":")[0])).toEqual(items.map((_, i) => `Preference ${i + 1}`));
    const assigned = items[placed.preference_position! - 1];
    expect(within(assigned).getByText("Placed here")).toBeInTheDocument();
    for (const li of items.slice(placed.preference_position!)) expect(within(li).getByText(/Not evaluated: placed at an earlier preference/)).toBeInTheDocument();
    const program = cat.programs.find((p) => p.program_code === placed.program_code)!;
    expect(screen.getAllByText(new RegExp(program.name_original)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not in schema").length).toBeGreaterThanOrEqual(1);
    for (const name of ["Candidate overview", "Admission performance", "Placement outcome"]) expect(screen.getByRole("region", { name })).toBeInTheDocument();
    const outcome = screen.getByRole("region", { name: "Placement outcome" });
    expect(within(outcome).getByText(`Preference ${placed.preference_position}`)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Candidate overview" })).getByText("Eligible")).toBeInTheDocument();
  });

  it("shows the simulation's reason for a candidate who was not placed", async () => {
    const unplaced = baseline.assignments.find((a) => a.status === "unplaced")!;
    render(<UniversitySourceProvider source={source}><CandidateDetails cohortId={cohortId(42, 1000)} candidateId={unplaced.candidate_id} runId={baseline.run_id} catalogue={cat} onClose={() => {}} /></UniversitySourceProvider>);
    expect(await screen.findByText(unplaced.reason!)).toBeInTheDocument();
  });

  it("flags an invalid preference reference", async () => {
    const id = cohort.preferences.find((p) => p.program_id === UNKNOWN_PROGRAM_CODE)!.candidate_id;
    render(<UniversitySourceProvider source={source}><CandidateDetails cohortId={cohortId(42, 1000)} candidateId={id} runId={null} catalogue={cat} onClose={() => {}} /></UniversitySourceProvider>);
    expect(await screen.findByText("Invalid reference")).toBeInTheDocument();
    expect(screen.getAllByText("Invalid preference reference").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Select a run for outcomes").length).toBeGreaterThan(0);
  });
});

describe("candidate explorer", () => {
  function Harness() {
    const [state, setState] = useState<CandidateUrlState>(candidateStateFromParams(new URLSearchParams()));
    const [run, setRun] = useState<string | null>(baseline.run_id);
    return (
      <UniversitySourceProvider source={source}>
        <CandidateExplorer snapshot={cat.snapshot} cohorts={[cohort.manifest]} runs={runs} cohortId={cohort.manifest.cohort_id} runId={run}
          onRun={setRun} onCohort={() => {}} state={state} onChange={setState} selected={null} onSelect={() => {}} />
      </UniversitySourceProvider>
    );
  }

  it("renders synthetic candidates with placement and filters by score type and status", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const table = await screen.findByRole("table", { name: /matching synthetic candidates/ });
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(26));
    // Summary tiles come from the whole run, not the page.
    const summary = screen.getByLabelText("Candidate summary");
    await waitFor(() => expect(within(summary).getByText("Placed candidates").closest(".tile")).toHaveTextContent(String(baseline.assignments.filter((a) => a.status === "placed").length)));
    // The cohort writes SOZ; the official spelling SÖZ is displayed, the filter value stays SOZ.
    await user.click(screen.getByRole("checkbox", { name: /^SÖZ/ }));
    await waitFor(() => expect(within(table).getAllByRole("row").slice(1).every((r) => within(r).queryByText("SÖZ"))).toBe(true));
    await user.selectOptions(screen.getByLabelText("Placement status"), "unplaced");
    await waitFor(() => expect(within(table).getAllByRole("row").slice(1).every((r) => within(r).queryByText("Not placed"))).toBe(true));
    expect(screen.getByRole("button", { name: "Remove filter Placement: Not placed" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Simulation run"), "");
    await waitFor(() => expect(screen.getAllByText("No run selected").length).toBeGreaterThan(1));
    expect(screen.getByLabelText("Placement status")).toBeDisabled();
    // Without a run, placement figures are unavailable, not zero.
    expect(within(summary).getAllByText("Select a run")).toHaveLength(3);
  });
});
