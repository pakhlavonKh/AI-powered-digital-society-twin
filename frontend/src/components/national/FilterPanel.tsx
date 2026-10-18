"use client";

import type { Capabilities, Filters, ProvinceCoverage } from "@/lib/api/v2";
import { FILTER_FIELDS } from "@/lib/nationalFilters";

/**
 * Filters for the national population. Only provinces with source data can be chosen; the others are listed
 * as unavailable instead of being hidden. Category lists come from the API's vocabularies.
 */
export function FilterPanel({ filters, onChange, provinces, caps, title = "Filters", available }: {
  filters: Filters; onChange: (f: Filters) => void; provinces: ProvinceCoverage[]; caps: Capabilities | undefined; title?: string;
  /** fields that have any source value in the population (others are shown disabled) */
  available?: Set<string>;
}) {
  const set = (patch: Partial<Filters>) => {
    const next = { ...filters, ...patch };
    for (const [k, v] of Object.entries(next)) if (v === undefined || (Array.isArray(v) && v.length === 0) || v === false) delete (next as Record<string, unknown>)[k];
    onChange(next);
  };
  const toggle = (key: keyof Filters, value: string) => {
    const current = new Set((filters[key] as string[] | undefined) ?? []);
    if (current.has(value)) current.delete(value); else current.add(value);
    set({ [key]: [...current] } as Partial<Filters>);
  };
  const covered = provinces.filter((p) => p.has_population_controls);
  const selectedProvince = filters.province_codes?.length === 1 ? filters.province_codes[0] : "";
  return (
    <section className="card filters2" aria-label={title}>
      <div className="row" style={{ justifyContent: "space-between" }}><h2 style={{ margin: 0 }}>{title}</h2>
        <button type="button" className="button small" onClick={() => onChange({})}>Reset</button></div>
      <div className="field">
        <label htmlFor="flt-province">Province</label>
        <select id="flt-province" value={selectedProvince} onChange={(e) => set({ province_codes: e.target.value ? [e.target.value] : undefined })}>
          <option value="">All Türkiye ({covered.length} with source data)</option>
          <optgroup label="Provinces with source data">
            {covered.map((p) => <option key={p.province_code} value={p.province_code}>{p.province_name} ({p.province_code})</option>)}
          </optgroup>
          <optgroup label="No source data loaded">
            {provinces.filter((p) => !p.has_population_controls).map((p) => (
              <option key={p.province_code} value={p.province_code} disabled>{p.province_name} ({p.province_code}) · no data</option>))}
          </optgroup>
        </select>
      </div>
      <label className="check"><input type="checkbox" checked={!!filters.adult_only} onChange={(e) => set({ adult_only: e.target.checked || undefined })} />
        Adults only (18+)</label>
      <div className="age-row">
        <div className="field"><label htmlFor="flt-amin">Age from</label>
          <input id="flt-amin" type="number" min={0} max={120} value={filters.age_min ?? ""} onChange={(e) => set({ age_min: e.target.value === "" ? undefined : Number(e.target.value) })} /></div>
        <div className="field"><label htmlFor="flt-amax">Age to</label>
          <input id="flt-amax" type="number" min={0} max={120} value={filters.age_max ?? ""} onChange={(e) => set({ age_max: e.target.value === "" ? undefined : Number(e.target.value) })} /></div>
      </div>
      <p className="field-hint" style={{ margin: 0 }}>Single-year age is assumed uniform within the observed five-year band (90+ is top-coded at 90).</p>
      {FILTER_FIELDS.map(({ key, field, label }) => {
        const vocab = caps?.vocabularies[field];
        if (!vocab) return null;
        const off = available !== undefined && !available.has(field);
        return (
          <fieldset key={key} disabled={off}>
            <legend>{label}{off ? " · no source data" : ""}</legend>
            <div className="checks">
              {vocab.categories.map((c) => (
                <label className="check" key={c.code} title={c.label_tr ?? undefined}>
                  <input type="checkbox" checked={((filters[key] as string[] | undefined) ?? []).includes(c.code)} onChange={() => toggle(key, c.code)} />
                  {c.label_en}
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}
    </section>
  );
}
