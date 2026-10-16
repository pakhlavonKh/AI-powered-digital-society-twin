const integer = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "unknown" : integer.format(n);
}

export function fmtPct(share: number | null | undefined, digits = 1): string {
  return share === null || share === undefined ? "–" : `${(share * 100).toFixed(digits)}%`;
}

export function fmtPp(pp: number | null | undefined, digits = 2): string {
  if (pp === null || pp === undefined) return "–";
  const sign = pp > 0 ? "+" : pp < 0 ? "−" : "±";
  return `${sign}${Math.abs(pp).toFixed(digits)} pp`;
}

export function fmtDecimal(n: number | null | undefined, digits = 4): string {
  return n === null || n === undefined ? "unknown" : n.toFixed(digits);
}

/** USD with enough precision for sub-cent estimates; null stays "unknown", never zero. */
export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "unknown";
  if (n === 0) return "$0";
  return n < 0.01 ? `$${n.toPrecision(3)}` : `$${n.toFixed(4)}`;
}

export function shortHash(hash: string | null | undefined, length = 12): string {
  return hash ? `${hash.slice(0, length)}…` : "unknown";
}

export function fmtValue(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export const FIELD_LABELS: Record<string, string> = {
  person_id: "Resident ID",
  age_group: "Age group",
  gender: "Sex (administrative)",
  marital_status: "Marital status",
  marital_status_conditioning: "Marital conditioning",
};
