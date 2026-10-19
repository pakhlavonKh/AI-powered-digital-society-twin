"use client";

import Link from "next/link";
import type { Schemas } from "@/lib/api/client";
import { fmtInt, shortHash } from "@/lib/format";
import { NOT_RECORDED } from "@/lib/recordedRuns";
import { withBuild } from "@/lib/urls";
import { KeyValues } from "../StatTile";
import { Badge, CheckBadge } from "../StatusBadge";

type Trial = Schemas["Trial"];
type View = Schemas["PersonaView"];

/** The stored persona file this trial used, matched by the snapshot's SHA-256 (never by name). */
export function matchedArtifact(trial: Trial, view: View | null | undefined): Schemas["PersonaArtifact"] | undefined {
  const sha = trial.persona_snapshot?.sha256;
  return sha ? view?.personas.find((p) => p.sha256 === sha) : undefined;
}

/** `dst_age_group` -> "age group"; `demo_marital_status` -> "marital status". */
function dimensionName(key: string): string {
  return key.replace(/^(dst|demo)_/, "").replace(/_/g, " ");
}

const HEADLINE: [string, string][] = [["age_group", "Age group"], ["gender", "Sex (administrative)"], ["marital_status", "Marital status"], ["province", "Province"]];

function Visibility({ artifact, field }: { artifact: Schemas["PersonaArtifact"] | undefined; field: string }) {
  if (!artifact) return null;
  const via = artifact.mapped_fields.filter((m) => m.source_field === field && artifact.prompt_visible_fields.includes(m.dimension));
  if (via.length) return <span className="small muted">Model saw {via.map((m) => `${dimensionName(m.dimension)} “${m.value}”`).join(", ")}</span>;
  if (artifact.metadata_only_fields.includes(field)) return <Badge tone="warn" glyph="⊘">Not shown to the model</Badge>;
  return null;
}

