import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceTerm } from "@/components/university/common";
import { buildRegistryFixture } from "@/lib/university/fixtures/registry";
import { englishLabel, englishLabelOrNull, isTranslated } from "@/lib/university/labels";
import { programFacets } from "@/lib/university/programs";

describe("English display labels for Turkish source vocabulary", () => {
  it("translates scholarship, institution-type and language labels, whatever the case or accents", () => {
    expect(englishLabel("Burslu")).toBe("Full scholarship");
    expect(englishLabel("%50 İndirimli")).toBe("50% discount");
    expect(englishLabel("%25 indirimli")).toBe("25% discount");
    expect(englishLabel("Ücretli")).toBe("Fee-paying");
    expect(englishLabel("Devlet (Ücretsiz)")).toBe("State (tuition-free)");
    expect(englishLabel("Vakıf")).toBe("Foundation");
    expect(englishLabel("DEVLET")).toBe("State");
    expect(englishLabel("İngilizce")).toBe("English");
  });

  it("never guesses: unknown labels, names and score-type codes are shown exactly as the source wrote them", () => {
    for (const s of ["KKTC Uyruklu", "Bilgisayar Mühendisliği", "SÖZ", "DİL", "Synthetic Foundation University C"]) {
      expect(englishLabel(s)).toBe(s);
      expect(isTranslated(s)).toBe(false);
    }
    expect(englishLabelOrNull(null)).toBeNull();
    expect(englishLabelOrNull("")).toBeNull();
  });

  it("keeps filter values as the exact source labels (URL state and queries are unchanged)", () => {
    const cat = buildRegistryFixture();
    const facets = programFacets(cat);
    const values = facets.scholarships.map((f) => f.value);
    expect(values).toContain("Burslu");
    expect(values).not.toContain("Full scholarship");
  });

  it("shows English with the source label as a tooltip, or inline in detail views", () => {
    const { rerender } = render(<SourceTerm value="Burslu" />);
    expect(screen.getByText("Full scholarship")).toHaveAttribute("title", "Source label: Burslu");
    rerender(<SourceTerm value="%50 İndirimli" showSource />);
    expect(screen.getByText(/50% discount/)).toBeInTheDocument();
    expect(screen.getByText("(source label: %50 İndirimli)")).toBeInTheDocument();
    rerender(<SourceTerm value={null} />);
    expect(screen.getByText("Missing from source")).toBeInTheDocument();
  });
});
