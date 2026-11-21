import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { buildCohort } from "@/lib/university/fixtures/candidates";
import { buildRegistryFixture } from "@/lib/university/fixtures/registry";
import { createFixtureSource, FIXTURE_CAPABILITIES } from "@/lib/university/fixtureSource";
import { defaultScenario, hasBlocking, scenarioFingerprint, SCENARIO_CONTRACT_VERSION, serializeScenario, validateScenario } from "@/lib/university/scenario";
import type { SubmitResult } from "@/lib/university/source";
import type { ScenarioConfig, SimulationRun } from "@/lib/university/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/university/scenarios",
}));

const { UniversitySourceProvider } = await import("@/lib/university/context");
const { ScenarioSetup } = await import("@/components/university/ScenarioSetup");

const cat = buildRegistryFixture();
const cohort = buildCohort(42, 1000).manifest;
const base = defaultScenario(cat, { cohort_id: cohort.cohort_id, generator_version: cohort.generator_version, seed: 42, size: 1000 });
const codes = (c: ScenarioConfig) => validateScenario(c, cat, FIXTURE_CAPABILITIES, cat.snapshot.snapshot_id).filter((f) => f.blocking).map((f) => f.code);

describe("scenario validation", () => {
  it("accepts the baseline and flags demo mode and missing quotas without blocking", () => {
    const f = validateScenario(base, cat, FIXTURE_CAPABILITIES, cat.snapshot.snapshot_id);
    expect(hasBlocking(f)).toBe(false);
    expect(f.map((x) => x.code)).toEqual(expect.arrayContaining(["fixture_mode", "missing_quota"]));
  });

  it("requires a name", () => {
    expect(codes({ ...base, name: "   " })).toContain("name_required");
    expect(codes({ ...base, name: "x".repeat(81) })).toContain("name_too_long");
  });

  it("rejects invalid numeric ranges", () => {
    expect(codes({ ...base, cohort: { ...base.cohort, size: 0 } })).toContain("cohort_size_invalid");
    expect(codes({ ...base, cohort: { ...base.cohort, size: 1.5 } })).toContain("cohort_size_invalid");
    expect(codes({ ...base, cohort: { ...base.cohort, size: 50_000 } })).toContain("cohort_size_too_large");
    expect(codes({ ...base, cohort: { ...base.cohort, seed: -1 } })).toContain("cohort_seed_invalid");
    expect(codes({ ...base, seed: Number.NaN })).toContain("seed_invalid");
    expect(codes({ ...base, quota_adjustment_pct: 500 })).toContain("quota_adjustment_out_of_range");
    expect(codes({ ...base, quota_adjustment_pct: -95 })).toContain("quota_adjustment_out_of_range");
  });

  it("rejects unavailable datasets, unsupported years and incompatible cohorts", () => {
    expect(codes({ ...base, registry_snapshot_id: "sha256:unknown" })).toContain("dataset_unavailable");
    expect(codes({ ...base, admission_year: 2019 })).toContain("year_unsupported");
    expect(validateScenario(base, cat, FIXTURE_CAPABILITIES, "fixture:other").filter((f) => f.blocking).map((f) => f.code)).toContain("cohort_snapshot_mismatch");
    expect(validateScenario(base, undefined, FIXTURE_CAPABILITIES).map((f) => f.code)).toContain("dataset_unavailable");
  });

  it("rejects invalid institution and program references and quota constraints", () => {
    expect(codes({ ...base, included_university_keys: [] })).toContain("no_institutions");
    expect(codes({ ...base, included_university_keys: ["nope"] })).toContain("unknown_institution");
    expect(codes({ ...base, program_quota_overrides: { "123456789": 5 } })).toContain("override_unknown_program");
    const p = cat.programs[0];
    expect(codes({ ...base, program_quota_overrides: { [p.program_code]: -1 } })).toContain("override_invalid");
    expect(codes({ ...base, program_quota_overrides: { [p.program_code]: 2.5 } })).toContain("override_invalid");
    const other = cat.universities.find((u) => u.university_id !== p.university_id)!;
    expect(codes({ ...base, included_university_keys: [other.university_key], program_quota_overrides: { [p.program_code]: 5 } })).toContain("override_excluded_program");
    const quarantined = cat.issues.find((i) => i.issue_code === "invalid_annual")!;
    const qp = cat.programs.find((x) => x.program_id === quarantined.program_id)!;
    expect(codes({ ...base, admission_year: quarantined.related_year!, program_quota_overrides: { [qp.program_code]: 5 } })).toContain("override_no_admission_row");
  });

  it("refuses scenario types with no simulation mechanism", () => {
    expect(codes({ ...base, preset: "scholarship_change" })).toContain("preset_unsupported");
    expect(codes({ ...base, preset: "preference_change" })).toContain("preset_unsupported");
  });
});

describe("scenario serialization", () => {
  it("is canonical: sorted keys, contract version, trimmed name, sorted institutions", () => {
    const c: ScenarioConfig = { ...base, name: "  My scenario ", included_university_keys: [cat.universities[3].university_key, cat.universities[0].university_key] };
    const json = serializeScenario(c);
    const parsed = JSON.parse(json);
    expect(parsed.contract_version).toBe(SCENARIO_CONTRACT_VERSION);
    expect(parsed.name).toBe("My scenario");
    expect(parsed.included_university_keys).toEqual([...c.included_university_keys!].sort());
    expect(Object.keys(parsed)).toEqual([...Object.keys(parsed)].sort());
    expect(serializeScenario({ ...c, program_quota_overrides: { b: 1, a: 2 } })).toBe(serializeScenario({ ...c, program_quota_overrides: { a: 2, b: 1 } }));
    expect(parsed).toMatchObject({ admission_year: c.admission_year, seed: c.seed, quota_adjustment_pct: c.quota_adjustment_pct, cohort: c.cohort, registry_snapshot_id: c.registry_snapshot_id });
  });

  it("fingerprints parameters, not labels", () => {
    expect(scenarioFingerprint({ ...base, name: "other", preset: "custom" })).toBe(scenarioFingerprint(base));
    expect(scenarioFingerprint({ ...base, quota_adjustment_pct: 10 })).not.toBe(scenarioFingerprint(base));
  });
});

