import Link from "next/link";
import type { Schemas } from "@/lib/api/client";
import { fmtInt } from "@/lib/format";
import { TURKEY_PROVINCES } from "@/lib/turkey-provinces";

/**
 * Small geographic context for a single-province historical build. The national coverage map lives on the dashboard;
 * this outline only locates the build's province and is not interactive.
 */
export function LocationCard({ build, exploreHref }: { build: Schemas["BuildDescriptor"]; exploreHref: string }) {
  const province = build.scope.province;
  const mapped = TURKEY_PROVINCES.some((p) => p.name === province);
  return (
    <section className="card location-card stack" aria-labelledby="location-h">
      <h2 id="location-h" style={{ margin: 0 }}>Location</h2>
      {mapped ? (
        <svg viewBox="0 0 860 380" className="mini-outline" role="img" aria-label={`Outline of Türkiye with ${province} highlighted`}>
          {TURKEY_PROVINCES.map((p) => <path key={p.iso} d={p.path} className={p.name === province ? "on" : undefined} />)}
        </svg>
      ) : null}
      <dl className="facts">
        <div><dt>Location</dt><dd>{province}{mapped ? ", Türkiye" : ""}</dd></div>
        <div><dt>Population build</dt><dd>{fmtInt(build.row_count)} synthetic residents</dd></div>
        <div><dt>Reference year</dt><dd>{build.scope.reference_year}</dd></div>
        <div><dt>Build</dt><dd>{build.variant}{build.is_default ? " (default)" : ""}</dd></div>
      </dl>
      <p className="small muted" style={{ margin: 0 }}>No other province has loaded data in this build. National coverage is on the <Link href="/">dashboard</Link>.</p>
      <Link className="small" href={exploreHref}>Explore this population →</Link>
    </section>
  );
}
