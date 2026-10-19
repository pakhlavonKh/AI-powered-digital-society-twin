import type { Geography } from "./api/v2";

function names(list: string[]): string {
  return list.length <= 1 ? list.join("") : `${list.slice(0, -1).join(", ")} and ${list.at(-1)}`;
}

/** Person attribute each standard control table supplies (the root table supplies age group × sex). */
const TABLE_ATTRIBUTE: Record<string, string> = {
  population_age_sex: "age group × sex", marital_status_age_sex: "marital status", marital_status_sex: "marital status",
  education_age_sex: "education", education_sex: "education", labour_status_age_sex: "labour status", labour_status_sex: "labour status",
  household_size_persons: "household size", household_type_persons: "household type", urbanicity_sex: "settlement type", urbanicity: "settlement type",
};
const PERSON_ATTRIBUTES = ["marital status", "education", "labour status", "household size", "household type", "settlement type"];

function uniq(list: string[]): string[] {
  return [...new Set(list)];
}

/** Source coverage in words, from the geography endpoint; it changes by itself as provinces gain source data. */
export function coverageNote(geo: Pick<Geography, "provinces" | "province_count">): string {
  const loadedProvinces = geo.provinces.filter((p) => p.has_population_controls);
  const loaded = loadedProvinces.map((p) => p.province_name);
  const total = geo.province_count;
  if (loaded.length === 0) return `The national architecture supports all ${total} provinces. No official source data is loaded yet.`;
  if (loaded.length >= total) {
    const everywhere = uniq(Object.keys(TABLE_ATTRIBUTE).filter((t) => loadedProvinces.every((p) => p.control_tables.includes(t))).map((t) => TABLE_ATTRIBUTE[t]));
    if (everywhere.length === 0) return `Official source data is loaded for all ${total} provinces.`;
    const anywhere = new Set(loadedProvinces.flatMap((p) => p.control_tables.map((t) => TABLE_ATTRIBUTE[t])));
    const missing = PERSON_ATTRIBUTES.filter((a) => !anywhere.has(a));
    return `Official source data is loaded for all ${total} provinces: ${names(everywhere)}.`
      + (missing.length ? ` No province-level table supports ${names(missing)}, so ${missing.length === 1 ? "it stays" : "they stay"} unavailable.` : "");
  }
  const which = loaded.length <= 3 ? `${names(loaded)} only` : `${loaded.length} of ${total} provinces`;
  return `The national architecture supports all ${total} provinces. Current official source data is loaded for ${which}.`;
}

/** True once every province has the root population table. */
export function fullCoverage(geo: Pick<Geography, "provinces" | "province_count">): boolean {
  return geo.provinces.filter((p) => p.has_population_controls).length >= geo.province_count;
}
