import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createPendingApiSource } from "@/lib/university/apiSource";
import { buildRegistryFixture, FIXTURE_SNAPSHOT_ID } from "@/lib/university/fixtures/registry";
import { createFixtureSource } from "@/lib/university/fixtureSource";
import type { Finding } from "@/lib/university/types";

const nav = vi.hoisted(() => ({ pathname: "/university/programs", params: new URLSearchParams(""), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => nav.pathname,
}));
vi.mock("@/lib/population", () => ({
  withPop: (p: string) => p,
  usePopulation: () => ({ items: [], population: null, populationId: null, usingDefault: false, missingId: null, loading: false, error: undefined, reload: () => {}, select: () => {} }),
}));

const { UniversitySourceProvider } = await import("@/lib/university/context");
const { DataQualityPanel, Missing, ProvenancePanel, ValidationList, Value } = await import("@/components/university/common");
const { ProgramExplorer } = await import("@/components/university/ProgramExplorer");
const { AppShell } = await import("@/components/AppShell");
const { defaultProgramState } = await import("@/lib/university/programs");
const { useUrlParams } = await import("@/lib/university/urlState");

const cat = buildRegistryFixture();
const finding = (i: number, severity: Finding["severity"], blocking = false): Finding =>
  ({ code: "missing_quota", severity, blocking, origin: "frontend_check", message: `Finding ${i}`, record: `Program ${i}` });

