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
import { v2, type Aggregate, type ResponsesPage, type RunDetail, type RunView } from "@/lib/api/v2";
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
  const optionLabels = Object.fromEntries(definition.task.options.map((o) => [o.id, o.label]));
  const terminal = done;
  return (
    <>
      <PageHeader title={detail.data.title} actions={terminal ? null : <button type="button" className="button small" onClick={detail.reload}>Refresh</button>}>
        Run <code>{run.run_id}</code>{run.kind === "replay" ? <> · replay of <Link href={withPop(`/results/${run.replay_of}`, pop)}>{run.replay_of}</Link></> : null}
      </PageHeader>
      <SyntheticNotice kind="responses" />
      {detail.data.is_stub ? <Notice tone="warn" title="Stub run — pipeline test only.">These answers were produced by the deterministic stub backend, not by a model. They test the pipeline and must not be read as results.</Notice> : null}
      {!detail.data.is_stub && detail.data.is_placeholder ? <Notice tone="warn" title="MatrAIx fake transport.">The real MatrAIx survey agent ran, but its zero-cost smoke client returned schema-valid placeholder answers. Not persona behaviour.</Notice> : null}
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
        <dt>Task</dt><dd>{definition.task.instruction}</dd>
      </dl>

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
              <thead><tr><th>Synthetic ID</th><th>Status</th><th>Choice</th><th>Rationale</th><th className="num">Attempt</th><th>Prompt source</th></tr></thead>
              <tbody>{responses.data.items.map((r) => (
                <tr key={r.request_key}><th><Link href={withPop(`/personas/${r.synthetic_id}`, pop)}><code>{r.synthetic_id}</code></Link></th>
                  <td className="status-pill">{r.status}</td><td>{r.choice ? optionLabels[r.choice] ?? r.choice : <span className="muted">{r.error}</span>}{r.other_text ? ` — ${r.other_text}` : ""}</td>
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
