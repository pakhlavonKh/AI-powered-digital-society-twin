"use client";

import { useBuild } from "@/lib/build";
import { fmtInt } from "@/lib/format";
import { Badge } from "./StatusBadge";

/** Build selector and scope badge. The selection lives in the URL; a missing build is reported, never replaced. */
export function BuildBar() {
  const { builds, build, missingBuildId, usingDefault, loading, error, select } = useBuild();
  return (
    <div className="topbar" role="region" aria-label="Selected population build">
      <div className="build-field">
        <label htmlFor="build-select">Build</label>
        <select
          id="build-select"
          value={build?.build_id ?? missingBuildId ?? ""}
          onChange={(e) => select(e.target.value)}
          disabled={loading || builds.length === 0}
        >
          {missingBuildId ? <option value={missingBuildId}>{missingBuildId} (not registered)</option> : null}
          {builds.length === 0 ? <option value="">{loading ? "Loading builds…" : "No builds"}</option> : null}
          {builds.map((b) => (
            <option key={b.build_id} value={b.build_id} disabled={b.availability.status !== "available"}>
              {b.variant === "v2" ? "v2: age, sex, marital status" : "base: age, sex"}{b.is_default ? " (default)" : ""} · {b.build_id}
              {b.availability.status !== "available" ? " · source changed" : ""}
            </option>
          ))}
        </select>
      </div>
      {build ? (
        <div className="row small" aria-live="polite">
          <Badge tone="info" glyph="⌖">{build.scope.province} · {build.scope.reference_year}</Badge>
          <span className="muted">{fmtInt(build.row_count)} synthetic residents · {build.variant} build{usingDefault ? " (default)" : ""}</span>
          {build.availability.status !== "available" ? <Badge tone="warn" glyph="!">Source changed</Badge> : null}
        </div>
      ) : null}
      {missingBuildId ? <Badge tone="crit" glyph="!">Build {missingBuildId} is not registered; nothing else was selected</Badge> : null}
      {error ? <Badge tone="crit" glyph="!">Builds unavailable: {error.message}</Badge> : null}
    </div>
  );
}
