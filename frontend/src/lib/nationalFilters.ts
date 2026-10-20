import type { Filters } from "./api/v2";

/** National population filters <-> URL search params. Values are passed through so the API, not the UI, rejects bad ones. */
const LISTS: [keyof Filters, string][] = [
  ["province_codes", "province"], ["age_groups", "age_group"], ["sexes", "sex"], ["marital_statuses", "marital"],
  ["education_levels", "education"], ["labour_statuses", "labour"], ["household_size_classes", "household_size"],
  ["household_types", "household_type"], ["urbanicities", "urbanicity"],
];

export const FILTER_FIELDS: { key: keyof Filters; field: string; label: string }[] = [
  { key: "sexes", field: "sex", label: "Sex" },
  { key: "marital_statuses", field: "marital_status", label: "Marital status" },
  { key: "education_levels", field: "education_level", label: "Education" },
  { key: "labour_statuses", field: "labour_status", label: "Labour status" },
  { key: "household_size_classes", field: "household_size_class", label: "Household size" },
  { key: "household_types", field: "household_type", label: "Household type" },
  { key: "urbanicities", field: "urbanicity", label: "Settlement type" },
];

export function filtersFromParams(params: URLSearchParams): Filters {
  const out: Filters = {};
  for (const [key, param] of LISTS) {
    const values = params.getAll(param).filter(Boolean);
    if (values.length) (out as Record<string, unknown>)[key] = values;
  }
  const min = params.get("age_min");
  const max = params.get("age_max");
  if (min !== null && min !== "") out.age_min = Number(min);
  if (max !== null && max !== "") out.age_max = Number(max);
  if (params.get("adult") === "1") out.adult_only = true;
  return out;
}

export function filtersToParams(filters: Filters, base?: URLSearchParams): URLSearchParams {
  const params = new URLSearchParams(base?.toString() ?? "");
  for (const [, param] of LISTS) params.delete(param);
  for (const p of ["age_min", "age_max", "adult"]) params.delete(p);
  for (const [key, param] of LISTS) for (const v of (filters[key] as string[] | undefined) ?? []) params.append(param, v);
  if (filters.age_min !== undefined) params.set("age_min", String(filters.age_min));
  if (filters.age_max !== undefined) params.set("age_max", String(filters.age_max));
  if (filters.adult_only) params.set("adult", "1");
  return params;
}

/** Query object for GET /api/v2/... endpoints (same names as the API). */
export function filtersToQuery(filters: Filters): Record<string, string | number | boolean | string[] | undefined> {
  return { ...filters } as Record<string, string | number | boolean | string[] | undefined>;
}

export function describeFilters(filters: Filters, provinceName: (code: string) => string): string {
  const parts: string[] = [];
  if (filters.province_codes?.length) parts.push(filters.province_codes.map(provinceName).join(", "));
  if (filters.adult_only) parts.push("adults (18+)");
  if (filters.age_min !== undefined || filters.age_max !== undefined) parts.push(`age ${filters.age_min ?? 0}–${filters.age_max ?? "max"}`);
  for (const f of FILTER_FIELDS) {
    const v = filters[f.key] as string[] | undefined;
    if (v?.length) parts.push(`${f.label.toLowerCase()}: ${v.join(", ")}`);
  }
  return parts.length ? parts.join(" · ") : "All records";
}

export function isEmpty(filters: Filters): boolean {
  return Object.keys(filters).length === 0;
}
