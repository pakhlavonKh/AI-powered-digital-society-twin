import type { MissingReason } from "./types";

export const MISSING_LABELS: Record<MissingReason, string> = {
  not_available: "Not available",
  missing_from_source: "Missing from source",
  not_applicable: "Not applicable",
  not_calculated: "Not calculated",
  pending_backend: "Pending backend integration",
  not_in_schema: "Not in schema",
};

export const MISSING_DESCRIPTIONS: Record<MissingReason, string> = {
  not_available: "No value is available for this field.",
  missing_from_source: "The source left this field empty. It is not zero and was not inferred.",
  not_applicable: "This field does not apply to this record.",
  not_calculated: "This value has not been calculated.",
  pending_backend: "No backend endpoint provides this yet. The UI is ready for it.",
  not_in_schema: "The current data contract has no field for this.",
};

/** Case- and diacritic-insensitive Turkish folding for search ("muhendislik" matches "Mühendislik", "İ"/"ı" → "i"). */
export function foldTr(text: string): string {
  return text
    .toLocaleLowerCase("tr")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ı/g, "i")
    .trim();
}

const collator = new Intl.Collator("tr", { sensitivity: "base", numeric: true });

export function compareText(a: string, b: string): number {
  return collator.compare(a, b);
}

/**
 * Score-type labels the candidate contract defines (`candidate-development-v1`: SAY, EA, SOZ, DIL). Registry labels
 * are kept exactly as the source wrote them (for example "SÖZ"); they are only folded for matching. Labels that do
 * not fold to one of these are reported as unknown rather than guessed.
 */
export const CONTRACT_SCORE_TYPES = ["SAY", "EA", "SOZ", "DIL"] as const;

export function scoreTypeKey(label: string | null | undefined): string | null {
  if (!label) return null;
  return label
    .toLocaleUpperCase("tr")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/İ/g, "I")
    .trim();
}

export function isContractScoreType(label: string | null | undefined): boolean {
  const key = scoreTypeKey(label);
  return key !== null && (CONTRACT_SCORE_TYPES as readonly string[]).includes(key);
}

/** FNV-1a 32-bit hash as 8 hex characters: stable IDs for fixture runs and configuration fingerprints. */
export function fnv1a(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

/** JSON with object keys sorted at every level, so equal configurations serialize identically. */
export function canonicalJson(value: unknown): string {
  const norm = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(norm);
    if (v && typeof v === "object") {
      return Object.fromEntries(Object.keys(v as Record<string, unknown>).sort().map((k) => [k, norm((v as Record<string, unknown>)[k])]));
    }
    return v;
  };
  return JSON.stringify(norm(value));
}

/**
 * Seeded PRNG (mulberry32) for frontend fixtures. It is NOT the national engine's SHA-256 counter stream, so fixture
 * cohorts are reproducible within the UI but are not byte-identical to `python -m societytwin.candidates`.
 */
export function rng(seed: number, namespace: string): () => number {
  let a = (parseInt(fnv1a(`${namespace}:${seed}`), 16) ^ (seed >>> 0)) >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Integer in [0, n). */
export function below(next: () => number, n: number): number {
  return Math.floor(next() * n);
}

export function fmtMoneyMinor(minor: number | null, currency: string): string | null {
  if (minor === null) return null;
  return `${(minor / 100).toLocaleString("en-GB", { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ${currency}`;
}

/** Signed relative change in percent, distinct from percentage points. */
export function fmtSignedPct(pct: number | null | undefined, digits = 1): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "–";
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "±";
  return `${sign}${Math.abs(pct).toFixed(digits)}%`;
}

export function fmtSignedInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  const sign = n > 0 ? "+" : n < 0 ? "−" : "±";
  return `${sign}${Math.abs(n).toLocaleString("en-GB")}`;
}

export function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] ?? s[v] ?? s[0]}`;
}
