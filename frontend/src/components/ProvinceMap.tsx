"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
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

const VIEW = { width: 860, height: 380 };

/** Bounding box of an outline from its absolute M/L coordinates, as fractions of the view box (for placing the tooltip). */
function bounds(path: string) {
  const nums = path.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i + 1 < nums.length; i += 2) {
    minX = Math.min(minX, nums[i]); maxX = Math.max(maxX, nums[i]);
    minY = Math.min(minY, nums[i + 1]); maxY = Math.max(maxY, nums[i + 1]);
  }
  return { cx: (minX + maxX) / 2 / VIEW.width, top: minY / VIEW.height, bottom: maxY / VIEW.height };
}

/**
 * All 81 provinces from the geoBoundaries outline (keyed by ISO 3166-2, which uses the plate codes).
 * Fill encodes data availability only; it is not a choropleth of any statistic. Provinces with records are links into the
 * Population Explorer; every other province is a button that pins its coverage tooltip instead of navigating to an empty view.
 */
export function ProvinceMap({ provinces, selected, hrefFor, referenceYear, note, title = "Türkiye province coverage" }: {
  provinces: ProvinceCoverage[]; selected?: string | null; hrefFor: (code: string) => string; referenceYear?: number | null;
  note?: React.ReactNode; title?: string;
}) {
  const router = useRouter();
  const [hover, setHover] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const byCode = new Map(provinces.map((p) => [p.province_code, p]));
  const boxes = useMemo(() => new Map(TURKEY_PROVINCES.map((s) => [s.iso.slice(3), bounds(s.path)])), []);
  const active = hover ?? pinned ?? selected ?? null;
  const activeShape = active ? TURKEY_PROVINCES.find((s) => s.iso === `TR-${active}`) : undefined;
  const info = active ? byCode.get(active) : undefined;
  const activeStatus = statusOf(info);
  const box = active ? boxes.get(active) : undefined;
  const below = box ? box.top < 0.32 : false;
  const counts = { records: 0, controls: 0, none: 0 } as Record<Status, number>;
  for (const shape of TURKEY_PROVINCES) counts[statusOf(byCode.get(shape.iso.slice(3)))] += 1;
  const announce = (code: string) => {
    const p = byCode.get(code);
    const name = p?.province_name ?? TURKEY_PROVINCES.find((s) => s.iso === `TR-${code}`)?.name ?? code;
    const status = statusOf(p);
    return `${name} (${code}): ${LABEL[status]}${p && p.records ? `, ${fmtInt(p.records)} records` : ""}`;
  };
  return (
    <section className="national-map card" aria-label={title} onKeyDown={(e) => { if (e.key === "Escape") setPinned(null); }}>
      <div className="card-head">
        <h2>{title}</h2>
        <span className="small muted">{counts.records} with records · {counts.controls} with source data only · {counts.none} without source data</span>
      </div>
      {note}
      <div className="map-stage">
        <svg viewBox={`0 0 ${VIEW.width} ${VIEW.height}`} role="group" aria-label={`${title}. Provinces with records open the Population Explorer.`} className="national-map-svg">
          {TURKEY_PROVINCES.map((shape) => {
            const code = shape.iso.slice(3);
            const status = statusOf(byCode.get(code));
            const label = announce(code);
            const path = <path d={shape.path} className={`prov prov-${status}${selected === code || pinned === code ? " prov-selected" : ""}`} />;
            const events = { onMouseEnter: () => setHover(code), onMouseLeave: () => setHover(null), onFocus: () => setHover(code), onBlur: () => setHover(null) };
            if (status === "records") {
              return (
                <a key={shape.iso} href={hrefFor(code)} aria-label={label} {...events}
                   onClick={(e) => { e.preventDefault(); router.push(hrefFor(code)); }}>{path}</a>
              );
            }
            const toggle = () => setPinned((p) => (p === code ? null : code));
            return (
              <g key={shape.iso} role="button" tabIndex={0} aria-label={label} aria-pressed={pinned === code} className="prov-button" {...events}
                 onClick={toggle} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}>{path}</g>
            );
          })}
        </svg>
        {activeShape && box ? (
          <div className={`map-tip${below ? " below" : ""}`} aria-hidden="true"
               style={{ left: `clamp(115px, ${(box.cx * 100).toFixed(1)}%, calc(100% - 115px))`, top: `${((below ? box.bottom : box.top) * 100).toFixed(1)}%` }}>
            <strong>{info?.province_name ?? activeShape.name}</strong>
            <dl>
              <dt>Source data</dt><dd>{info?.has_population_controls ? "Available" : "Not loaded"}</dd>
              {activeStatus === "records" ? <>
                <dt>Synthetic records</dt><dd>{fmtInt(info!.records)}</dd>
                {info!.represented_population !== null ? <><dt>Residents represented</dt><dd>{fmtInt(info!.represented_population)}</dd></> : null}
                {referenceYear ? <><dt>Reference year</dt><dd>{referenceYear}</dd></> : null}
              </> : <>
                <dt>Synthetic population</dt><dd>{activeStatus === "controls" ? "None in the selected population" : "Not available"}</dd>
              </>}
            </dl>
            {activeStatus === "records" ? <span className="map-tip-action">Explore population →</span>
              : <span className="map-tip-note">{activeStatus === "none" ? "No source data loaded" : "Generate a population that includes it"}</span>}
          </div>
        ) : null}
      </div>
      <p className="visually-hidden" aria-live="polite">{active ? announce(active) : ""}</p>
      <p className="map-info small muted">Hover or focus a province for its coverage. Provinces with records open the Population Explorer;
        the others show their coverage here.</p>
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
