import { foldTr } from "./util";

/**
 * Display-only English for the Turkish vocabulary the registry source uses for scholarship labels, institution types
 * and teaching languages.
 *
 * Only what is shown changes: stored records, filter values, URL state, API identifiers and exports keep the exact
 * source text, and every translated label keeps the source wording available (tooltip or "source label" note).
 * Labels not listed here are shown exactly as the source wrote them; nothing is guessed. Official university and
 * program names and score-type codes (SAY, EA, SÖZ, DİL) are proper names or codes and are never translated.
 */
const TERMS: Record<string, string> = {
  // Scholarship / fee status (ÖSYM guide wording)
  "burslu": "Full scholarship",
  "tam burslu": "Full scholarship",
  "ucretli": "Fee-paying",
  "ucretsiz": "Tuition-free",
  "devlet (ucretsiz)": "State (tuition-free)",
  "devlet (katki payi rejimi)": "State (contribution-fee regime)",
  "ikinci ogretim": "Evening program",
  "uzaktan ogretim": "Distance learning",
  "acikogretim": "Open education",
  // Institution type
  "devlet": "State",
  "vakif": "Foundation",
  "ozel": "Private",
  "kktc": "TRNC",
  "yurt disi": "Abroad",
  // Teaching language
  "turkce": "Turkish",
  "ingilizce": "English",
  "almanca": "German",
  "fransizca": "French",
  "arapca": "Arabic",
  "rusca": "Russian",
  "ispanyolca": "Spanish",
  "italyanca": "Italian",
  "japonca": "Japanese",
  "cince": "Chinese",
  "korece": "Korean",
  "farsca": "Persian",
};

/** "%50 İndirimli" → "50% discount": the percentage tuition discount ÖSYM lists for foundation universities. */
const DISCOUNT = /^%\s*(\d{1,3})\s*indirimli$/;

/** English display text for a source label; the source text itself when no translation is known. */
export function englishLabel(source: string): string {
  const key = foldTr(source).replace(/\s+/g, " ");
  const discount = key.match(DISCOUNT);
  if (discount) return `${discount[1]}% discount`;
  return TERMS[key] ?? source;
}

/** English display text, or null when the source value is missing (callers render their explicit missing state). */
export function englishLabelOrNull(source: string | null | undefined): string | null {
  return source === null || source === undefined || source === "" ? null : englishLabel(source);
}

export type ScholarshipKind = "full" | "discount" | "fee" | "state" | "other";

/**
 * What a scholarship label means for the "scholarship programs" count: a full scholarship (Burslu) or a percentage
 * tuition discount (%NN İndirimli). Fee-paying and state (tuition-free) places are not scholarships; any other label
 * is "other" and is not counted, rather than guessed.
 */
export function scholarshipKind(source: string | null | undefined): ScholarshipKind | null {
  if (source === null || source === undefined || source === "") return null;
  const key = foldTr(source).replace(/\s+/g, " ");
  if (key === "burslu" || key === "tam burslu") return "full";
  if (DISCOUNT.test(key)) return "discount";
  if (key === "ucretli") return "fee";
  if (key === "devlet (ucretsiz)" || key === "ucretsiz" || key === "devlet" || key === "devlet (katki payi rejimi)") return "state";
  return "other";
}

/** Official ÖSYM spelling of a score-type code. The candidate contract writes SOZ / DIL; the guide writes SÖZ / DİL. */
const OFFICIAL_SCORE_TYPES: Record<string, string> = { SAY: "SAY", EA: "EA", SOZ: "SÖZ", DIL: "DİL", TYT: "TYT" };

/** Score-type code as displayed (official spelling); unknown labels are shown exactly as written. */
export function scoreTypeDisplay(label: string): string {
  const key = label.toLocaleUpperCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/İ/g, "I").trim();
  return OFFICIAL_SCORE_TYPES[key] ?? label;
}

/** True when the displayed English differs from the source wording, so the UI should point to the source label. */
export function isTranslated(source: string | null | undefined): source is string {
  return typeof source === "string" && source !== "" && englishLabel(source) !== source;
}
