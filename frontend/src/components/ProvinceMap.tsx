"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { ProvinceCoverage } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { TURKEY_PROVINCES } from "@/lib/turkey-provinces";

type Status = "records" | "controls" | "none";

function statusOf(p: ProvinceCoverage | undefined): Status {
  if (!p) return "none";
  if (p.records > 0) return "records";
  return p.has_population_controls ? "controls" : "none";
}

const LABEL: Record<Status, string> = {
  records: "Synthetic records in the selected population",
  controls: "Source data loaded, no records in the selected population",
  none: "No source data loaded",
};

/**
 * All 81 provinces from the geoBoundaries outline (keyed by ISO 3166-2, which uses the plate codes).
 * Fill encodes data availability only; it is not a choropleth of any statistic. Every province is a
 * keyboard-reachable link into the Population Explorer.
 */
export function ProvinceMap({ provinces, selected, hrefFor, title = "Türkiye province coverage" }: {
  provinces: ProvinceCoverage[]; selected?: string | null; hrefFor: (code: string) => string; title?: string;
}) {
  const router = useRouter();
  const [hover, setHover] = useState<string | null>(null);
  const byCode = new Map(provinces.map((p) => [p.province_code, p]));
  const shown = hover ?? selected ?? null;
  const info = shown ? byCode.get(shown) : undefined;
  const counts = { records: 0, controls: 0, none: 0 } as Record<Status, number>;
  for (const shape of TURKEY_PROVINCES) counts[statusOf(byCode.get(shape.iso.slice(3)))] += 1;
  return (
    <section className="national-map card" aria-label={title}>
      <div className="card-head">
        <h2>{title}</h2>
        <span className="small muted">{counts.records} with records · {counts.controls} with source data only · {counts.none} without source data</span>
      </div>
      <svg viewBox="0 0 860 380" role="group" aria-label={`${title}. Select a province to explore it.`} className="national-map-svg">
        {TURKEY_PROVINCES.map((shape) => {
          const code = shape.iso.slice(3);
          const p = byCode.get(code);
          const status = statusOf(p);
          const label = `${shape.name} (${code}): ${LABEL[status]}${p && p.records ? `, ${fmtInt(p.records)} records` : ""}`;
          return (
            <a key={shape.iso} href={hrefFor(code)} aria-label={label}
               onClick={(e) => { e.preventDefault(); router.push(hrefFor(code)); }}
               onMouseEnter={() => setHover(code)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(code)} onBlur={() => setHover(null)}>
              <path d={shape.path} className={`prov prov-${status}${selected === code ? " prov-selected" : ""}`}><title>{label}</title></path>
            </a>
          );
        })}
      </svg>
      <div className="map-info" aria-live="polite">
        {info ? (
          <span><strong>{info.province_name}</strong> · {info.province_code} · {info.nuts3_code} · {LABEL[statusOf(info)]}
            {info.records ? ` · ${fmtInt(info.records)} records representing ${fmtInt(info.represented_population)} residents` : ""}</span>
        ) : <span className="muted">Hover or focus a province for its coverage; select it to open the Population Explorer.</span>}
      </div>
      <div className="legend" aria-label="Legend">
        <span><i className="legend-key prov-records-key" />Records in this population</span>
        <span><i className="legend-key prov-controls-key" />Source data only</span>
        <span><i className="legend-key prov-none-key" />No source data</span>
        <span><i className="legend-key prov-selected-key" />Selected</span>
        <a href="/map-attribution.md" target="_blank" rel="noreferrer">Boundaries: geoBoundaries / OSM (2021), CC BY-SA 2.0</a>
      </div>
    </section>
  );
}
