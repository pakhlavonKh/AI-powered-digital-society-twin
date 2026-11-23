import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { buildRegistryFixture, FIXTURE_SNAPSHOT_ID, generateRegistryFixture } from "@/lib/university/fixtures/registry";
import { createFixtureSource } from "@/lib/university/fixtureSource";
import {
  defaultProgramState, filterProgramRows, programFacets, programRows, programStateFromParams, programStateToParams, queryProgramRows,
  sortProgramRows, type ProgramUrlState,
} from "@/lib/university/programs";
import { allFindings, catalogueChecks } from "@/lib/university/quality";
import { MISSING_VALUE, type ProgramQuery, type RegistryCatalogue } from "@/lib/university/types";
import { foldTr } from "@/lib/university/util";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/university/programs",
}));

const { UniversitySourceProvider } = await import("@/lib/university/context");
const { ProgramExplorer } = await import("@/components/university/ProgramExplorer");

const cat = buildRegistryFixture();
const LATEST = cat.snapshot.admission_years[cat.snapshot.admission_years.length - 1];
const baseQuery = (patch: Partial<ProgramQuery> = {}): ProgramQuery => ({
  ...defaultProgramState(LATEST), snapshot_id: FIXTURE_SNAPSHOT_ID, offset: 0, limit: 25, ...patch,
});

describe("registry fixture", () => {
  it("is deterministic and mirrors the registry schema's identity rules", () => {
    expect(JSON.stringify(generateRegistryFixture())).toBe(JSON.stringify(generateRegistryFixture()));
    const codes = cat.programs.map((p) => p.program_code);
    expect(new Set(codes).size).toBe(codes.length);
    for (const code of codes) expect(code).toMatch(/^0\d{8}$/); // text codes keep their leading zeros
    const programIds = new Set(cat.programs.map((p) => p.program_id));
    for (const a of cat.admissions) expect(programIds.has(a.program_id)).toBe(true);
    const keys = cat.admissions.map((a) => `${a.program_id}:${a.admission_year}`);
    expect(new Set(keys).size).toBe(keys.length);
    expect(cat.snapshot.origin).toBe("fixture");
    expect(cat.snapshot.counts.programs).toBe(cat.programs.length);
  });

  it("keeps NULLs as missing and never caps placed counts", () => {
    expect(cat.admissions.some((a) => a.quota === null)).toBe(true);
    expect(cat.admissions.some((a) => a.success_rank === null)).toBe(true);
    const above = cat.admissions.filter((a) => a.quota !== null && a.placed_students !== null && a.placed_students > a.quota);
    expect(above.length).toBeGreaterThan(0);
    expect(cat.issues.filter((i) => i.issue_code === "placed_above_quota")).toHaveLength(above.length);
  });
});

