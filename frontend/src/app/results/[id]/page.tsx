"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ShareBars } from "@/components/national/charts";
import { useLabels } from "@/components/national/common";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { Badge, RunStateBadge } from "@/components/StatusBadge";
import { toApiError, type ApiError } from "@/lib/api/client";
import { v2, type Aggregate, type ResponsesPage, type ResultTextSummary, type RunDetail, type RunView } from "@/lib/api/v2";
import { fmtInt, fmtUsd } from "@/lib/format";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

const GROUPS: [string, string][] = [["sex", "Sex"], ["age_group", "Age group"], ["province_code", "Province"], ["marital_status", "Marital status"],
  ["education_level", "Education"], ["labour_status", "Labour status"], ["urbanicity", "Settlement type"]];

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const runId = decodeURIComponent(id);
  const router = useRouter();
  const pop = useLinkPop();
  const labels = useLabels();
  const [group, setGroup] = useState("sex");
  const [minGroup, setMinGroup] = useState(10);
  const [page, setPage] = useState(0);
  const [replayError, setReplayError] = useState<ApiError | null>(null);
  const historical = runId.startsWith("imp_");
  const [tick, setTick] = useState(0);
  const detail = useApi(historical ? null : `v2:run:${runId}:${tick}`, (signal) => v2<RunDetail>(`/runs/${runId}`, { signal }));
  const state = detail.data?.run.state;
  const done = state !== undefined && ["completed", "completed_with_errors", "failed", "budget_stopped"].includes(state);
  const agg = useApi(historical || !done ? null : `v2:agg:${runId}:${group}:${minGroup}`, (signal) => v2<Aggregate>(`/runs/${runId}/aggregate`, { query: { group_by: [group], min_group: minGroup }, signal }));
  const responses = useApi(historical || !done ? null : `v2:resp:${runId}:${page}`, (signal) => v2<ResponsesPage>(`/runs/${runId}/responses`, { query: { offset: page * 20, limit: 20 }, signal }));
  const textSummary = useApi(
    historical || !done ? null : `v2:text-summary:${runId}`,
    (signal) => v2<ResultTextSummary>(`/runs/${runId}/text-summary`, { signal })
  );
  const [showFullReport, setShowFullReport] = useState(false);
  const [copiedSummary, setCopiedSummary] = useState(false);
  useEffect(() => { if (historical) router.replace(`/historical/results/${encodeURIComponent(runId)}`); }, [historical, router, runId]);
  useEffect(() => {  // queued or running MatrAIx runs are executed by the local worker; poll until they finish
    if (!state || done) return;
    const timer = setTimeout(() => setTick((t) => t + 1), 2000);
    return () => clearTimeout(timer);
  }, [state, done, tick]);
  if (historical) return null;
  if (detail.error) return <><PageHeader title="Run" /><ErrorState error={detail.error} onRetry={detail.reload} what="run" /></>;
  if (!detail.data) return <><PageHeader title="Run" /><Loading what="run" /></>;
  if (!done) return <><PageHeader title={detail.data.title} /><div className="row"><RunStateBadge state={detail.data.run.state} />
    <span className="small muted">Waiting for the local worker; this page refreshes automatically.</span></div></>;
  const { run, definition, plan, manifest, cohort } = detail.data;
  const isFreeText = definition.task.response_type === "free_text" || definition.task.options.length === 0;
  const optionLabels = Object.fromEntries(definition.task.options.map((o) => [o.id, o.label]));
  const terminal = done;
  return (
    <>
      <PageHeader title={detail.data.title} actions={terminal ? null : <button type="button" className="button small" onClick={detail.reload}>Refresh</button>}>
        Run <code>{run.run_id}</code>{run.kind === "replay" ? <> · replay of <Link href={withPop(`/results/${run.replay_of}`, pop)}>{run.replay_of}</Link></> : null}
      </PageHeader>
      <SyntheticNotice kind="responses" />
      {detail.data.is_stub ? <Notice tone="warn" title="Stub run — pipeline test only.">These answers were produced by the deterministic stub backend, not by a model. They test the pipeline and must not be read as results.</Notice> : null}
      {!detail.data.is_stub && detail.data.is_placeholder ? <Notice tone="warn" title="Simulated agent responses (Zero-cost).">The AI survey agent pipeline ran with simulated persona responses to validate behavior without incurring cloud LLM provider costs.</Notice> : null}
      <div className="row"><RunStateBadge state={run.state} />{run.error_message ? <span className="small muted">{run.error_message}</span> : null}</div>
      <div className="tiles">
        <StatTile label="Active personas" value={fmtInt(run.personas ?? plan.active_personas)} sub={`${fmtInt(plan.eligible_records)} eligible records`} />
        <StatTile label="Completed" value={fmtInt(run.valid_responses)} sub={`of ${fmtInt(run.final_responses)} final responses`} />
        <StatTile label="Failed / invalid" value={fmtInt(run.final_responses !== null && run.valid_responses !== null ? run.final_responses - run.valid_responses : null)}
          sub={Object.entries(run.status_counts ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")} />
        <StatTile label="Calls" value={fmtInt(run.calls_attempted)} sub={`${fmtInt(run.provider_calls)} to a provider`} />
        <StatTile label="Tokens (in / out)" value={`${fmtInt(run.usage?.input_tokens)} / ${fmtInt(run.usage?.output_tokens)}`} sub="unknown = not reported by the backend" />
        <StatTile label="Cost" value={fmtUsd(run.usage?.cost_usd)} sub={plan.cost.basis} />
      </div>
      <dl className="kv card">
        <dt>Backend</dt><dd>{run.backend_label ?? run.backend}</dd>
        <dt>Model</dt><dd>{definition.model.backend} / {definition.model.transport}{definition.model.model ? ` / ${definition.model.model}` : ""} · temperature {definition.model.temperature} · seed {definition.model.seed ?? "none"}</dd>
        <dt>Cohort</dt><dd>{cohort?.name ?? definition.cohort.cohort_id} · sample {definition.cohort.sample_size} ({definition.cohort.sampling_method}, seed {definition.cohort.seed})</dd>
        <dt>Scenario</dt><dd>{definition.scenario.title}{definition.scenario.hypothetical ? " (hypothetical)" : ""}</dd>
        <dt>Task Format</dt><dd>{isFreeText ? "Free-Text (Open-ended textual answers in citizen's own words)" : "Single Choice (Closed options)"}</dd>
        <dt>Task</dt><dd>{definition.task.instruction}</dd>
      </dl>

      {/* EXECUTIVE RESULT TEXT SUMMARY CARD */}
      <section
        className="card stack"
        aria-labelledby="exec-summary-h"
        style={{
          borderLeft: "4px solid var(--accent, #3b82f6)",
          background: "var(--surface-1)",
          padding: "18px 22px",
          gap: 14,
        }}
      >
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <div className="row" style={{ alignItems: "center", gap: 8 }}>
            <h2 id="exec-summary-h" style={{ margin: 0, fontSize: "1.12rem" }}>
              Executive Result Summary
            </h2>
            <Badge tone="info">Simulation Findings</Badge>
          </div>
          <button
            type="button"
            className="button small"
            onClick={() => {
              if (textSummary.data?.summary_markdown) {
                navigator.clipboard.writeText(textSummary.data.summary_markdown);
                setCopiedSummary(true);
                setTimeout(() => setCopiedSummary(false), 2000);
              }
            }}
          >
            {copiedSummary ? "✓ Copied to Clipboard" : "Copy Result Summary"}
          </button>
        </div>

        {textSummary.loading && !textSummary.data ? (
          <p className="small muted">Synthesizing result summary from citizen agent responses…</p>
        ) : textSummary.data ? (
          <>
            <div
              style={{
                fontSize: "1.02rem",
                fontWeight: 500,
                lineHeight: 1.5,
                color: "var(--text-primary)",
                background: "var(--surface-2)",
                padding: "12px 16px",
                borderRadius: "6px",
                border: "1px solid var(--border)",
              }}
            >
              {textSummary.data.headline}
            </div>

            {textSummary.data.key_findings.length > 0 ? (
              <div>
                <strong className="small" style={{ textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-secondary)" }}>
                  Key Behavioral Findings:
                </strong>
                <ul style={{ margin: "6px 0 0 18px", padding: 0, fontSize: "0.9rem", lineHeight: 1.5 }}>
                  {textSummary.data.key_findings.map((finding, idx) => (
                    <li key={idx} style={{ marginBottom: 4 }}>
                      {finding}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {/* Collapsible Full Narrative Report */}
            <div style={{ marginTop: 4 }}>
              <button
                type="button"
                className="button small"
                onClick={() => setShowFullReport((prev) => !prev)}
                style={{ fontSize: "0.78rem" }}
              >
                {showFullReport ? "▲ Hide Full Narrative Report" : "▼ View Full Analytical Report (Markdown)"}
              </button>

              {showFullReport ? (
                <div
                  style={{
                    marginTop: 10,
                    background: "var(--surface-2)",
                    padding: "14px 18px",
                    borderRadius: "6px",
                    border: "1px solid var(--border)",
                  }}
                >
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: "pre-wrap",
                      fontFamily: "monospace",
                      fontSize: "0.82rem",
                      lineHeight: 1.5,
                      maxHeight: "380px",
                      overflowY: "auto",
                      color: "var(--text-primary)",
                    }}
                  >
                    {textSummary.data.summary_markdown}
                  </pre>
                </div>
              ) : null}
            </div>
          </>
        ) : null}
      </section>

      {isFreeText ? (
        <section className="card stack" aria-labelledby="free-text-h">
          <div className="card-head">
            <h2 id="free-text-h">Citizen Free-Text Responses (Qualitative Findings)</h2>
            <span className="small muted">{fmtInt(responses.data?.total ?? 0)} recorded text responses</span>
          </div>
          <p className="small muted" style={{ margin: "0 0 10px 0" }}>
            Below are open-ended answers and rationales provided by synthetic citizen personas in their own words.
          </p>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
              gap: 14,
            }}
          >
            {responses.data?.items
              .filter((r) => r.choice || r.raw_response || r.rationale)
              .map((r) => (
                <div
                  key={r.request_key}
                  className="card"
                  style={{
                    background: "var(--surface-2)",
                    padding: 14,
                    borderRadius: 8,
                    borderLeft: "4px solid var(--accent, #3b82f6)",
                  }}
                >
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <Link href={withPop(`/personas/${r.synthetic_id}`, pop)}>
                      <code>{r.synthetic_id}</code>
                    </Link>
                    <span className="status-pill">{r.status}</span>
                  </div>
                  {(() => {
                    const quoteText =
                      r.choice && r.choice !== "open_response"
                        ? r.choice
                        : (r.rationale || r.raw_response || r.choice || "");
                    const showReasoning = r.rationale && r.rationale !== quoteText && r.choice !== "open_response";
                    return (
                      <>
                        <blockquote
                          style={{
                            margin: "8px 0",
                            fontSize: "0.92rem",
                            lineHeight: 1.45,
                            fontStyle: "italic",
                            color: "var(--text-primary)",
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          "{quoteText}"
                        </blockquote>
                        {showReasoning ? (
                          <p className="small muted" style={{ margin: "8px 0 0 0" }}>
                            <strong>Reasoning:</strong> {r.rationale}
                          </p>
                        ) : null}
                      </>
                    );
                  })()}
                </div>
              ))}
          </div>
        </section>
      ) : (
        <section className="card stack" aria-labelledby="dist-h">
          <h2 id="dist-h">Response distribution (weighted)</h2>
          {agg.error ? <ErrorState error={agg.error} /> : null}
          {agg.data ? (
            <>
              {agg.data.overall.responses === 0 ? <p className="muted">No valid responses.</p> :
                <ShareBars options={agg.data.overall.options} labels={optionLabels} caption="Overall response distribution" />}
              <p className="small muted">{fmtInt(agg.data.overall.responses)} valid responses from {fmtInt(agg.data.overall.personas)} personas · Kish effective n {agg.data.overall.effective_n.toFixed(1)}. {agg.data.weighting}</p>
              <p className="small">{agg.data.inference_note}</p>
            </>
          ) : <Loading what="aggregates" />}
        </section>
      )}

      <section className="card stack" aria-labelledby="sub-h">
        <div className="card-head"><h2 id="sub-h">Subgroup comparison</h2>
          <div className="row">
            <div className="field"><label htmlFor="grp">Group by</label><select id="grp" value={group} onChange={(e) => setGroup(e.target.value)}>{GROUPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
            <div className="field"><label htmlFor="ming">Minimum personas per group</label><input id="ming" type="number" min={1} value={minGroup} onChange={(e) => setMinGroup(Math.max(1, Number(e.target.value)))} /></div>
          </div></div>
        {agg.data?.by[group] ? (
          <>
            {agg.data.by[group].groups.map((g) => (
              <div key={g.value} className="stack" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
                <strong>{group === "province_code" ? g.value : labels(group, g.value)} <span className="small muted">· {g.personas} personas</span></strong>
                {g.suppressed ? <span className="small muted">{g.reason}</span> : <ShareBars options={g.options} labels={optionLabels} caption={`Responses for ${g.value}`} />}
              </div>
            ))}
            {agg.data.by[group].comparisons.length ? <ul className="small">{agg.data.by[group].comparisons.map((c) => <li key={c}>{c}</li>)}</ul>
              : <p className="small muted">No subgroup difference whose intervals do not overlap. Differences between small groups are not reported as findings.</p>}
          </>
        ) : null}
      </section>

      <section className="card" aria-labelledby="resp-h">
        <h2 id="resp-h">Structured responses (final attempt per persona)</h2>
        {responses.data ? (
          <>
            <div className="table-wrap"><table><caption>{fmtInt(responses.data.total)} final responses</caption>
              <thead><tr><th>Synthetic ID</th><th>Status</th><th>{isFreeText ? "Free-Text Answer" : "Choice"}</th><th>Rationale</th><th className="num">Attempt</th><th>Prompt source</th></tr></thead>
              <tbody>{responses.data.items.map((r) => (
                <tr key={r.request_key}><th><Link href={withPop(`/personas/${r.synthetic_id}`, pop)}><code>{r.synthetic_id}</code></Link></th>
                  <td className="status-pill">{r.status}</td>
                  <td>
                    {isFreeText ? (
                      <div style={{ maxWidth: 440, whiteSpace: "pre-wrap", fontWeight: 500 }}>
                        {r.choice ? `"${r.choice}"` : <span className="muted">{r.error ?? "–"}</span>}
                      </div>
                    ) : (
                      <>
                        {r.choice ? optionLabels[r.choice] ?? r.choice : <span className="muted">{r.error}</span>}
                        {r.other_text ? ` — ${r.other_text}` : ""}
                      </>
                    )}
                  </td>
                  <td className="small">{r.rationale ?? "–"}</td><td className="num">{r.attempt}</td><td className="small">{r.prompt_source.replaceAll("_", " ")}</td></tr>))}</tbody></table></div>
            <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
              <button type="button" className="button small" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
              <button type="button" className="button small" disabled={(page + 1) * 20 >= responses.data.total} onClick={() => setPage((p) => p + 1)}>Next</button>
            </div>
          </>
        ) : <Loading what="responses" />}
      </section>

      <section className="card stack" aria-labelledby="repro-h">
        <h2 id="repro-h">Reproducibility and limitations</h2>
        <dl className="kv">
          <dt>Population</dt><dd><code>{manifest?.population?.population_id ?? plan.population_id}</code> · seed {manifest?.population?.seed ?? "?"} · {manifest?.population?.generator_version} · reference year {manifest?.population?.reference_year}</dd>
          <dt>Source years</dt><dd>{manifest?.reference_years ? Object.entries(manifest.reference_years.source_years).map(([p, ys]) => `${p}: ${Object.entries(ys).map(([f, y]) => `${f} ${y}`).join(", ")}`).join(" · ") : "–"}</dd>
          <dt>Templates</dt><dd>persona {plan.persona_template_version} · prompt {plan.prompt_template_version} · visible fields {plan.visible_fields_policy.join(", ")}</dd>
          <dt>Plan hash</dt><dd><code>{plan.plan_hash}</code></dd>
          <dt>Code version</dt><dd>{manifest?.code_version?.commit ? <code>{manifest.code_version.commit.slice(0, 12)}</code> : "unknown"} {manifest?.code_version?.note}</dd>
          <dt>Reproduce</dt><dd>{String(manifest?.reproduction ?? "")}</dd>
        </dl>
        {plan.warnings.length ? <ul className="small">{plan.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : null}
        {terminal && run.kind === "execute" && (run.state === "completed" || run.state === "completed_with_errors") ? (
          <div className="row"><button type="button" className="button small" onClick={async () => {
            setReplayError(null);
            try { const out = await v2<{ run: RunView }>(`/runs/${runId}/replay`, { body: { idempotency_key: `replay-${runId}` } }); router.push(withPop(`/results/${out.run.run_id}`, pop)); }
            catch (e) { setReplayError(toApiError(e)); }
          }}>Replay from cache (exact, no calls)</button></div>
        ) : null}
        {replayError ? <ErrorState error={replayError} /> : null}
        <p className="small muted">Source-fit validation of the population does not show that these responses resemble human behaviour; behavioural validation is a separate question.</p>
        <Badge tone="neutral">{detail.data.label}</Badge>
      </section>
    </>
  );
}