describe("missing values", () => {
  it("render explicit states and keep zero as a value", () => {
    render(<><Value value={null} /><Value value={0} /><Missing reason="pending_backend" /><Missing reason="not_applicable" /></>);
    expect(screen.getByText("Missing from source")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Pending backend integration")).toBeInTheDocument();
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
  });
});

describe("provenance panel", () => {
  it("shows source metadata and keeps absent fields visible with their reason", () => {
    render(<ProvenancePanel origin="fixture" items={[
      { label: "Registry snapshot", value: FIXTURE_SNAPSHOT_ID, mono: true },
      { label: "File SHA-256", value: null, missing: "not_applicable" },
      { label: "Source retrieved", value: undefined, missing: "missing_from_source" },
      { label: "Simulation version", value: "" },
    ]} />);
    const panel = screen.getByRole("region", { name: "Data provenance" });
    expect(within(panel).getByText(FIXTURE_SNAPSHOT_ID)).toBeInTheDocument();
    expect(within(panel).getByText("Fixture data")).toBeInTheDocument();
    expect(within(panel).getByText("Not applicable")).toBeInTheDocument();
    expect(within(panel).getByText("Missing from source")).toBeInTheDocument();
    expect(within(panel).getByText("Not available")).toBeInTheDocument();
    expect(within(panel).getAllByRole("term")).toHaveLength(4);
  });
});

describe("validation list", () => {
  it("counts every finding, separates errors from warnings and never drops any", async () => {
    const user = userEvent.setup();
    const findings = [...Array.from({ length: 60 }, (_, i) => finding(i, "warning")), finding(100, "error", true), finding(101, "info")];
    render(<ValidationList findings={findings} title="Checks" />);
    expect(screen.getByRole("status")).toHaveTextContent("1 blocking · 1 error · 60 warnings · 1 info");
    expect(screen.getByText("Blocking error")).toBeInTheDocument();
    expect(screen.getByText("Warnings (60)")).toBeInTheDocument();
    expect(screen.getAllByText(/^Finding \d+$/).length).toBe(52); // 50 warnings shown + error + info
    await user.click(screen.getByRole("button", { name: "Show all 60" }));
    expect(screen.getAllByText(/^Finding \d+$/).length).toBe(62);
  });

  it("feeds the data-quality panel's counts", () => {
    render(<DataQualityPanel records={10} incomplete={3} findings={[finding(1, "warning"), finding(2, "error")]} origin="fixture" source="x" version={null} />);
    const panel = screen.getByRole("region", { name: "Data quality" });
    expect(within(panel).getByText("Incomplete records").closest(".tile")).toHaveTextContent("3");
    expect(within(panel).getByText("Warnings").closest(".tile")).toHaveTextContent("1");
    expect(within(panel).getByText("Errors").closest(".tile")).toHaveTextContent("1");
    expect(within(panel).getByText("Data source").closest(".tile")).toHaveTextContent("Not available");
  });
});

describe("data sources", () => {
  it("the API adapter reports pending integration instead of calling an invented endpoint", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const api = createPendingApiSource();
    await expect(api.listSnapshots()).rejects.toMatchObject({ status: 501, code: "pending_backend_integration" });
    await expect(api.submitScenario({} as never)).rejects.toMatchObject({ status: 501 });
    expect((await api.capabilities()).execution.mode).toBe("unavailable");
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("the explorer shows the pending state when the API source is active", async () => {
    render(<UniversitySourceProvider source={createPendingApiSource()}>
      <ProgramExplorer snapshot={cat.snapshot} state={defaultProgramState(2026)} onChange={() => {}} selected={null} onSelect={() => {}} />
    </UniversitySourceProvider>);
    expect((await screen.findAllByText(/pending backend integration/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Not available in this release/).length).toBeGreaterThan(0);
  });

  it("every fixture object is labelled as fixture data", async () => {
    const s = createFixtureSource({ persist: false });
    expect((await s.listSnapshots()).every((x) => x.origin === "fixture")).toBe(true);
    expect((await s.listCohorts()).every((x) => x.origin === "fixture")).toBe(true);
    const runs = await s.listRuns();
    expect(runs.every((r) => r.origin === "fixture")).toBe(true);
    expect((await s.getRun(runs[0].run_id)).findings.some((f) => f.code === "fixture_allocation")).toBe(true);
  });
});

describe("app shell integration", () => {
  it("keeps existing navigation and adds the University Simulation group with its own top bar", async () => {
    nav.pathname = "/university/results";
    render(<UniversitySourceProvider source={createFixtureSource({ persist: false })}><AppShell><h1>Body</h1></AppShell></UniversitySourceProvider>);
    const links = within(screen.getByRole("navigation", { name: "Workbench" })).getAllByRole("link").map((l) => l.textContent);
    expect(links).toEqual(["Dashboard", "Population", "Cohorts", "Personas", "New Experiment", "Experiments", "Results", "Historical Run3 Recorded proof of concept",
      "Programs", "Candidates", "Scenario Setup", "Placement Results", "Compare Scenarios", "Validation", "Data Sources", "Settings"]);
    expect(screen.getByRole("link", { name: /Placement Results/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("region", { name: "University data source" })).toBeInTheDocument();
    expect(await screen.findByText("Execution: fixture preview only")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Selected synthetic population" })).toBeNull();
  });

  it("shows the population bar, not the university bar, on population pages", () => {
    nav.pathname = "/population";
    render(<AppShell><h1>Body</h1></AppShell>);
    expect(screen.getByRole("region", { name: "Selected synthetic population" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "University data source" })).toBeNull();
  });
});

describe("URL state", () => {
  function Probe() {
    const { params, update } = useUrlParams();
    return (
      <>
        <output aria-label="query">{params.toString()}</output>
        <button type="button" onClick={() => update((p) => p.append("score", "EA"))}>EA</button>
        <button type="button" onClick={() => update((p) => p.append("score", "SAY"))}>SAY</button>
      </>
    );
  }

  it("shows a change immediately and keeps quick successive changes before the URL catches up", async () => {
    const user = userEvent.setup();
    nav.pathname = "/university/programs";
    nav.params = new URLSearchParams("snapshot=s1");
    nav.replace.mockClear();
    render(<Probe />);
    await user.click(screen.getByRole("button", { name: "EA" }));
    await user.click(screen.getByRole("button", { name: "SAY" }));
    expect(screen.getByLabelText("query")).toHaveTextContent("snapshot=s1&score=EA&score=SAY");
    expect(nav.replace).toHaveBeenLastCalledWith("/university/programs?snapshot=s1&score=EA&score=SAY", { scroll: false });
  });
});
