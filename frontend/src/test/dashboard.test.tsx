import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/lib/api/client";
import type { Overview, ProvinceCoverage, ValidationReport } from "@/lib/api/v2";
import { coverageNote } from "@/lib/coverage";
import { featuredRun } from "@/lib/recordedRuns";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/",
}));

const { PersonaPair } = await import("@/components/historical/PersonaPair");
const { PipelineStatus } = await import("@/components/dashboard/PipelineStatus");

function province(code: string, name: string, controls: boolean): ProvinceCoverage {
  return { province_code: code, province_name: name, nuts3_code: "TR000", nuts2_code: "TR00", nuts1_code: "TR0", nuts1_name: "x", iso_3166_2: `TR-${code}`,
    has_population_controls: controls, control_tables: [], context_indicators: 0, records: 0, represented_population: null };
}

describe("coverage note", () => {
  const all = Array.from({ length: 81 }, (_, i) => String(i + 1).padStart(2, "0"));
  it("names the loaded provinces and never implies the rest are populated", () => {
    expect(coverageNote({ province_count: 81, provinces: all.map((c) => province(c, c === "06" ? "Ankara" : `P${c}`, c === "06")) }))
      .toBe("The national architecture supports all 81 provinces. Current official source data is loaded for Ankara only.");
    expect(coverageNote({ province_count: 81, provinces: all.map((c) => province(c, `P${c}`, ["01", "06", "69"].includes(c))) }))
      .toMatch(/loaded for P01, P06 and P69 only\.$/);
    expect(coverageNote({ province_count: 81, provinces: all.map((c) => province(c, `P${c}`, Number(c) <= 10)) })).toMatch(/loaded for 10 of 81 provinces\.$/);
    expect(coverageNote({ province_count: 81, provinces: all.map((c) => province(c, `P${c}`, false)) })).toMatch(/No official source data is loaded yet\.$/);
  });

  it("switches to full coverage by itself when every province has source data", () => {
    expect(coverageNote({ province_count: 81, provinces: all.map((c) => province(c, `P${c}`, true)) })).toBe("Official source data is loaded for all 81 provinces.");
  });

  it("names the attributes covered everywhere and the ones no table supports", () => {
    const tables = ["population_age_sex", "marital_status_sex", "education_sex", "urbanicity_sex"];
    const provinces = all.map((c) => ({ ...province(c, `P${c}`, true), control_tables: tables }));
    expect(coverageNote({ province_count: 81, provinces })).toBe("Official source data is loaded for all 81 provinces: age group × sex, "
      + "marital status, education and settlement type. No province-level table supports labour status, household size and household type, "
      + "so they stay unavailable.");
  });
});

describe("featured recorded run", () => {
  const item = (name: string, state: string) => ({ experiment_id: `imp_${name}`, name, display_state: state }) as Schemas["ExperimentListItem"];
  it("is the last completed run, chosen by recorded state rather than by name", () => {
    expect(featuredRun([item("run2", "completed"), item("run3", "completed"), item("smoke", "completed_fake"), item("live", "partial")])?.name).toBe("run3");
    expect(featuredRun([item("smoke", "completed_fake"), item("x", "outcome_unknown")])).toBeUndefined();
    expect(featuredRun(undefined)).toBeUndefined();
  });
});

function trial(label: string, id: string, dims: Record<string, string>, attrs: Record<string, string>): Schemas["Trial"] {
  return { label, persona_id: id, state: "result_recorded", persona_snapshot: { sha256: `sha-${id}`, parse_error: false, persona_id: id, dimensions: dims,
    source_attributes: attrs, source_csv_row: 2, unassigned_fields: ["education"], relpath: `trial_${label}/persona.yaml` } } as unknown as Schemas["Trial"];
}

function view(id: string, dims: Record<string, string>): Schemas["PersonaView"] {
  return {
    record_id: id, notes: { gender_field: "Administrative sex category." },
    source_card: { attributes: {}, display_translations: { marital_status: { Evli: "Married", "Eşi öldü": "Widowed" } } },
    personas: [{ sha256: `sha-${id}`, relpath: `personas/${id}.yaml`, prompt_visible_fields: Object.keys(dims), metadata_only_fields: ["gender"],
      mapped_fields: [
        { dimension: "age_bracket", value: dims.age_bracket, source_field: "age_group" },
        { dimension: "demo_marital_status", value: dims.demo_marital_status, source_field: "marital_status" },
        { dimension: "dst_residence_province", value: dims.dst_residence_province, source_field: "province" },
      ], mapping_warnings: ["Source sex is kept in metadata only; it is not a prompt dimension."], metadata: { generation_seed: 42 },
      source_row_check: { passed: true, detail: "Row matches." }, attribution_note: null }],
  } as unknown as Schemas["PersonaView"];
}

