"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { AnswerCell } from "@/components/AnswerCell";
import { SafeMarkdown } from "@/components/Markdown";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { KeyValues, StatTile } from "@/components/StatTile";
import { Badge, CheckBadge, OriginBadge, RunStateBadge, TrialStateBadge } from "@/components/StatusBadge";
import { UsageTable } from "@/components/UsageTable";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { fmtInt, fmtUsd, fmtValue } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { apiPath, withBuild } from "@/lib/urls";

function ArtifactRow({ artifact }: { artifact: Schemas["Artifact"] }) {
  const [preview, setPreview] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const href = apiPath(`/artifacts/${artifact.artifact_id}`);
  const isMarkdown = artifact.media_type.startsWith("text/markdown");
  return (
    <tr>
      <th scope="row"><code>{artifact.relpath}</code>{artifact.caveat ? <div className="small muted">{artifact.caveat}</div> : null}
        {preview !== null ? <div className="card" style={{ marginTop: 8 }}><SafeMarkdown text={preview} /></div> : null}
        {failed ? <div className="small">Could not load the preview.</div> : null}
      </th>
      <td>{artifact.kind === "report" ? <Badge tone="warn" glyph="!">Descriptive report</Badge> : artifact.kind}</td>
      <td className="num">{fmtInt(artifact.size)} B</td>
      <td>
        <div className="row">
          <a className="button small" href={`${href}?download=true`} download>Download</a>
          {isMarkdown ? (
            <button type="button" className="button small" onClick={async () => {
              if (preview !== null) { setPreview(null); return; }
              try {
                const res = await fetch(href);
                if (!res.ok) throw new Error(String(res.status));
                setPreview(await res.text());
              } catch {
                setFailed(true);
              }
            }}>{preview !== null ? "Hide preview" : "Preview"}</button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function EventsPanel({ experimentId, jobId }: { experimentId: string; jobId: string | null }) {
  const [offset, setOffset] = useState(0);
  const events = useApi(`events:${experimentId}:${jobId}:${offset}`, (signal) =>
    unwrap(api.GET("/api/v1/experiments/{experiment_id}/events", { params: { path: { experiment_id: experimentId }, query: { offset, limit: 20, job_id: jobId } }, signal })));
  return (
    <details>
      <summary>Runtime events{events.data ? ` (${events.data.total})` : ""}</summary>
      <div className="details-body">
        <p className="small muted">{events.data?.note}</p>
        {events.error ? <ErrorState error={events.error} onRetry={events.reload} /> : null}
        {events.data?.items.map((e) => (
          <details key={`${e.trial_label}:${e.index}`}>
            <summary>Trial {e.trial_label} · #{e.index} · {e.type ?? "(untyped)"}{e.phase ? ` · ${e.phase}` : ""}</summary>
            <div className="details-body"><pre className="prompt">{JSON.stringify(e.content, null, 2)}</pre></div>
          </details>
        ))}
        {events.data ? (
          <div className="row">
            <button type="button" className="button small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button>
            <span className="small">{events.data.total ? `${offset + 1}–${Math.min(offset + 20, events.data.total)} of ${events.data.total}` : "No events"}</span>
            <button type="button" className="button small" disabled={offset + 20 >= events.data.total} onClick={() => setOffset(offset + 20)}>Next</button>
          </div>
        ) : null}
      </div>
    </details>
  );
}

export default function ResultDetailPage() {
  const { id: rawId } = useParams<{ id: string }>();
  const id = decodeURIComponent(rawId);
  const params = useSearchParams();
  const jobId = params.get("job");
  const focusTrial = params.get("trial");
  const linkBuild = params.get("build");
  const results = useApi(`results:${id}:${jobId}`, (signal) =>
    unwrap(api.GET("/api/v1/experiments/{experiment_id}/results", { params: { path: { experiment_id: id }, query: { job_id: jobId } }, signal })));
  const trials = useApi(`trials:${id}:${jobId}`, (signal) =>
    unwrap(api.GET("/api/v1/experiments/{experiment_id}/trials", { params: { path: { experiment_id: id }, query: { job_id: jobId } }, signal })));
  const r = results.data;
  const coercions = new Map<string, Schemas["Coercion"]>();
  for (const t of r?.trial_summaries ?? []) for (const c of t.coerced_answers) if (c.question_id) coercions.set(`${t.label}:${c.question_id}`, c);
  const [a, b] = r?.trial_summaries ?? [];
  const exportBase = apiPath(`/experiments/${encodeURIComponent(id)}/export`);
  const jobQuery = jobId ? `&job_id=${encodeURIComponent(jobId)}` : "";

  return (
    <>
      <PageHeader title={r ? `Results: ${r.display_name}` : "Results"}>
        {r ? r.display_state_reason : "Recorded evidence for one run."}
      </PageHeader>
      <SyntheticNotice kind="responses" />
      {results.loading && !r ? <Loading what="results" /> : null}
      {results.error ? <ErrorState error={results.error} onRetry={results.reload} what="results" /> : null}
      {r ? (
        <>
          <div className="row">
            <RunStateBadge state={r.display_state} />
            <OriginBadge origin={r.origin} />
            {r.evidence_kind === "fake" ? <Badge tone="fake" glyph="◇">Fake transport: not model behaviour</Badge> : null}
            {r.evidence_kind === "live" ? <Badge tone="info" glyph="◆">Live provider evidence (recorded)</Badge> : null}
            <span className="small muted"><code>{r.experiment_id}</code></span>
          </div>
          <nav className="reference-tabs" aria-label="Result sections"><a href="#result-overview">Overview</a><a href="#cmp-h">Individual responses</a><a href="#usage-h">Usage &amp; cost</a><a href="#checks-h">Methodology</a><a href="#files-h">Export</a></nav>
          <div className="result-overview" id="result-overview">
            <StatTile label="Recorded results" value={r.trial_summaries.filter(t=>t.answers !== null).length} sub="Trials with saved answers"/>
            <StatTile label="Total personas" value={r.trial_summaries.length} sub="Recorded in this experiment"/>
            <StatTile label="Different answer values" value={r.differing_values_recomputed ?? "—"} sub={`${r.comparison_rows.length} questions compared`}/>
            <StatTile label="Estimated cost (USD)" value={r.usage?.cost_usd == null ? "Unknown" : fmtUsd(r.usage.cost_usd)} sub="Provider-billed cost not recorded"/>
          </div>
          <Notice tone="info" title="How to read this.">{r.inference_note}</Notice>
          {r.warnings.length ? <Notice tone="warn" title="Evidence warnings:"><ul>{r.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Notice> : null}

          <div className="grid-2">
            <section className="card" aria-labelledby="facts-h">
              <h2 id="facts-h">Run facts</h2>
              <KeyValues items={[
                ["Model", <code key="m">{r.model ?? "unknown"}</code>],
                ["Temperature", r.temperature === null ? "unknown" : String(r.temperature)],
                ["Task", r.task ? <code key="t">{r.task}</code> : "unknown"],
                ["Planned calls", r.planned_calls === null ? "unknown" : String(r.planned_calls)],
                ["Recorded calls", r.recorded_calls === null ? (r.provider_calls_recorded !== null ? `${r.provider_calls_recorded} provider calls (smoke report)` : "not recorded") : String(r.recorded_calls)],
                ["Automatic retries", r.automatic_retries === null ? "not recorded" : String(r.automatic_retries)],
                ["Output-token cap", r.max_output_tokens_per_call === null ? "none recorded" : fmtInt(r.max_output_tokens_per_call)],
                ["Runtime", r.runtime_seconds === null ? "not recorded" : `${r.runtime_seconds.toFixed(2)} s`],
                ["Credential flag in the old preflight", r.historical_credentials_present === null ? "not recorded" : `${r.historical_credentials_present}. ${r.historical_credentials_note}`],
              ]} />
            </section>
            <section className="card stack" aria-labelledby="usage-h">
              <h2 id="usage-h">Usage and cost</h2>
              <UsageTable caption="Null values are unknown, not zero" rows={[
                ...r.trial_summaries.map((t) => ({ label: `Trial ${t.label}`, usage: t.usage })),
                ...(r.usage ? [{ label: "Run total (comparison file)", usage: r.usage }] : []),
              ]} />
              <p className="small muted">Costs marked estimated come from a local price table in the external framework. No provider-billed amount is recorded.</p>
              {r.budget_file ? <p className="small muted">Budget file: spent {fmtUsd(r.budget_file.spent_usd)}, cap {r.budget_file.max_cost_usd === null ? "none" : fmtUsd(r.budget_file.max_cost_usd)}. {r.budget_file.note}</p> : null}
            </section>
          </div>

          {r.comparison_rows.length ? (
            <section className="card stack" aria-labelledby="cmp-h">
              <div className="card-head">
                <h2 id="cmp-h">Answers side by side</h2>
                <span className="small">
                  {r.differing_values_recomputed} of {r.comparison_rows.length} recorded values differ
                  {r.differing_values_recorded !== null ? ` (comparison file: ${r.differing_values_recorded})` : ""}
                </span>
              </div>
              <div className="table-wrap">
                <table>
                  <caption>Persona A {a?.persona_id ?? ""} versus persona B {b?.persona_id ?? ""}; one response each</caption>
                  <thead><tr><th scope="col">Question</th><th scope="col">Persona A</th><th scope="col">Persona B</th><th scope="col">Values differ</th></tr></thead>
                  <tbody>
                    {r.comparison_rows.map((row) => (
                      <tr key={row.question_id}>
                        <th scope="row">{row.prompt ?? row.question_id}<div className="small muted"><code>{row.question_id}</code>{row.question_type ? ` · ${row.question_type}` : ""}</div></th>
                        <td><AnswerCell answer={row.answer_a} coercion={a ? coercions.get(`${a.label}:${row.question_id}`) : undefined} /></td>
                        <td><AnswerCell answer={row.answer_b} coercion={b ? coercions.get(`${b.label}:${row.question_id}`) : undefined} /></td>
                        <td>{row.value_differs === null ? "–" : row.value_differs ? "Yes" : "No"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="small muted">The two personas differ in age band and marital status. Differences describe these two recorded responses only.</p>
            </section>
          ) : (
            <section className="card stack" aria-labelledby="ans-h">
              <h2 id="ans-h">Recorded answers</h2>
              {r.trial_summaries.every((t) => !t.answers) ? <p className="muted">No trial in this folder has a saved result.</p> : null}
              {r.trial_summaries.filter((t) => t.answers).map((t) => (
                <div className="table-wrap" key={t.label}>
                  <table>
                    <caption>Trial {t.label} · {t.persona_id ?? "unknown persona"}</caption>
                    <thead><tr><th scope="col">Question</th><th scope="col">Answer</th></tr></thead>
                    <tbody>
                      {t.answers!.map((ans) => (
                        <tr key={ans.question_id}><th scope="row"><code>{ans.question_id}</code></th><td><AnswerCell answer={ans} coercion={coercions.get(`${t.label}:${ans.question_id}`)} /></td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </section>
          )}

          <section className="card stack" aria-labelledby="trials-h">
            <h2 id="trials-h">Trials</h2>
            {trials.error ? <ErrorState error={trials.error} onRetry={trials.reload} /> : null}
            {trials.data?.trials.map((t) => (
              <details key={t.label} open={focusTrial === t.label}>
                <summary>Trial {t.label} · {t.persona_id ?? "unknown persona"} · {t.answer_count ?? 0} answers</summary>
                <div className="details-body">
                  <div className="row"><TrialStateBadge state={t.state} /><span className="small muted">Raw boundary status: <code>{t.boundary_status_raw ?? "none"}</code></span></div>
                  {t.persona_id ? <Link href={withBuild("/historical/personas", linkBuild, { record: t.persona_id })}>Open {t.persona_id} in the Persona Explorer</Link> : null}
                  {t.persona_snapshot && !t.persona_snapshot.parse_error ? (
                    <div className="table-wrap">
                      <table>
                        <caption>Persona snapshot saved with this trial (authoritative for this run) · SHA-256 <code>{t.persona_snapshot.sha256.slice(0, 16)}…</code>
                          {t.preflight_persona_sha256 ? (t.preflight_persona_sha256 === t.persona_snapshot.sha256 ? " · matches the preflight hash" : " · differs from the preflight hash") : ""}</caption>
                        <thead><tr><th scope="col">Prompt-visible dimension</th><th scope="col">Value</th></tr></thead>
                        <tbody>{Object.entries(t.persona_snapshot.dimensions).map(([k, v]) => <tr key={k}><th scope="row"><code>{k}</code></th><td>{v}</td></tr>)}</tbody>
                      </table>
                    </div>
                  ) : <p className="muted small">No persona snapshot saved in this trial folder.</p>}
                  {t.prompts ? (
                    <>
                      <p className="small muted">Prompts as recorded in <code>{t.prompts.source}</code>; not re-rendered.</p>
                      <details><summary>Exact system prompt</summary><div className="details-body"><pre className="prompt">{t.prompts.system}</pre></div></details>
                      <details><summary>Exact task prompt</summary><div className="details-body"><pre className="prompt">{t.prompts.user}</pre></div></details>
                    </>
                  ) : <p className="muted small">No prompt evidence recorded.</p>}
                  <p className="small muted">Events: {t.events_summary.count} ({Object.entries(t.events_summary.types).map(([k, v]) => `${k} ${v}`).join(", ") || "none"}). {t.events_summary.note}</p>
                </div>
              </details>
            ))}
          </section>

          <section className="card stack" aria-labelledby="checks-h">
            <h2 id="checks-h">Consistency checks</h2>
            {r.consistency_checks.length === 0 ? <p className="muted">No cross-file checks apply to this evidence.</p> : (
              <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {r.consistency_checks.map((c) => <li key={c.name} className="row"><CheckBadge passed={c.passed} /><code>{c.name}</code><span className="small">{c.detail}</span></li>)}
              </ul>
            )}
            <ul className="small muted">{r.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </section>

          <section className="card stack" aria-labelledby="files-h">
            <div className="card-head">
              <h2 id="files-h">Artifacts and export</h2>
              <div className="row">
                <a className="button small" href={`${exportBase}?format=csv${jobQuery}`} download>Export CSV</a>
                <a className="button small" href={`${exportBase}?format=json${jobQuery}`} download>Export JSON</a>
              </div>
            </div>
            <p className="small muted">Exports carry the synthetic-data label, provenance hashes and a column schema. Null stays null.</p>
            <div className="table-wrap">
              <table>
                <caption>Files in the run folder, served by server-owned IDs</caption>
                <thead><tr><th scope="col">File</th><th scope="col">Kind</th><th scope="col" className="num">Size</th><th scope="col">Actions</th></tr></thead>
                <tbody>{r.artifacts.map((art) => <ArtifactRow key={art.artifact_id} artifact={art} />)}</tbody>
              </table>
            </div>
            <EventsPanel experimentId={id} jobId={jobId} />
            <details>
              <summary>Raw statuses and file evidence</summary>
              <div className="details-body">
                <KeyValues items={[
                  ["preflight.status", fmtValue(r.raw_statuses.preflight_status)],
                  ["comparison.status", fmtValue(r.raw_statuses.comparison_status)],
                  ["smoke_report.ok", fmtValue(r.raw_statuses.smoke_report_ok)],
                  ["Trial boundary statuses", JSON.stringify(r.raw_statuses.trial_boundaries)],
                  ["Changed since first import", r.evidence_drift && r.evidence_drift.length ? r.evidence_drift.join(", ") : "nothing"],
                ]} />
                <div className="table-wrap">
                  <table>
                    <caption>Files read to build this view</caption>
                    <thead><tr><th scope="col">File</th><th scope="col">Status</th><th scope="col">SHA-256</th></tr></thead>
                    <tbody>{r.files.map((f) => <tr key={f.relpath}><td><code>{f.relpath}</code></td><td>{f.status}{f.error ? ` (${f.error})` : ""}</td><td><code>{f.sha256 ? `${f.sha256.slice(0, 16)}…` : "–"}</code></td></tr>)}</tbody>
                  </table>
                </div>
              </div>
            </details>
          </section>
        </>
      ) : null}
    </>
  );
}