function PersonaCard({ trial, slot, view, linkBuild }: { trial: Trial; slot: string; view: View | null | undefined; linkBuild: string | null }) {
  const snap = trial.persona_snapshot && !trial.persona_snapshot.parse_error ? trial.persona_snapshot : null;
  const artifact = matchedArtifact(trial, view);
  const attrs: Record<string, unknown> = snap?.source_attributes ?? view?.source_card.attributes ?? {};
  const translations = view?.source_card.display_translations ?? {};
  const value = (field: string): string | null => {
    if (field === "province") {
      return artifact?.mapped_fields.find((m) => m.source_field === "province")?.value ?? snap?.dimensions.dst_residence_province ?? null;
    }
    const raw = attrs[field];
    if (raw === undefined || raw === null || raw === "") return null;
    const text = String(raw);
    if (field === "gender") return text.charAt(0).toUpperCase() + text.slice(1);
    const label = translations[field]?.[text];
    return label && label !== text ? `${label} (${text})` : text;
  };
  const visible = artifact ? artifact.prompt_visible_fields : Object.keys(snap?.dimensions ?? {});
  const limits = [snap?.dimensions.dst_evidence_limit, ...(artifact?.mapping_warnings ?? []), view?.notes.gender_field].filter((x): x is string => Boolean(x));
  const meta = artifact?.metadata ?? {};
  return (
    <article className="card persona-side stack" aria-label={`Persona ${slot}`}>
      <div className="card-head" style={{ marginBottom: 0 }}>
        <h3>Persona {slot}</h3>
        {trial.persona_id ? <Link className="small" href={withBuild("/historical/personas", linkBuild, { record: trial.persona_id })}>Persona Explorer</Link> : null}
      </div>
      <dl className="persona-facts">
        <div><dt>Synthetic ID</dt><dd><code>{trial.persona_id ?? NOT_RECORDED}</code></dd></div>
        {HEADLINE.map(([field, label]) => (
          <div key={field}><dt>{label}</dt><dd>{value(field) ?? NOT_RECORDED} <Visibility artifact={artifact} field={field} /></dd></div>
        ))}
      </dl>
      {!snap ? <p className="small muted" style={{ margin: 0 }}>No persona snapshot was saved with this trial.</p> : null}
      {snap && !artifact ? <p className="small muted" style={{ margin: 0 }}>No stored persona in the selected build matches this snapshot&apos;s hash; values are read from the run snapshot only.</p> : null}
      <details>
        <summary>Model-visible attributes ({visible.length})</summary>
        <div className="details-body">
          <p className="small muted" style={{ margin: 0 }}>Prompt dimensions exactly as saved with this trial.</p>
          <KeyValues items={visible.map((k) => [k, snap?.dimensions[k] ?? NOT_RECORDED] as [string, React.ReactNode])} />
        </div>
      </details>
      <details>
        <summary>Available synthetic attributes</summary>
        <div className="details-body">
          <KeyValues items={Object.entries(attrs).map(([k, v]) => [k, String(v)] as [string, React.ReactNode])} />
          {artifact?.metadata_only_fields.length ? <p className="small muted" style={{ margin: 0 }}>Kept in metadata only (never shown to the model): {artifact.metadata_only_fields.join(", ")}.</p> : null}
          {snap?.unassigned_fields.length ? <p className="small muted" style={{ margin: 0 }}>Not assigned to this persona: {snap.unassigned_fields.join(", ")}.</p> : null}
        </div>
      </details>
      <details>
        <summary>Evidence limitations ({limits.length})</summary>
        <div className="details-body">{limits.length ? <ul style={{ margin: 0 }}>{limits.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="small muted">None recorded.</p>}</div>
      </details>
      <details>
        <summary>Source and provenance</summary>
        <div className="details-body">
          <KeyValues items={[
            ["Run snapshot", snap ? <span key="s"><code>{snap.relpath ?? NOT_RECORDED}</code> · SHA-256 <code>{shortHash(snap.sha256, 16)}</code></span> : NOT_RECORDED],
            ["Stored persona", artifact ? <span key="a"><code>{artifact.relpath}</code> · same SHA-256 as the snapshot</span> : "No matching stored persona"],
            ["Source row", snap?.source_csv_row != null ? `CSV row ${fmtInt(snap.source_csv_row)}` : NOT_RECORDED],
            ["Row check", artifact?.source_row_check ? <span key="r"><CheckBadge passed={artifact.source_row_check.passed} /> {artifact.source_row_check.detail}</span> : NOT_RECORDED],
            ["Source population", typeof meta.source_population === "string" ? <code key="p">{meta.source_population}</code> : NOT_RECORDED],
            ["Generation seed", meta.generation_seed != null ? `${String(meta.generation_seed)}${typeof meta.seed_provenance === "string" ? ` · ${meta.seed_provenance}` : ""}` : NOT_RECORDED],
            ["Attribution", artifact?.attribution_note ?? NOT_RECORDED],
          ]} />
          {artifact?.mapped_fields.length ? (
            <div className="table-wrap">
              <table>
                <caption>How each prompt dimension was derived (as recorded in the persona file)</caption>
                <thead><tr><th scope="col">Dimension</th><th scope="col">Source field</th><th scope="col">Dataset</th><th scope="col">Method</th></tr></thead>
                <tbody>{artifact.mapped_fields.map((m) => <tr key={m.dimension}><th scope="row"><code>{m.dimension}</code></th><td>{m.source_field ?? "–"}</td><td>{m.dataset ?? "–"}</td><td>{m.method ?? "–"}</td></tr>)}</tbody>
              </table>
            </div>
          ) : null}
        </div>
      </details>
    </article>
  );
}

/** Persona A and B side by side, with the recorded comparison between them. */
export function PersonaPair({ result, trials, views, linkBuild }: {
  result: Schemas["Results"]; trials: Trial[]; views: Map<string, View | null> | undefined; linkBuild: string | null;
}) {
  const [a, b] = trials;
  const compared = result.comparison_rows.length;
  const differ = result.differing_values_recomputed;
  const agrees = result.differing_values_recorded === null || result.differing_values_recorded === differ;
  const dimsA = a?.persona_snapshot?.dimensions ?? {};
  const dimsB = b?.persona_snapshot?.dimensions ?? {};
  const differing = Object.keys(dimsA).filter((k) => k in dimsB && dimsA[k] !== dimsB[k]).map(dimensionName);
  return (
    <section className="stack" aria-labelledby="pair-h">
      <h2 id="pair-h" style={{ margin: 0 }}>Persona A vs Persona B</h2>
      <div className="persona-pair">
        {a ? <PersonaCard trial={a} slot="A" view={a.persona_id ? views?.get(a.persona_id) : null} linkBuild={linkBuild} /> : null}
        <div className="pair-verdict card" role="group" aria-label="Recorded comparison">
          {differ !== null && compared ? (
            <>
              <strong className="pair-count">{fmtInt(differ)} / {compared}</strong>
              <span>survey answers differed</span>
              {!agrees ? <span className="small muted">The comparison file records {fmtInt(result.differing_values_recorded)}.</span> : null}
            </>
          ) : <span className="muted">No recorded comparison</span>}
          {differing.length ? <span className="small muted">Model-visible differences: {differing.join(", ")}.</span> : null}
          <span className="small muted">One recorded response each; not a population estimate.</span>
        </div>
        {b ? <PersonaCard trial={b} slot="B" view={b.persona_id ? views?.get(b.persona_id) : null} linkBuild={linkBuild} /> : null}
      </div>
    </section>
  );
}