function renderSetup(source = createFixtureSource({ persist: false })) {
  render(
    <UniversitySourceProvider source={source}>
      <ScenarioSetup catalogue={cat} snapshots={[cat.snapshot]} caps={FIXTURE_CAPABILITIES} cohortBase={cohort} />
    </UniversitySourceProvider>,
  );
  return source;
}

describe("scenario setup", () => {
  it("identifies demo mode and marks unsupported presets", () => {
    renderSetup();
    expect(screen.getByRole("button", { name: "Run fixture preview" })).toBeEnabled();
    expect(screen.getAllByText(/Demo mode/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Scholarship availability change/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Candidate preference change/ })).toBeDisabled();
    expect(screen.getAllByText("Fixture preview only")).toHaveLength(3);
  });

  it("blocks running when a required field is empty and explains why", async () => {
    const user = userEvent.setup();
    renderSetup();
    await user.clear(screen.getByLabelText("Scenario name"));
    expect(screen.getByLabelText("Scenario name")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getAllByText("Enter a scenario name.").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Run fixture preview" })).toBeDisabled();
    await user.clear(screen.getByLabelText("Candidate count"));
    await user.type(screen.getByLabelText("Candidate count"), "0");
    expect(screen.getAllByText(/Candidate count must be a whole number/).length).toBeGreaterThan(0);
  });

  it("applies a preset, runs a fixture preview and prevents a duplicate run", async () => {
    const user = userEvent.setup();
    const source = renderSetup();
    await user.click(screen.getByRole("button", { name: /Reduced program quotas/ }));
    expect(screen.getByLabelText("Program quota adjustment (%)")).toHaveValue(-30);
    await user.click(screen.getByRole("button", { name: "Run fixture preview" }));
    const status = await screen.findByText("Fixture preview completed");
    expect(within(status.closest("[role=status]") as HTMLElement).getByText(/No backend simulation ran/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View placement results" }).getAttribute("href")).toMatch(/run=fx-/);
    // Scenario C is also a built-in run, so even the first submission is recognised as a duplicate.
    expect(screen.getByText(/identical configuration was already run/)).toBeInTheDocument();
    const before = (await source.listRuns()).length;
    await user.clear(screen.getByLabelText("Program quota adjustment (%)"));
    await user.type(screen.getByLabelText("Program quota adjustment (%)"), "-10");
    await user.click(screen.getByRole("button", { name: "Run fixture preview" }));
    await screen.findByText("Fixture preview completed");
    expect((await source.listRuns()).length).toBe(before + 1);
    await user.click(screen.getByRole("button", { name: "Run fixture preview" }));
    await waitFor(() => expect(screen.getByText(/identical configuration was already run/)).toBeInTheDocument());
    expect((await source.listRuns()).length).toBe(before + 1);
  });

  it("submits once even when clicked twice while a submission is in flight", async () => {
    const user = userEvent.setup();
    const real = createFixtureSource({ persist: false });
    let resolve!: (v: SubmitResult) => void;
    const submitScenario = vi.fn(() => new Promise<SubmitResult>((r) => { resolve = r; }));
    renderSetup({ ...real, submitScenario });
    const button = screen.getByRole("button", { name: "Run fixture preview" });
    await user.dblClick(button);
    expect(submitScenario).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
    resolve(await real.submitScenario(base));
    expect(await screen.findByText("Fixture preview completed")).toBeInTheDocument();
  });

  it("shows pending, then completed after a status refresh, for an API-style run", async () => {
    const user = userEvent.setup();
    const real = createFixtureSource({ persist: false });
    const done = (await real.submitScenario(base)).run;
    const pending: SimulationRun = { ...done, status: "pending", origin: "api", kind: "api" };
    const getRun = vi.fn().mockResolvedValue({ ...done, origin: "api", kind: "api" });
    renderSetup({ ...real, submitScenario: vi.fn().mockResolvedValue({ run: pending, duplicate_of: null }), getRun });
    await user.click(screen.getByRole("button", { name: "Run fixture preview" }));
    expect(await screen.findByText("Pending")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View placement results" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View placement results" })).toBeInTheDocument();
  });

  it("reports a failed submission and allows a retry", async () => {
    const user = userEvent.setup();
    const real = createFixtureSource({ persist: false });
    const submitScenario = vi.fn(real.submitScenario).mockRejectedValueOnce(new ApiError(503, "busy", "Simulation queue unavailable"));
    renderSetup({ ...real, submitScenario });
    await user.click(screen.getByRole("button", { name: "Run fixture preview" }));
    expect(await screen.findByText(/Simulation queue unavailable/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry submission" }));
    expect(await screen.findByText("Fixture preview completed")).toBeInTheDocument();
    expect(submitScenario).toHaveBeenCalledTimes(2);
  });

  it("rejects an invalid scenario at the data source too", async () => {
    const source = createFixtureSource({ persist: false });
    await expect(source.submitScenario({ ...base, name: "" })).rejects.toMatchObject({ status: 422, code: "invalid_scenario" });
  });
});
