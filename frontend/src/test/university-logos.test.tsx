import { fireEvent, render } from "@testing-library/react";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { UniversityLogo } from "@/components/university/common";
import { logoFor, VERIFIED_LOGOS, type LogoAsset } from "@/lib/university/logos";

// A neutral grey test square, not any institution's mark.
const TEST_ASSET: LogoAsset = {
  src: "/university-logos/test-light.svg", width: 120, height: 60, institution: "Test institution",
  sourceUrl: "https://example.invalid/brand", terms: "test only",
};

describe("university logos", () => {
  it("lists only sourced logos with a same-origin asset, terms and proportions; unknown codes fall back", () => {
    for (const [code, a] of Object.entries(VERIFIED_LOGOS)) {
      expect(code).toMatch(/^\d{4}$/);
      expect(a.src).toMatch(new RegExp(`^/university-logos/${code}\\.(svg|png|jpg)$`));
      expect(existsSync(join(process.cwd(), "public", a.src))).toBe(true);
      expect(a.sourceUrl).toMatch(/^https:\/\/commons\.wikimedia\.org\/wiki\/File:/);
      expect(a.terms).toMatch(/public domain/i);
      expect(a.width).toBeGreaterThan(0);
      expect(a.height).toBeGreaterThan(0);
    }
    expect(logoFor("0000")).toBeNull();
    expect(logoFor(null)).toBeNull();
  });

  it("renders a neutral, decorative fallback when there is no verified logo", () => {
    const { container } = render(<UniversityLogo code="0000" name="Unlisted institution" />);
    const slot = container.querySelector("[data-logo]")!;
    expect(slot).toHaveAttribute("data-logo", "fallback");
    expect(slot).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector("img")).toBeNull();
  });

  it("renders a verified logo with its proportions, prefers the dark variant, and falls back if the image fails", () => {
    const registry = { "9999": TEST_ASSET, "9998": { ...TEST_ASSET, srcDark: "/university-logos/test-dark.svg" } };
    const { container, rerender } = render(<UniversityLogo code="9999" name="Test" registry={registry} />);
    const img = container.querySelector("img")!;
    expect(img).toHaveAttribute("width", "120");
    expect(img).toHaveAttribute("height", "60");
    expect(img).toHaveAttribute("alt", "");
    expect(container.querySelector("[data-logo]")).toHaveClass("uni-logo-plate");
    fireEvent.error(img);
    expect(container.querySelector("[data-logo]")).toHaveAttribute("data-logo", "fallback");
    rerender(<UniversityLogo code="9998" name="Test" registry={registry} />);
    expect(container.querySelector("img")).toHaveAttribute("src", "/university-logos/test-dark.svg");
    expect(container.querySelector("[data-logo]")).not.toHaveClass("uni-logo-plate");
  });

  it("is announced only when not decorative", () => {
    const { container } = render(<UniversityLogo code={null} name="Test University" decorative={false} />);
    expect(container.querySelector("[data-logo]")).toHaveAttribute("aria-label", "Test University logo");
  });
});
