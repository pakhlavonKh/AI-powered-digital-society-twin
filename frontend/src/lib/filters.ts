import type { Schemas } from "./api/client";

type Spec = Schemas["FilterSpec"];
export type AgeGroup = NonNullable<Spec["age_groups"]>[number];
export type Gender = NonNullable<Spec["genders"]>[number];
export type MaritalStatus = NonNullable<Spec["marital_statuses"]>[number];

/**
 * Filter state typed by the generated API schema. Values read from the URL are not trusted: they are
 * passed through as typed so that an invalid value reaches the API and comes back as a visible 422,
 * rather than being dropped silently.
 */
export type Filters = {
  person_ids?: string[];
  age_groups?: AgeGroup[];
  genders?: Gender[];
  marital_statuses?: MaritalStatus[];
};

const PARAMS: [keyof Filters, string][] = [
  ["person_ids", "id"],
  ["age_groups", "age_group"],
  ["genders", "gender"],
  ["marital_statuses", "marital_status"],
];

export function filtersFromParams(params: URLSearchParams): Filters {
  const out: Filters = {};
  for (const [key, param] of PARAMS) {
    const values = params.getAll(param).filter(Boolean);
    if (values.length) (out as Record<string, string[]>)[key] = values;
  }
  return out;
}

export function filtersToParams(filters: Filters, base: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(base.toString());
  for (const [key, param] of PARAMS) {
    next.delete(param);
    for (const v of (filters[key] ?? []) as string[]) next.append(param, v);
  }
  return next;
}

/** Query object for GET endpoints (repeated parameters). Omitted fields mean "no restriction". */
export function filtersToQuery(filters: Filters) {
  return {
    person_id: filters.person_ids,
    age_group: filters.age_groups,
    gender: filters.genders,
    marital_status: filters.marital_statuses,
  } as const;
}

/** Body for POST endpoints; empty selections are dropped rather than sent (the API rejects empty arrays). */
export function filtersToBody(filters: Filters): Filters {
  const out: Filters = {};
  for (const [key] of PARAMS) {
    const values = filters[key];
    if (values && values.length) (out as Record<string, string[]>)[key] = values as string[];
  }
  return out;
}

export function filterCount(filters: Filters): number {
  return PARAMS.reduce((n, [key]) => n + (filters[key]?.length ? 1 : 0), 0);
}