describe("program filters, search, sorting and pagination", () => {
  const rows = programRows(cat, LATEST);
  const none = { score_types: [], scholarships: [], university_keys: [], university_types: [], teaching_languages: [], search: "" };

  it("filter each field independently", () => {
    expect(filterProgramRows(rows, { ...none, score_types: ["SAY"] }).every((r) => r.program.score_type === "SAY")).toBe(true);
    expect(filterProgramRows(rows, { ...none, scholarships: ["Burslu"] }).every((r) => r.program.scholarship_original === "Burslu")).toBe(true);
    const uni = cat.universities[2].university_key;
    expect(filterProgramRows(rows, { ...none, university_keys: [uni] }).every((r) => r.university.university_key === uni)).toBe(true);
    expect(filterProgramRows(rows, { ...none, university_types: ["Vakıf"] }).every((r) => r.university.university_type === "Vakıf")).toBe(true);
    const missingType = filterProgramRows(rows, { ...none, university_types: [MISSING_VALUE] });
    expect(missingType.length).toBeGreaterThan(0);
    expect(missingType.every((r) => r.university.university_type === null)).toBe(true);
  });

  it("combine with AND across fields and OR within a field", () => {
    const both = filterProgramRows(rows, { ...none, score_types: ["EA"], scholarships: ["Burslu"] });
    expect(both.length).toBeGreaterThan(0);
    expect(both.every((r) => r.program.score_type === "EA" && r.program.scholarship_original === "Burslu")).toBe(true);
    const either = filterProgramRows(rows, { ...none, score_types: ["EA", "SAY"] });
    expect(either.length).toBe(filterProgramRows(rows, { ...none, score_types: ["EA"] }).length + filterProgramRows(rows, { ...none, score_types: ["SAY"] }).length);
  });

  it("search ignores case and Turkish accents and matches codes", () => {
    expect(foldTr("Mühendisliği İŞLETME")).toBe("muhendisligi isletme");
    const hits = filterProgramRows(rows, { ...none, search: "muhendisligi" });
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.every((r) => r.program.name_original.includes("Mühendisliği"))).toBe(true);
    const code = rows[0].program.program_code;
    expect(filterProgramRows(rows, { ...none, search: code }).map((r) => r.program.program_code)).toEqual([code]);
    expect(filterProgramRows(rows, { ...none, search: "no such program xyz" })).toHaveLength(0);
  });

  it("sort deterministically with missing values last in both directions", () => {
    for (const dir of ["asc", "desc"] as const) {
      const sorted = sortProgramRows(rows, "quota", dir);
      expect(sortProgramRows([...rows].reverse(), "quota", dir).map((r) => r.key)).toEqual(sorted.map((r) => r.key));
      const firstNull = sorted.findIndex((r) => r.admission?.quota === null);
      if (firstNull >= 0) expect(sorted.slice(firstNull).every((r) => r.admission?.quota === null)).toBe(true);
      const known = sorted.filter((r) => r.admission?.quota !== null).map((r) => r.admission!.quota!);
      expect(known).toEqual([...known].sort((a, b) => (dir === "asc" ? a - b : b - a)));
    }
  });

  it("paginate without overlap and clamp past the end", () => {
    const all = programRows(cat, null).length;
    const p1 = queryProgramRows(cat, baseQuery({ year: null, offset: 0 }));
    const p2 = queryProgramRows(cat, baseQuery({ year: null, offset: 25 }));
    expect(p1.total_matching).toBe(all);
    expect(p1.items).toHaveLength(25);
    expect(new Set([...p1.items, ...p2.items].map((r) => r.key)).size).toBe(50);
    const beyond = queryProgramRows(cat, baseQuery({ year: null, offset: 10_000 }));
    expect(beyond.items.length).toBeGreaterThan(0);
    expect(beyond.offset).toBe(Math.floor((all - 1) / 25) * 25);
  });

  it("count missing quotas instead of adding them as zero", () => {
    const page = queryProgramRows(cat, baseQuery({ year: 2025, limit: 1000 }));
    const known = page.items.reduce((s, r) => s + (r.admission?.quota ?? 0), 0);
    expect(page.matching_missing_quota).toBe(page.items.filter((r) => r.admission?.quota === null).length);
    expect(page.matching_missing_quota).toBeGreaterThan(0);
    expect(page.matching_known_quota).toBe(known);
  });

  it("offer only filter values present in the data", () => {
    const f = programFacets(cat);
    const observed = new Set(cat.programs.map((p) => p.score_type ?? MISSING_VALUE));
    expect(new Set(f.score_types.map((s) => s.value))).toEqual(observed);
    expect(f.cities).toEqual([]); // no city recorded anywhere, so no city filter
    expect(f.years).toEqual(cat.snapshot.admission_years);
  });

  it("round-trip through the URL and keep unrelated parameters", () => {
    const state: ProgramUrlState = { ...defaultProgramState(LATEST), year: 2024, score_types: ["SAY", "EA"], scholarships: ["Burslu"], search: "hukuk", sort: "quota", direction: "desc", page: 2 };
    const params = programStateToParams(state, LATEST, new URLSearchParams("snapshot=s1&program=001"));
    expect(params.get("snapshot")).toBe("s1");
    expect(params.get("program")).toBe("001");
    expect(programStateFromParams(params, LATEST)).toEqual(state);
    expect(programStateToParams(defaultProgramState(LATEST), LATEST).toString()).toBe("");
    expect(programStateFromParams(new URLSearchParams("year=all"), LATEST).year).toBeNull();
    expect(programStateFromParams(new URLSearchParams("sort=bogus&page=-3"), LATEST)).toMatchObject({ sort: "university", page: 0 });
  });
});

describe("registry quality checks", () => {
  it("report missing quota, unknown and missing score types, and pass importer issues through unchanged", () => {
    const codes = new Set(allFindings(cat).map((f) => f.code));
    for (const c of ["missing_quota", "unknown_score_type", "missing_score_type", "placed_above_quota", "invalid_annual", "duplicate_program"]) expect(codes).toContain(c);
    expect(allFindings(cat).filter((f) => f.origin === "source_import")).toHaveLength(cat.issues.length);
  });

  it("flag duplicate program records and programs without a university", () => {
    const broken: RegistryCatalogue = { ...cat, programs: [...cat.programs, { ...cat.programs[0], program_id: 9999 }, { ...cat.programs[1], program_id: 9998, program_code: "000000000", university_id: 777 }] };
    const codes = catalogueChecks(broken).map((f) => f.code);
    expect(codes).toContain("duplicate_program_record");
    expect(codes).toContain("missing_university");
  });
});

