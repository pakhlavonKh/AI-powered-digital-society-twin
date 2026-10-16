"use client";

import { useState } from "react";
import type { Filters } from "@/lib/filters";

type Props = {
  filters: Filters;
  onChange: (next: Filters) => void;
  categories: { age_group: string[]; gender: string[]; marital_status: string[] };
  availableFields: string[];
  translations?: Record<string, string>;
  showTranslations?: boolean;
  idSearch?: boolean;
  disabled?: boolean;
};

function toggle<T extends string>(list: T[] | undefined, value: string): T[] | undefined {
  const set = new Set<string>(list ?? []);
  if (set.has(value)) set.delete(value);
  else set.add(value);
  return set.size ? ([...set] as T[]) : undefined;
}

/** AND across fields, OR within a field. Only fields that exist in the selected build can be used. */
export function FilterControls({ filters, onChange, categories, availableFields, translations = {}, showTranslations, idSearch, disabled }: Props) {
  const [idText, setIdText] = useState(filters.person_ids?.join(" ") ?? "");
  const maritalAvailable = availableFields.includes("marital_status");
  const label = (value: string) => (showTranslations && translations[value] ? `${value} (${translations[value]})` : value);

  return (
    <div className="filter-bar">
      {idSearch ? (
        <form className="field" onSubmit={(e) => {
          e.preventDefault();
          const ids = idText.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
          onChange({ ...filters, person_ids: ids.length ? ids : undefined });
        }}>
          <label htmlFor="id-search">Resident ID (exact)</label>
          <div className="row">
            <input id="id-search" type="search" value={idText} onChange={(e) => setIdText(e.target.value)} placeholder="ANK2025_000001" disabled={disabled}
              aria-describedby="id-search-hint" style={{ flex: "1 1 160px" }} />
            <button type="submit" className="button small" disabled={disabled}>Search</button>
          </div>
          <span className="field-hint" id="id-search-hint">Exact IDs only, separated by spaces. No pattern matching.</span>
        </form>
      ) : null}
      <fieldset disabled={disabled}>
        <legend>Sex (administrative)</legend>
        <div className="checks">
          {categories.gender.map((g) => (
            <label className="check" key={g}>
              <input type="checkbox" checked={(filters.genders as string[] | undefined)?.includes(g) ?? false} onChange={() => onChange({ ...filters, genders: toggle(filters.genders, g) })} />
              {g}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset disabled={disabled || !maritalAvailable} aria-describedby={!maritalAvailable ? "marital-unavailable" : undefined}>
        <legend>Marital status</legend>
        {maritalAvailable ? (
          <div className="checks">
            {categories.marital_status.map((m) => (
              <label className="check" key={m}>
                <input type="checkbox" checked={(filters.marital_statuses as string[] | undefined)?.includes(m) ?? false}
                  onChange={() => onChange({ ...filters, marital_statuses: toggle(filters.marital_statuses, m) })} />
                {label(m)}
              </label>
            ))}
          </div>
        ) : (
          <p className="small muted" id="marital-unavailable">This build has no marital_status column, so this filter is unavailable.</p>
        )}
      </fieldset>
      <details style={{ flexBasis: "100%" }}>
        <summary>Age groups{filters.age_groups?.length ? ` (${filters.age_groups.length} selected)` : " (all)"}</summary>
        <div className="details-body">
          <fieldset disabled={disabled} style={{ border: 0, padding: 0 }}>
            <legend className="visually-hidden">Age groups</legend>
            <div className="checks">
              {categories.age_group.map((a) => (
                <label className="check" key={a}>
                  <input type="checkbox" checked={(filters.age_groups as string[] | undefined)?.includes(a) ?? false} onChange={() => onChange({ ...filters, age_groups: toggle(filters.age_groups, a) })} />
                  {a}
                </label>
              ))}
            </div>
            <p className="field-hint">Five-year bands as published. Exact ages do not exist in these rows.</p>
          </fieldset>
        </div>
      </details>
    </div>
  );
}
