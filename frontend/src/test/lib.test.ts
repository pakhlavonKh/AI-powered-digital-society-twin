import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { filtersFromParams, filtersToBody, filtersToParams } from "@/lib/filters";
import { fmtInt, fmtPp, fmtUsd } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

describe("filters", () => {
  it("round-trip through the URL and drop empty selections from request bodies", () => {
    const params = filtersToParams({ genders: ["female"], marital_statuses: ["Eşi öldü", "Evli"] }, new URLSearchParams("build=b1&page=2"));
    expect(params.getAll("marital_status")).toEqual(["Eşi öldü", "Evli"]);
    expect(params.get("build")).toBe("b1");
    expect(filtersFromParams(params)).toEqual({ genders: ["female"], marital_statuses: ["Eşi öldü", "Evli"] });
    expect(filtersToBody({ genders: [], age_groups: ["0-4"] })).toEqual({ age_groups: ["0-4"] });
  });
});

describe("formatting", () => {
  it("never turns unknown into zero", () => {
    expect(fmtUsd(null)).toBe("unknown");
    expect(fmtUsd(0.00205475)).toBe("$0.00205");
    expect(fmtInt(undefined)).toBe("unknown");
    expect(fmtPp(-0.83)).toBe("−0.83 pp");
  });

  it("keeps an explicit build choice in links", () => {
    expect(withBuild("/personas", "b1", { record: "X" })).toBe("/personas?build=b1&record=X");
    expect(withBuild("/personas", null)).toBe("/personas");
  });
});

describe("useApi", () => {
  it("keeps the previous render while refetching, and never shows another key's data after an error", async () => {
    let fail = false;
    const { result, rerender } = renderHook(({ key }) => useApi(key, async () => {
      if (fail) throw new ApiError(500, "boom", "failed");
      return key;
    }), { initialProps: { key: "a" } });
    await waitFor(() => expect(result.current.data).toBe("a"));
    fail = true;
    rerender({ key: "b" });
    expect(result.current.data).toBe("a");
    expect(result.current.stale).toBe(true);
    await waitFor(() => expect(result.current.error?.code).toBe("boom"));
    expect(result.current.data).toBeUndefined();
    fail = false;
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe("b"));
  });
});