function Harness({ source = createFixtureSource({ persist: false }), initial }: { source?: ReturnType<typeof createFixtureSource>; initial?: Partial<ProgramUrlState> }) {
  const [state, setState] = useState<ProgramUrlState>({ ...defaultProgramState(LATEST), ...initial });
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <UniversitySourceProvider source={source}>
      <ProgramExplorer snapshot={cat.snapshot} state={state} onChange={setState} selected={selected} onSelect={setSelected} />
    </UniversitySourceProvider>
  );
}

const table = () => screen.getByRole("table", { name: /matching program-year rows/ });
const bodyRows = () => within(table()).getAllByRole("row").slice(1);

describe("program explorer", () => {
  it("renders registry rows, filters by score type, and resets", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await waitFor(() => expect(bodyRows().length).toBe(25));
    expect(screen.getAllByText("Historical registry data").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("checkbox", { name: /^TYT/ }));
    await waitFor(() => expect(bodyRows().every((r) => within(r).queryByText("TYT") !== null)).toBe(true));
    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    await waitFor(() => expect(bodyRows().length).toBe(25));
    expect(screen.getByRole("checkbox", { name: /^TYT/ })).not.toBeChecked();
  });

  it("searches on Enter and shows an empty state when nothing matches", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await waitFor(() => expect(bodyRows().length).toBe(25));
    await user.type(screen.getByLabelText("Search university or program"), "zzz-nothing{Enter}");
    expect(await screen.findByText("No programs match these filters.")).toBeInTheDocument();
  });

  it("shows a missing quota as missing, never as zero", async () => {
    const missing = cat.admissions.find((a) => a.quota === null)!;
    const program = cat.programs.find((p) => p.program_id === missing.program_id)!;
    render(<Harness initial={{ year: missing.admission_year, search: program.program_code }} />);
    await waitFor(() => expect(bodyRows()).toHaveLength(1));
    const cells = within(bodyRows()[0]).getAllByRole("cell");
    const quotaCell = cells[5];
    expect(quotaCell).toHaveTextContent("Missing from source");
    expect(quotaCell).not.toHaveTextContent(/^0$/);
  });

  it("opens program details with history, source metadata, missing fields and warnings", async () => {
    const user = userEvent.setup();
    const target = cat.issues.find((i) => i.issue_code === "placed_above_quota")!;
    const program = cat.programs.find((p) => p.program_id === target.program_id)!;
    render(<Harness initial={{ year: null, search: program.program_code }} />);
    await waitFor(() => expect(bodyRows().length).toBeGreaterThan(0));
    await user.click(within(bodyRows()[0]).getByRole("button", { name: /Open details/ }));
    const detail = await screen.findByRole("region", { name: new RegExp(program.name_original) });
    expect(within(detail).getByRole("table", { name: /Admission history/ })).toBeInTheDocument();
    expect(within(detail).getAllByText(FIXTURE_SNAPSHOT_ID).length).toBeGreaterThan(0);
    expect(within(within(detail).getByRole("region", { name: "Missing fields" })).getByText(/Degree level/)).toBeInTheDocument();
    expect(within(detail).getAllByText("Placed count above reported quota").length).toBeGreaterThan(0);
    await user.click(within(detail).getByRole("button", { name: "Close details" }));
    expect(screen.queryByRole("region", { name: new RegExp(program.name_original) })).toBeNull();
  });

  it("shows an error state when the registry fails and recovers on retry", async () => {
    const user = userEvent.setup();
    const real = createFixtureSource({ persist: false });
    const queryPrograms = vi.fn(real.queryPrograms).mockRejectedValueOnce(new ApiError(503, "unavailable", "Registry offline"));
    render(<Harness source={{ ...real, queryPrograms }} />);
    expect(await screen.findByText(/Registry offline/)).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    await waitFor(() => expect(bodyRows().length).toBe(25));
  });

  it("lists every data-quality finding with counts", async () => {
    render(<Harness />);
    const panel = await screen.findByRole("region", { name: "Data quality" });
    const warnings = allFindings(cat).filter((f) => f.severity === "warning").length;
    expect(within(panel).getByText("Warnings").closest(".tile")).toHaveTextContent(String(warnings));
  });
});
