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

/** True when the displayed English differs from the source wording, so the UI should point to the source label. */
export function isTranslated(source: string | null | undefined): source is string {
  return typeof source === "string" && source !== "" && englishLabel(source) !== source;
}
