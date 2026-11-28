import { afterEach, describe, expect, it, vi } from "vitest";
import { englishLabel, scholarshipKind } from "@/lib/university/labels";
import { localPreviewRequested } from "@/lib/university/localPreviewSource";

afterEach(() => { vi.unstubAllEnvs(); });

describe("local registry preview", () => {
  it("is opt-in and development-only", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(localPreviewRequested(new URLSearchParams("source=local-preview"))).toBe(true);
    expect(localPreviewRequested(new URLSearchParams(""))).toBe(false);
    vi.stubEnv("NODE_ENV", "production");
    expect(localPreviewRequested(new URLSearchParams("source=local-preview"))).toBe(false);
  });

  it("serves nothing outside a development build", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const { GET } = await import("@/app/api/local-preview/university/route");
    const res = await GET(new Request("http://localhost/api/local-preview/university?scope=logos"));
    expect(res.status).toBe(404);
  });

  it("labels the national state tier in English and does not count it as a scholarship", () => {
    expect(englishLabel("Devlet (Katkı Payı Rejimi)")).toBe("State (contribution-fee regime)");
    expect(scholarshipKind("Devlet (Katkı Payı Rejimi)")).toBe("state");
  });
});
