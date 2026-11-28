"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSelectedSnapshot, useUniversityCapabilities } from "@/lib/university/context";
import { Badge } from "../StatusBadge";
import { SourceBadge } from "./common";

/** Top bar for /university/* explorer pages: shows active snapshot, fixture vs API provenance, and link to /university studio. */
export function UniversityBar() {
  const { snapshot, snapshots, missingId, loading, error } = useSelectedSnapshot();
  const caps = useUniversityCapabilities();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const select = (id: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("snapshot", id);
    for (const k of ["program", "page", "candidate", "run", "a", "b"]) next.delete(k);
    router.replace(`${pathname}?${next.toString()}`);
  };
  const exec = caps.data?.execution;
  return (
    <div className="topbar" role="region" aria-label="University data source">
      <div className="topbar-caption">TÜRKİYE <span>/</span> UNIVERSITY SIMULATION</div>
      <div className="build-field">
        <label htmlFor="snapshot-select">Registry snapshot</label>
        <select id="snapshot-select" value={snapshot?.snapshot_id ?? missingId ?? ""} onChange={(e) => select(e.target.value)} disabled={loading || snapshots.length === 0}>
          {missingId ? <option value={missingId}>{missingId} (not found)</option> : null}
          {snapshots.length === 0 ? <option value="">{loading ? "Loading snapshots…" : "No snapshot available"}</option> : null}
          {snapshots.map((s) => <option key={s.snapshot_id} value={s.snapshot_id}>{s.snapshot_id} · {s.counts.programs} programs · {s.admission_years[0]}–{s.admission_years[s.admission_years.length - 1]}</option>)}
        </select>
      </div>
      <div className="row small" aria-live="polite">
        {caps.data ? <SourceBadge origin={caps.data.origin} /> : null}
        {exec ? (
          exec.mode === "fixture_preview" ? <Badge tone="fake" glyph="◇" title={exec.detail}>Execution: fixture preview only</Badge>
            : exec.mode === "api" ? <Badge tone="good" glyph="✓" title={exec.detail}>Execution: placement API</Badge>
              : <Badge tone="warn" glyph="!" title={exec.detail}>Execution unavailable</Badge>
        ) : null}
        {caps.data?.origin === "local_preview" ? <Badge tone="info" glyph="·" title="Remove ?source=local-preview from the URL to return to the fixtures.">Explorer mode: local preview</Badge> : null}
        {caps.data && caps.data.origin === "fixture" ? (
          <Badge
            tone="info"
            glyph="·"
            title="This sub-explorer uses fixture:university-ui-v1; live SQLite registry queries (/api/v2/university-registry/*) and placement simulation (/university) are available."
          >
            Explorer mode: UI fixtures
          </Badge>
        ) : null}
        <Link className="button small" href="/university">Placement Studio →</Link>
      </div>
      {missingId ? <Badge tone="crit" glyph="!">Snapshot {missingId} does not exist; nothing else was selected</Badge> : null}
      {error ? <Badge tone="crit" glyph="!">Snapshots unavailable: {error.message}</Badge> : null}
    </div>
  );
}
