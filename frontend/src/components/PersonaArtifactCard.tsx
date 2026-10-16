import type { Schemas } from "@/lib/api/client";
import { fmtValue } from "@/lib/format";
import { CopyId } from "./CopyId";
import { Notice } from "./Notices";
import { KeyValues } from "./StatTile";
import { Badge, CheckBadge, HashBadge } from "./StatusBadge";

/** One stored persona YAML: what the model sees versus what stays in metadata, with provenance checks. */
export function PersonaArtifactCard({ persona, sourceAttributes }: { persona: Schemas["PersonaArtifact"]; sourceAttributes: Record<string, string> }) {
  if (!persona.valid) {
    return (
      <section className="card">
        <h3>Persona file <code>{persona.relpath}</code></h3>
        <Notice tone="crit" title="Invalid persona file.">{persona.error}</Notice>
      </section>
    );
  }
  return (
    <section className="card stack" aria-label={`Persona YAML ${persona.relpath}`}>
      <div className="card-head">
        <h3>MatrAIx persona YAML <code>{persona.relpath}</code></h3>
        {persona.origin === "fixture" ? <Badge tone="neutral" glyph="⧉">Stored fixture</Badge> : <Badge tone="info" glyph="◆">Materialized here</Badge>}
      </div>
      <p className="small muted">
        A MatrAIx-compatible persona file (envelope <code>persona_id</code>, <code>version {persona.version}</code>, <code>source: {persona.source}</code>).
        Only the dimensions below are rendered into the model prompt. SHA-256 <code>{persona.sha256}</code>
      </p>
      {persona.mapping_warnings.length ? (
        <Notice tone="warn" title="Read before using this persona:"><ul>{persona.mapping_warnings.map((w) => <li key={w}>{w}</li>)}</ul></Notice>
      ) : null}
      <div className="table-wrap">
        <table>
          <caption>Shown to the model (prompt-visible dimensions) with their source mapping</caption>
          <thead><tr><th scope="col">Dimension</th><th scope="col">Value</th><th scope="col">Source field</th><th scope="col">Source value</th><th scope="col">Method</th><th scope="col">Provenance type</th></tr></thead>
          <tbody>
            {persona.mapped_fields.map((m) => (
              <tr key={m.dimension}>
                <th scope="row"><code>{m.dimension}</code></th>
                <td>{m.value}</td>
                <td>{m.source_field ? <code>{m.source_field}</code> : "–"}</td>
                <td>{m.source_value ?? "–"}</td>
                <td className="small">{m.method ?? "–"}</td>
                <td className="small">{m.source_type ?? "–"}{m.dataset ? ` (${m.dataset})` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid-2">
        <div>
          <h4>Kept in metadata only (never shown to the model)</h4>
          {persona.metadata_only_fields.length ? (
            <ul>{persona.metadata_only_fields.map((f) => <li key={f}><code>{f}</code>: {sourceAttributes[f] ?? "–"}</li>)}</ul>
          ) : <p className="muted small">None.</p>}
        </div>
        <div>
          <h4>Not assigned (do not exist for this persona)</h4>
          <p className="small">{persona.unassigned_fields.length ? persona.unassigned_fields.map((f) => <code key={f} style={{ marginRight: 6 }}>{f}</code>) : "None listed."}</p>
          <p className="small muted">Nothing here is filled from stereotypes or documentation examples. A model may still fill such gaps with its own defaults.</p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <caption>Provenance digests recorded in the YAML versus today&apos;s files</caption>
          <thead><tr><th scope="col">Recorded input</th><th scope="col">Path as recorded</th><th scope="col">Recorded SHA-256</th><th scope="col">Comparison</th></tr></thead>
          <tbody>
            {persona.hash_checks.map((h) => (
              <tr key={h.name}>
                <th scope="row">{h.name}</th>
                <td><code>{h.path ?? "–"}</code></td>
                <td><code>{h.recorded_sha256 ? `${h.recorded_sha256.slice(0, 16)}…` : "not comparable"}</code></td>
                <td><HashBadge status={h.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {persona.source_row_check ? (
        <p className="row small"><CheckBadge passed={persona.source_row_check.passed} /> {persona.source_row_check.detail}</p>
      ) : null}
      {persona.attribution_note ? <p className="small muted">{persona.attribution_note}</p> : null}
      <details>
        <summary>Full persona metadata</summary>
        <div className="details-body">
          <KeyValues items={Object.entries(persona.metadata).map(([k, v]) => [k, typeof v === "object" && v !== null ? <code key={k}>{JSON.stringify(v)}</code> : fmtValue(v)])} />
          <p className="small">Provenance source types used: {persona.provenance_source_types.join(", ") || "none"} (the adapter&apos;s own vocabulary; not relabelled).</p>
          <span className="small">Persona artifact ID: <CopyId value={persona.persona_artifact_id} label="persona artifact ID" /></span>
        </div>
      </details>
    </section>
  );
}
