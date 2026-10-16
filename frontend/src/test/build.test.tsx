import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = { params: new URLSearchParams("build=not-a-build") };
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/population",
}));

const descriptor = (id: string, variant: string, isDefault: boolean) => ({
  build_id: id, variant, schema_version: "s", schema_note: "n", source_path: "p.csv", source_sha256: "a".repeat(64), source_bytes: 1,
  row_count: 40, available_fields: ["person_id"], filterable_fields: [], unavailable_fields: [],
  scope: { province: "TESTLAND", reference_year: 2099, evidence: "e" }, generator: { method: "m", configured_seed: 7, seed_evidence: "s" },
  origin: "artificial", is_default: isDefault, evidence_gaps: [], synthetic_label: "l", registered_at: "t",
  availability: { status: "available", detail: "d" },
});

vi.mock("@/lib/api/client", async (original) => {
  const actual = await original<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      GET: vi.fn(async () => ({
        data: { items: [descriptor("testland-40-base-x", "base", false), descriptor("testland-40-v2-y", "v2", true)],
                default_build_id: "testland-40-v2-y", relations: [], load_errors: [] },
        response: new Response(null, { status: 200 }),
      })),
    },
  };
});

import { BuildBar } from "@/components/BuildBar";
import { BuildProvider, useBuild } from "@/lib/build";

function Probe() {
  const { build, usingDefault } = useBuild();
  return <span data-testid="probe">{build ? `${build.build_id}${usingDefault ? " default" : ""}` : "none"}</span>;
}

describe("build selection", () => {
  beforeEach(() => { nav.params = new URLSearchParams("build=not-a-build"); });

  it("reports an unknown build and never substitutes another one", async () => {
    render(<BuildProvider><BuildBar /><Probe /></BuildProvider>);
    await waitFor(() => expect(screen.getByText(/is not registered; nothing else was selected/)).toBeInTheDocument());
    expect(screen.getByTestId("probe")).toHaveTextContent("none");
  });

  it("uses the registered default only when no build is named, and says so", async () => {
    nav.params = new URLSearchParams("");
    render(<BuildProvider><BuildBar /><Probe /></BuildProvider>);
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("testland-40-v2-y default"));
    expect(screen.getByText(/TESTLAND · 2099/)).toBeInTheDocument();
  });
});