describe("persona A vs B", () => {
  const dimsA = { dst_residence_province: "Ankara", age_bracket: "45-54", demo_marital_status: "Married" };
  const dimsB = { dst_residence_province: "Ankara", age_bracket: "75-84", demo_marital_status: "Widowed" };
  const trials = [trial("A", "ANK_1", dimsA, { age_group: "45-49", gender: "female", marital_status: "Evli" }),
    trial("B", "ANK_2", dimsB, { age_group: "80-84", gender: "female", marital_status: "Eşi öldü" })];
  const result = { comparison_rows: Array.from({ length: 9 }, (_, i) => ({ question_id: `q${i}` })), differing_values_recomputed: 9,
    differing_values_recorded: 9 } as unknown as Schemas["Results"];

  it("shows both recorded personas, what the model saw, and the recorded comparison", () => {
    render(<PersonaPair result={result} trials={trials} views={new Map([["ANK_1", view("ANK_1", dimsA)], ["ANK_2", view("ANK_2", dimsB)]])} linkBuild={null} />);
    const a = screen.getByRole("article", { name: "Persona A" });
    const b = screen.getByRole("article", { name: "Persona B" });
    expect(a).toHaveTextContent("ANK_1");
    expect(a).toHaveTextContent("45-49");
    expect(a).toHaveTextContent("Married (Evli)");
    expect(b).toHaveTextContent("Widowed (Eşi öldü)");
    expect(within(a).getByText("Not shown to the model")).toBeInTheDocument();
    expect(a).toHaveTextContent("Model saw residence province “Ankara”");
    const verdict = screen.getByRole("group", { name: "Recorded comparison" });
    expect(verdict).toHaveTextContent("9 / 9");
    expect(verdict).toHaveTextContent("survey answers differed");
    expect(verdict).toHaveTextContent("Model-visible differences: age bracket, marital status.");
  });

  it("reports a disagreement between the comparison file and the recomputed count", () => {
    render(<PersonaPair result={{ ...result, differing_values_recorded: 8 }} trials={trials} views={undefined} linkBuild={null} />);
    expect(screen.getByText("The comparison file records 8.")).toBeInTheDocument();
    expect(screen.getAllByText(/No stored persona in the selected build matches/)).toHaveLength(2);
  });
});

describe("pipeline status", () => {
  const overview = {
    controls: { status: "built", built_at: "2026-10-18T16:20:19Z", tables: ["population_age_sex", "marital_status_sex"] },
    populations: [{ population_id: "p1", synthetic_size: 100000 }], default_population_id: "p1", provinces_with_population_controls: 1, province_count: 81,
    saved_cohorts: 0, experiments: 0, personas_used_in_completed_runs: 0, latest_run: null,
  } as unknown as Overview;
  const caps = { backends: { stub: { available: true, reasons: [] }, matraix_fake: { available: false, reasons: ["x"] }, matraix_live: { available: false, reasons: ["y"] } } };
  const validation = { constraint_violations: 0, provinces: [{ tables: [{}, {}] }] } as unknown as ValidationReport;

  it("reads every stage from API state and shows source coverage as n / 81", () => {
    render(<PipelineStatus overview={overview} caps={caps as never} validation={validation} recordedCompleted={2} pop={null} />);
    const stages = screen.getAllByRole("listitem");
    expect(stages.map((li) => li.querySelector(".pipe-name")?.textContent)).toEqual(["Data", "Synthetic population", "Cohorts", "Personas", "Experiments", "Results"]);
    expect(stages[0]).toHaveTextContent("Loaded");
    expect(stages[0]).toHaveTextContent("1 / 81 provinces · 2 control tables");
    expect(stages[1]).toHaveTextContent("1 saved · newest 100,000 records");
    expect(stages[2]).toHaveTextContent("No cohort saved yet");
    expect(stages[4]).toHaveTextContent("Backends available: stub (offline)");
    expect(stages[5]).toHaveTextContent("No national run yet · 2 completed historical runs recorded");
    expect(screen.getByText(/Source data loaded: 1 \/ 81/)).toBeInTheDocument();
    expect(screen.getByText(/2 source-table fit checks · 0 constraint violations · not a behavioural validation/)).toBeInTheDocument();
  });

  it("counts calibration margins that small provinces could not carry", () => {
    const partial = { ...validation, calibration: [
      { province_code: "69", calibrated: true, margins: ["population_age_sex"], margins_not_calibrated: [{ margin: "education_sex", records: 97, reason: "x" }] },
      { province_code: "75", calibrated: true, margins: ["population_age_sex"], margins_not_calibrated: [{ margin: "marital_status_sex", records: 90, reason: "y" }] },
      { province_code: "06", calibrated: true, margins: ["population_age_sex", "education_sex"], margins_not_calibrated: [] },
    ] } as unknown as ValidationReport;
    render(<PipelineStatus overview={overview} caps={caps as never} validation={partial} recordedCompleted={2} pop={null} />);
    expect(screen.getByText(/0 constraint violations · 2 calibration margins not imposed \(small provinces\) · not a behavioural validation/)).toBeInTheDocument();
  });

  it("does not report stages as working before their inputs exist", () => {
    render(<PipelineStatus overview={{ ...overview, controls: { status: "not_built", built_at: null, tables: [] }, populations: [], default_population_id: null,
      provinces_with_population_controls: 0 }} caps={undefined} validation={undefined} recordedCompleted={null} pop={null} />);
    const stages = screen.getAllByRole("listitem");
    expect(stages[0]).toHaveTextContent("Not built");
    expect(stages[1]).toHaveTextContent("Not generated");
    expect(stages[2]).toHaveTextContent("Needs a population");
    expect(stages[3]).toHaveTextContent("Needs a population");
    expect(screen.getByText("Validation runs once a population exists.")).toBeInTheDocument();
  });
});
