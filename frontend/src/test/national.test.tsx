import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Distribution, ProvinceCoverage } from "@/lib/api/v2";
import { describeFilters, filtersFromParams, filtersToParams } from "@/lib/nationalFilters";
import { withPop } from "@/lib/population";
import { TURKEY_PROVINCES } from "@/lib/turkey-provinces";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/",
}));

const { ProvinceMap } = await import("@/components/ProvinceMap");
const { DistributionChart, ShareBars } = await import("@/components/national/charts");

function coverage(code: string, records: number, controls: boolean): ProvinceCoverage {
  return { province_code: code, province_name: `P${code}`, nuts3_code: "TR000", nuts2_code: "TR00", nuts1_code: "TR0", nuts1_name: "x",
    iso_3166_2: `TR-${code}`, has_population_controls: controls, control_tables: [], context_indicators: 0, records, represented_population: records ? records * 10 : null };
}

describe("province map", () => {
  it("renders all 81 provinces as keyboard links with availability, never as a value scale", () => {
    const provinces = TURKEY_PROVINCES.map((p) => coverage(p.iso.slice(3), p.iso === "TR-06" ? 100 : 0, p.iso === "TR-06" || p.iso === "TR-34"));
    render(<ProvinceMap provinces={provinces} selected="06" hrefFor={(c) => `/population?province=${c}`} />);
    const links = screen.getAllByRole("link").filter((a) => a.getAttribute("href")?.startsWith("/population"));
    expect(links).toHaveLength(81);
    expect(screen.getByText(/1 with records · 1 with source data only · 79 without source data/)).toBeInTheDocument();
    const ankara = links.find((a) => a.getAttribute("href") === "/population?province=06")!;
    expect(ankara.getAttribute("aria-label")).toMatch(/Synthetic records in the selected population, 100 records/);
    const izmir = links.find((a) => a.getAttribute("href") === "/population?province=35")!;
    expect(izmir.getAttribute("aria-label")).toMatch(/No source data loaded/);
  });
});

describe("national filters", () => {
  it("round-trip through the URL and keep other parameters", () => {
    const params = filtersToParams({ province_codes: ["06"], adult_only: true, sexes: ["female"], age_min: 18, age_max: 34 }, new URLSearchParams("pop=p1"));
    expect(params.get("pop")).toBe("p1");
    expect(filtersFromParams(params)).toEqual({ province_codes: ["06"], adult_only: true, sexes: ["female"], age_min: 18, age_max: 34 });
    expect(describeFilters({ province_codes: ["06"], adult_only: true }, () => "Ankara")).toBe("Ankara · adults (18+)");
    expect(describeFilters({}, () => "")).toBe("All records");
  });

  it("carries only an explicit population choice in links", () => {
    expect(withPop("/cohorts", "pop-x", { prefill: "{}" })).toBe("/cohorts?pop=pop-x&prefill=%7B%7D");
    expect(withPop("/cohorts", null)).toBe("/cohorts");
  });
});

describe("distribution chart", () => {
  it("explains unavailable fields instead of drawing zeros", () => {
    const dist: Distribution = { field: "education_level", records: 10, weighted_total: 100, available: false,
      note: "No source table is loaded for this field in the selected provinces.",
      categories: [{ value: "unavailable", label: "Not available", records: 10, weighted: 100, weighted_share: 1, record_share: 1 }] };
    render(<DistributionChart dist={dist} title="Education" label={(c) => c} />);
    expect(screen.getByText("No source table is loaded for this field in the selected provinces.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show table" })).toBeNull();
  });
});

describe("share bars", () => {
  it("print the share, interval and count as text", () => {
    render(<ShareBars caption="x" labels={{ a: "Option A" }} options={[{ option_id: "a", responses: 4, weighted_share: 0.25, unweighted_share: 0.2, ci95: [0.1, 0.5] }]} />);
    expect(screen.getByText("Option A")).toBeInTheDocument();
    expect(screen.getByText(/25.0% \(10%–50%\) · n=4/)).toBeInTheDocument();
  });
});
