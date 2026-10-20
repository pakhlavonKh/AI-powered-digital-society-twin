"use client";

import { fmtInt } from "@/lib/format";
import { usePopulation } from "@/lib/population";
import { Badge } from "./StatusBadge";

/** Population selector for the national pages. The choice lives in the URL; a missing ID is reported, never replaced. */
export function PopulationBar() {
  const { items, population, missingId, usingDefault, loading, error, select } = usePopulation();
  return (
    <div className="topbar" role="region" aria-label="Selected synthetic population">
      <div className="topbar-caption">TÜRKİYE <span>/</span> SYNTHETIC POPULATION</div>
      <div className="build-field">
        <label htmlFor="population-select">Population</label>
        <select id="population-select" value={population?.population_id ?? missingId ?? ""} onChange={(e) => select(e.target.value)}
                disabled={loading || items.length === 0}>
          {missingId ? <option value={missingId}>{missingId} (not found)</option> : null}
          {items.length === 0 ? <option value="">{loading ? "Loading populations…" : "No population generated"}</option> : null}
          {items.map((p) => (
            <option key={p.population_id} value={p.population_id}>
              {p.scope.scope_code === "TR" ? "Türkiye" : p.scope.label} · {fmtInt(p.synthetic_size)} records · seed {p.seed} · {p.reference_year}
            </option>
          ))}
        </select>
      </div>
      {population ? (
        <div className="row small" aria-live="polite">
          <Badge tone="info" glyph="⌖">{population.scope.province_count} of {population.scope.province_reference_count} provinces with source data</Badge>
          <Badge tone="neutral" glyph="◷">Reference year {population.reference_year}</Badge>
          {usingDefault ? <span className="muted">newest population</span> : null}
        </div>
      ) : null}
      {missingId ? <Badge tone="crit" glyph="!">Population {missingId} does not exist; nothing else was selected</Badge> : null}
      {error ? <Badge tone="crit" glyph="!">Populations unavailable: {error.message}</Badge> : null}
    </div>
  );
}
