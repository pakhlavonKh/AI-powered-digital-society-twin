import type { Geography } from "./api/v2";

function names(list: string[]): string {
  return list.length <= 1 ? list.join("") : `${list.slice(0, -1).join(", ")} and ${list.at(-1)}`;
}

/** Source coverage in words, from the geography endpoint; it changes by itself as provinces gain source data. */
export function coverageNote(geo: Pick<Geography, "provinces" | "province_count">): string {
  const loaded = geo.provinces.filter((p) => p.has_population_controls).map((p) => p.province_name);
  const total = geo.province_count;
  if (loaded.length >= total) return `Official source data is loaded for all ${total} provinces.`;
  if (loaded.length === 0) return `The national architecture supports all ${total} provinces. No official source data is loaded yet.`;
  const which = loaded.length <= 3 ? `${names(loaded)} only` : `${loaded.length} of ${total} provinces`;
  return `The national architecture supports all ${total} provinces. Current official source data is loaded for ${which}.`;
}
