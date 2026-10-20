import type { Schemas } from "@/lib/api/client";
import { CopyId } from "./CopyId";
import { KeyValues } from "./StatTile";

/** Technical provenance of a build, kept in an expandable panel. */
export function BuildDetails({ build, open = false }: { build: Schemas["BuildDescriptor"]; open?: boolean }) {
  return (
    <details open={open}>
      <summary>Build provenance and evidence gaps</summary>
      <div className="details-body">
        <KeyValues items={[
          ["Build ID", <CopyId key="id" value={build.build_id} label="build ID" />],
          ["Source file", <code key="p">{build.source_path}</code>],
          ["Source SHA-256", <code key="h">{build.source_sha256}</code>],
          ["Rows", String(build.row_count)],
          ["Schema", `${build.schema_version} (${build.schema_note})`],
          ["Columns", build.available_fields.join(", ")],
          ["Generator method", build.generator.method],
          ["Configured seed", build.generator.configured_seed === null ? "unknown" : String(build.generator.configured_seed)],
          ["Seed evidence", build.generator.seed_evidence],
          ["Scope evidence", build.scope.evidence],
          ["Origin", build.origin],
          ["Registered", build.registered_at],
        ]} />
        <div>
          <h3>Evidence gaps</h3>
          <ul>{build.evidence_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </div>
        <div>
          <h3>Not in these rows</h3>
          <ul>{build.unavailable_fields.map((f) => <li key={f.field}><code>{f.field}</code>: {f.reason}</li>)}</ul>
        </div>
      </div>
    </details>
  );
}
