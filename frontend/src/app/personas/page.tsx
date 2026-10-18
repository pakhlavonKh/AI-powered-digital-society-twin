"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { PersonaGallery } from "@/components/PersonaGallery";
import { Icon } from "@/components/Icon";
import { PersonaComparison } from "@/components/PersonaComparison";
import { CopyId } from "@/components/CopyId";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { PersonaArtifactCard } from "@/components/PersonaArtifactCard";
import { RuntimeProbeButton } from "@/components/RuntimeProbeButton";
import { EmptyState, ErrorState, Loading, UnavailableState } from "@/components/States";
import { KeyValues } from "@/components/StatTile";
import { Badge, RunStateBadge } from "@/components/StatusBadge";
import { api, toApiError, unwrap, type ApiError } from "@/lib/api/client";
import { useBuild } from "@/lib/build";
import { FIELD_LABELS } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

const STATUS_TEXT: Record<string, [string, "neutral" | "info" | "good"]> = {
  source_card_only: ["Source card only: no persona file exists for this resident", "neutral"],
  fixture_persona: ["Stored fixture persona available", "info"],
  materialized_persona: ["Persona materialized in this workbench", "info"],
  fixture_and_materialized: ["Fixture and materialized personas available", "info"],
};

export default function PersonaPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const record = params.get("record");
  const linkBuild = params.get("build");
  const { build, missingBuildId } = useBuild();
  const buildId = build?.availability.status === "available" ? build.build_id : null;
  const [lookup, setLookup] = useState(record ?? "");
  const [materializing, setMaterializing] = useState(false);
  const [matError, setMatError] = useState<ApiError | undefined>();

  const index = useApi(buildId ? `persona-index:${buildId}` : null, (signal) =>
    unwrap(api.GET("/api/v1/personas/{build_id}", { params: { path: { build_id: buildId! } }, signal })));
  const view = useApi(buildId && record ? `persona:${buildId}:${record}` : null, (signal) =>
    unwrap(api.GET("/api/v1/personas/{build_id}/{record_id}", { params: { path: { build_id: buildId!, record_id: record! } }, signal })));
  const v = view.data;

  const open = (id: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("record", id.trim());
    router.push(`${pathname}?${next.toString()}`);
  };

  async function materialize() {
    if (!buildId || !record) return;
    setMaterializing(true);
    setMatError(undefined);
    try {
      await unwrap(api.POST("/api/v1/personas/{build_id}/{record_id}/materialize", { params: { path: { build_id: buildId, record_id: record } } }));
      view.reload();
      index.reload();
    } catch (err) {
      setMatError(toApiError(err));
    } finally {
      setMaterializing(false);
    }
  }

  const status = v ? STATUS_TEXT[v.persona_status] : undefined;
  return (
    <>
      <PageHeader title="Persona Explorer">
        Synthetic resident cards created from demographic data. Explore their sources and model-visible attributes.
      </PageHeader>
      <SyntheticNotice kind="responses" />
      {missingBuildId ? <UnavailableState title={`Build ${missingBuildId} is not registered.`} /> : null}

      <section className={`card stack ${record ? "" : "persona-search"}`} aria-labelledby="lookup-h">
        <h2 id="lookup-h">Choose a resident</h2>
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (lookup.trim()) open(lookup); }}>
          <label htmlFor="record-input">Resident ID</label>
          <input id="record-input" type="text" value={lookup} onChange={(e) => setLookup(e.target.value)} placeholder="ANK2025_000001" style={{ flex: "1 1 200px" }} />
          <button type="submit" className="button">Open</button>
        </form>
        {index.data ? (
          index.data.items.length ? (
            <div className="row small">
              <span className="muted">Residents with a stored persona in this build:</span>
              {index.data.items.map((i) => (
                <Link key={i.persona_artifact_id} href={withBuild("/personas", linkBuild, { record: i.record_id })}>
                  {i.record_id} ({i.origin})
                </Link>
              ))}
            </div>
          ) : <p className="small muted">No stored personas are linked to this build. {build?.variant === "base" ? "The persona adapter reads only the v2 build." : ""}</p>
        ) : null}
      </section>

      {!record && buildId ? <PersonaGallery buildId={buildId} linkBuild={linkBuild}/> : null}
      {view.loading && !v ? <Loading what="resident" /> : null}
      {view.error ? <ErrorState error={view.error} onRetry={view.reload} what={`resident ${record}`} /> : null}

      {v ? (
        <div className={`stack ${view.loading ? "is-stale" : ""}`} aria-busy={view.loading}>
          <div className="row">
            <h2 style={{ margin: 0 }}>Resident <code>{v.record_id}</code></h2>
            {status ? <Badge tone={status[1]} glyph={status[1] === "neutral" ? "·" : "◆"}>{status[0]}</Badge> : null}
          </div>

          <div className="persona-detail-layout">
          <section className="card stack" aria-labelledby="card-h">
            <div className="persona-detail-heading"><span className="persona-avatar"><Icon name="persona" size={36}/></span><div><h2>{v.record_id}</h2><span className="small muted">Fictional synthetic resident · {v.source_card.context.province}</span></div></div>
            <div className="card-head"><h3 id="card-h">Source card: the population row</h3><Badge tone="neutral" glyph="▤">Not a persona</Badge></div>
            <p className="small muted">{v.source_card.note}</p>
            <div className="table-wrap">
              <table>
                <caption>Row {v.source_card.csv_row} of <code>{v.source_card.source_path}</code></caption>
                <thead><tr><th scope="col">Field</th><th scope="col">Source value</th><th scope="col">Display translation</th></tr></thead>
                <tbody>
                  {Object.entries(v.source_card.attributes).map(([field, value]) => (
                    <tr key={field}>
                      <th scope="row">{FIELD_LABELS[field] ?? field} <span className="muted small"><code>{field}</code></span></th>
                      <td>{value}</td>
                      <td className="muted">{v.source_card.display_translations[field]?.[value] ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <KeyValues items={[
              ["Build context", `${v.source_card.context.province}, ${v.source_card.context.reference_year}`],
              ["How the context is known", v.source_card.context.evidence],
              ["Source file SHA-256", <code key="s">{v.source_card.source_sha256}</code>],
              ["Sex field", v.notes.gender_field ?? ""],
            ]} />
            <details>
              <summary>Source tables and fields that are not modelled</summary>
              <div className="details-body">
                <ul>{v.source_card.source_tables.map((t) => <li key={t.field}><code>{t.field}</code> from <code>{t.table}</code>: {t.note}</li>)}</ul>
                <ul>{v.source_card.not_modelled.map((f) => <li key={f.field}><code>{f.field}</code>: {f.reason}</li>)}</ul>
              </div>
            </details>
          </section>

          <PersonaComparison recordId={v.record_id} evidence={v.historical_prompt_evidence} linkBuild={linkBuild}/>
          </div>
          {v.personas.map((p) => <PersonaArtifactCard key={p.persona_artifact_id} persona={p} sourceAttributes={v.source_card.attributes} />)}

          <div className="grid-2">
            <section className="card stack" aria-labelledby="mat-h">
              <h3 id="mat-h">Materialize a persona with the existing adapter</h3>
              <p className="small">
                Runs the project&apos;s persona adapter for this resident in an isolated process. It writes a new YAML under managed state and
                makes no model calls. Unsupported mappings fail visibly; the prompt is never adjusted to make a run work.
              </p>
              <ul className="small">{v.materialization.expected_omissions.map((o) => <li key={o}>{o}</li>)}</ul>
              {v.materialization.available ? null : (
                <UnavailableState title="Materialization is unavailable here." reasons={v.materialization.reasons}>
                  {v.materialization.reasons.some((r) => r.includes("import probe")) ? <RuntimeProbeButton onDone={view.reload} /> : null}
                </UnavailableState>
              )}
              {matError ? <ErrorState error={matError} what="materialization" /> : null}
              <div className="row">
                <button type="button" className="button" onClick={materialize} disabled={!v.materialization.available || materializing}>
                  {materializing ? "Running adapter…" : "Materialize persona"}
                </button>
              </div>
              <p className="small muted">{v.materialization.output_note}</p>
            </section>
            <section className="card stack" aria-labelledby="runner-h">
              <h3 id="runner-h">Fixed two-persona A/B runner</h3>
              <p className="row small">
                {v.legacy_runner.in_fixed_pair
                  ? <Badge tone="info" glyph="◆">{`In the fixed pair (slot ${v.legacy_runner.slot})`}</Badge>
                  : <Badge tone="neutral" glyph="·">Not in the fixed pair</Badge>}
                <span className="muted">Fixed IDs: {v.legacy_runner.fixed_ids.join(", ")}</span>
              </p>
              <p className="small">{v.legacy_runner.note}</p>
              <p className="small muted">The two fixture personas differ in age band and in marital status, so they are not a single-attribute contrast.</p>
            </section>
          </div>

          <section className="card stack" aria-labelledby="evidence-h">
            <h3 id="evidence-h">Recorded prompt evidence</h3>
            <p className="small muted">Prompts are shown only as they were recorded in a run folder. Nothing is re-rendered for this page.</p>
            {v.historical_prompt_evidence.length === 0 ? <p className="muted">No recorded run used this resident.</p> : (
              <div className="table-wrap">
                <table>
                  <caption>Runs whose recorded prompts name this resident</caption>
                  <thead><tr><th scope="col">Run</th><th scope="col">Trial</th><th scope="col">Run state</th><th scope="col">Model</th><th scope="col">Prompt source</th><th scope="col">System prompt SHA-256</th></tr></thead>
                  <tbody>
                    {v.historical_prompt_evidence.map((e) => (
                      <tr key={`${e.experiment_id}:${e.trial_label}`}>
                        <th scope="row"><Link href={withBuild(`/results/${encodeURIComponent(e.experiment_id)}`, linkBuild, { trial: e.trial_label })}>{e.experiment_id}</Link></th>
                        <td>{e.trial_label}</td>
                        <td><RunStateBadge state={e.display_state} /></td>
                        <td><code>{e.model ?? "–"}</code></td>
                        <td className="small"><code>{e.prompt_source}</code></td>
                        <td><code>{e.system_sha256.slice(0, 16)}…</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <p className="small muted">Build <CopyId value={v.build_id} label="build ID" /></p>
        </div>
      ) : null}
      {v && v.persona_status === "source_card_only" ? (
        <Notice tone="info" title="No persona file exists for this resident.">
          The source card above is the population row itself. It has never been shown to a model.
        </Notice>
      ) : null}
    </>
  );
}
