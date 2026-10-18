"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { PopulationGate, useCapabilities } from "@/components/national/common";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";
import { toApiError, type ApiError } from "@/lib/api/client";
import { v2, type Cohort, type Environment, type Experiment, type ExperimentDefinition, type Geography, type Plan, type RunView } from "@/lib/api/v2";
import { fmtInt, fmtUsd } from "@/lib/format";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

const STEPS = ["Scenario", "Task", "Environment", "Cohort", "Model", "Review"] as const;

function blank(cohortId: string): ExperimentDefinition {
  return {
    title: "",
    scenario: { title: "", description: "", parameters: [], hypothetical: true, source_note: null },
    task: { instruction: "", options: [{ id: "option_a", label: "" }, { id: "option_b", label: "" }], allow_other_text: false, ask_rationale: true, adult_only: true },
    environment: { province_code: null, context_indicators: [] },
    cohort: { cohort_id: cohortId, sample_size: 20, sampling_method: "weighted", seed: 7, strata_field: null },
    model: { backend: "stub", transport: "fake", model: null, temperature: 0, seed: null, max_output_tokens: 512 },
    execution: { repetitions: 1, max_attempts: 1, max_calls: 20, max_cost_usd: null },
    persona: { visible_fields: null },
  };
}

function Builder({ populationId }: { populationId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const pop = useLinkPop();
  const caps = useCapabilities();
  const cohorts = useApi("v2:cohorts", (signal) => v2<{ items: Cohort[] }>("/cohorts", { signal }));
  const geo = useApi(`v2:geo:${populationId}`, (signal) => v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }));
  const [step, setStep] = useState(0);
  const [d, setD] = useState<ExperimentDefinition>(() => blank(params.get("cohort") ?? ""));
  const [plan, setPlan] = useState<Plan | null>(null);
  const [exp, setExp] = useState<Experiment | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const envCode = d.environment.province_code ?? geo.data?.provinces.find((p) => p.records > 0)?.province_code ?? null;
  const env = useApi(envCode ? `v2:env:${envCode}` : null, (signal) => v2<Environment>(`/environments/${envCode}`, { signal }));
  const valid = cohorts.data?.items.filter((c) => c.status === "valid" && c.population_id === populationId) ?? [];
  useEffect(() => { setPlan(null); setExp(null); setConfirm(false); }, [d]);

  const patch = <K extends keyof ExperimentDefinition>(key: K, value: Partial<ExperimentDefinition[K]>) =>
    setD((cur) => ({ ...cur, [key]: { ...(cur[key] as object), ...(value as object) } }));

  const loadExample = async () => {
    const cohortId = d.cohort.cohort_id || valid.find((c) => !c.minors)?.cohort_id || valid[0]?.cohort_id || "";
    const ex = await v2<ExperimentDefinition>("/examples/fare-experiment", { query: { cohort_id: cohortId } });
    setD({ ...ex, persona: { visible_fields: null } });
  };

  const review = async () => {
    setBusy(true); setError(null);
    try {
      const created = await v2<Experiment>("/experiments", { body: d });
      setExp(created);
      setPlan(await v2<Plan>(`/experiments/${created.experiment_id}/plan`, { method: "POST", body: {} }));
    } catch (e) { setError(toApiError(e)); } finally { setBusy(false); }
  };

  const run = async () => {
    if (!plan || !exp) return;
    setBusy(true); setError(null);
    try {
      const out = await v2<{ run: RunView }>(`/experiments/${exp.experiment_id}/runs`, { body: { plan_hash: plan.plan_hash, idempotency_key: `ui-${plan.plan_hash.slice(0, 24)}`, confirm: true } });
      router.push(withPop(`/results/${out.run.run_id}`, pop));
    } catch (e) { setError(toApiError(e)); setBusy(false); }
  };

  const indicators = env.data ? Object.values(env.data.domains).flat() : [];
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <ol className="builder-steps" aria-label="Experiment design steps">
          {STEPS.map((s, i) => <li key={s}><button type="button" aria-current={i === step ? "step" : undefined} onClick={() => setStep(i)} aria-label={`Step ${i + 1}: ${s}`}><span>{i + 1}</span>{s}</button></li>)}
        </ol>
        <button type="button" className="button small" onClick={loadExample} disabled={!valid.length}>Load example: Ankara fare increase (hypothetical)</button>
      </div>
      {cohorts.data && valid.length === 0 ? <EmptyState title="No cohort for this population.">Save a cohort first on the <Link href={withPop("/cohorts", pop)}>Cohorts</Link> page; experiments always run on a saved cohort.</EmptyState> : null}

      {step === 0 ? (
        <section className="card stack" aria-labelledby="s-h"><h2 id="s-h">Scenario — what is happening?</h2>
          <div className="field"><label htmlFor="exp-title">Experiment title</label><input id="exp-title" type="text" value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })} /></div>
          <div className="field"><label htmlFor="sc-title">Scenario title</label><input id="sc-title" type="text" value={d.scenario.title} onChange={(e) => patch("scenario", { title: e.target.value })} /></div>
          <div className="field"><label htmlFor="sc-desc">Description</label><textarea id="sc-desc" value={d.scenario.description} onChange={(e) => patch("scenario", { description: e.target.value })} /></div>
          <fieldset><legend>Parameters</legend>
            {d.scenario.parameters.map((p, i) => (
              <div className="param-row" key={i} style={{ marginBottom: 6 }}>
                <input aria-label={`Parameter ${i + 1} name`} type="text" value={p.name} onChange={(e) => patch("scenario", { parameters: d.scenario.parameters.map((q, j) => j === i ? { ...q, name: e.target.value } : q) })} />
                <input aria-label={`Parameter ${i + 1} label`} type="text" value={p.label} onChange={(e) => patch("scenario", { parameters: d.scenario.parameters.map((q, j) => j === i ? { ...q, label: e.target.value } : q) })} />
                <input aria-label={`Parameter ${i + 1} value`} type="text" value={String(p.value)} onChange={(e) => patch("scenario", { parameters: d.scenario.parameters.map((q, j) => j === i ? { ...q, value: e.target.value !== "" && !isNaN(Number(e.target.value)) ? Number(e.target.value) : e.target.value } : q) })} />
                <input aria-label={`Parameter ${i + 1} unit`} type="text" value={p.unit ?? ""} onChange={(e) => patch("scenario", { parameters: d.scenario.parameters.map((q, j) => j === i ? { ...q, unit: e.target.value || null } : q) })} />
                <button type="button" className="button small" onClick={() => patch("scenario", { parameters: d.scenario.parameters.filter((_, j) => j !== i) })}>Remove</button>
              </div>))}
            <button type="button" className="button small" onClick={() => patch("scenario", { parameters: [...d.scenario.parameters, { name: `param_${d.scenario.parameters.length + 1}`, label: "", value: 0, unit: null }] })}>Add parameter</button>
          </fieldset>
          <label className="check"><input type="checkbox" checked={d.scenario.hypothetical} onChange={(e) => patch("scenario", { hypothetical: e.target.checked })} />Hypothetical scenario (values are set for the experiment, not current facts)</label>
          {!d.scenario.hypothetical ? <div className="field"><label htmlFor="sc-src">Source for the scenario values (required)</label><input id="sc-src" type="text" value={d.scenario.source_note ?? ""} onChange={(e) => patch("scenario", { source_note: e.target.value })} /></div> : null}
        </section>
      ) : null}

      {step === 1 ? (
        <section className="card stack" aria-labelledby="t-h"><h2 id="t-h">Task — what must the agent do?</h2>
          <div className="field"><label htmlFor="t-ins">Question / instruction</label><textarea id="t-ins" value={d.task.instruction} onChange={(e) => patch("task", { instruction: e.target.value })} /></div>
          <p className="small muted">Response type: single choice among controlled options (structured JSON output, validated against these ids).</p>
          <fieldset><legend>Options</legend>
            {d.task.options.map((o, i) => (
              <div className="option-row" key={i} style={{ marginBottom: 6 }}>
                <input aria-label={`Option ${i + 1} id`} type="text" value={o.id} onChange={(e) => patch("task", { options: d.task.options.map((q, j) => j === i ? { ...q, id: e.target.value } : q) })} />
                <input aria-label={`Option ${i + 1} label`} type="text" value={o.label} onChange={(e) => patch("task", { options: d.task.options.map((q, j) => j === i ? { ...q, label: e.target.value } : q) })} />
                <button type="button" className="button small" disabled={d.task.options.length <= 2} onClick={() => patch("task", { options: d.task.options.filter((_, j) => j !== i) })}>Remove</button>
              </div>))}
            <button type="button" className="button small" disabled={d.task.options.length >= 12} onClick={() => patch("task", { options: [...d.task.options, { id: `option_${d.task.options.length + 1}`, label: "" }] })}>Add option</button>
          </fieldset>
          <label className="check"><input type="checkbox" checked={d.task.allow_other_text} onChange={(e) => patch("task", { allow_other_text: e.target.checked })} />Allow free text for an option with id <code>other</code></label>
          <label className="check"><input type="checkbox" checked={d.task.ask_rationale} onChange={(e) => patch("task", { ask_rationale: e.target.checked })} />Ask for a short rationale</label>
          <label className="check"><input type="checkbox" checked={d.task.adult_only} onChange={(e) => patch("task", { adult_only: e.target.checked })} />Adult-only task (minors in the sample block execution)</label>
        </section>
      ) : null}

      {step === 2 ? (
        <section className="card stack" aria-labelledby="e-h"><h2 id="e-h">Environment — where does it happen?</h2>
          <div className="field"><label htmlFor="e-prov">Context province</label>
            <select id="e-prov" value={d.environment.province_code ?? ""} onChange={(e) => patch("environment", { province_code: e.target.value || null, context_indicators: [] })}>
              <option value="">Each persona's own province</option>
              {geo.data?.provinces.filter((p) => p.has_population_controls || p.context_indicators > 0).map((p) => <option key={p.province_code} value={p.province_code}>{p.province_name}</option>)}
            </select></div>
          <fieldset><legend>Context dimensions shown to the agent{envCode ? ` (indicators of ${env.data?.province.province_name ?? envCode})` : ""}</legend>
            {env.loading && !env.data ? <Loading what="environment" /> : null}
            {env.data && indicators.length === 0 ? <p className="small muted">No context indicators are loaded for this province.</p> : null}
            <div className="checks">{indicators.filter((i) => i.value !== null).map((i) => (
              <label className="check" key={i.indicator_id}><input type="checkbox" checked={d.environment.context_indicators.includes(i.indicator_id)}
                onChange={(e) => patch("environment", { context_indicators: e.target.checked ? [...d.environment.context_indicators, i.indicator_id] : d.environment.context_indicators.filter((x) => x !== i.indicator_id) })} />
                {i.label} ({i.source_year})</label>))}</div>
            <p className="field-hint">Each indicator is shown with its own source year. Missing indicators are omitted, never invented.</p>
          </fieldset>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="card stack" aria-labelledby="c-h"><h2 id="c-h">Cohort — who is asked?</h2>
          <div className="field"><label htmlFor="c-pick">Saved cohort</label>
            <select id="c-pick" value={d.cohort.cohort_id} onChange={(e) => patch("cohort", { cohort_id: e.target.value })}>
              <option value="">Choose a cohort…</option>
              {valid.map((c) => <option key={c.cohort_id} value={c.cohort_id}>{c.name} · {fmtInt(c.eligible_records)} eligible{c.minors ? ` · ${fmtInt(c.minors)} minors` : ""}</option>)}
            </select></div>
          <div className="form-grid">
            <div className="field"><label htmlFor="c-size">Sample size (active personas)</label><input id="c-size" type="number" min={1} max={caps.data?.max_agents_per_run ?? 200} value={d.cohort.sample_size} onChange={(e) => patch("cohort", { sample_size: Number(e.target.value) })} />
              <span className="field-hint">Limit per run: {caps.data?.max_agents_per_run ?? "…"}. The population size never sets the number of agents.</span></div>
            <div className="field"><label htmlFor="c-meth">Sampling</label><select id="c-meth" value={d.cohort.sampling_method} onChange={(e) => patch("cohort", { sampling_method: e.target.value, strata_field: e.target.value === "stratified" ? "province_code" : null })}>
              <option value="weighted">Weighted (∝ population weight)</option><option value="simple_random">Simple random</option><option value="stratified">Stratified by province</option></select></div>
            <div className="field"><label htmlFor="c-seed">Sampling seed</label><input id="c-seed" type="number" min={0} value={d.cohort.seed} onChange={(e) => patch("cohort", { seed: Number(e.target.value) })} /></div>
          </div>
        </section>
      ) : null}

      {step === 4 ? (
        <section className="card stack" aria-labelledby="m-h"><h2 id="m-h">Model — what executes it?</h2>
          <div className="form-grid">
            <div className="field"><label htmlFor="m-backend">Backend</label>
              <select id="m-backend" value={`${d.model.backend}:${d.model.transport}`} onChange={(e) => { const [backend, transport] = e.target.value.split(":") as ["stub" | "matraix", "fake" | "live"]; patch("model", { backend, transport }); }}>
                <option value="stub:fake">Stub (offline pipeline test — not a model)</option>
                <option value="matraix:fake" disabled={!caps.data?.backends.matraix_fake.available}>MatrAIx survey agent, fake transport (zero cost){caps.data?.backends.matraix_fake.available ? "" : " — unavailable"}</option>
                <option value="matraix:live">MatrAIx survey agent, live provider (gated)</option>
              </select></div>
            <div className="field"><label htmlFor="m-model">Provider/model</label><input id="m-model" type="text" placeholder="e.g. anthropic/claude-haiku-5-5" value={d.model.model ?? ""} disabled={d.model.transport !== "live"} onChange={(e) => patch("model", { model: e.target.value || null })} /></div>
            <div className="field"><label htmlFor="m-temp">Temperature</label><input id="m-temp" type="number" step="0.1" min={0} max={2} value={d.model.temperature} onChange={(e) => patch("model", { temperature: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="m-reps">Repetitions per persona</label><input id="m-reps" type="number" min={1} max={5} value={d.execution.repetitions} onChange={(e) => patch("execution", { repetitions: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="m-att">Attempts per call (1 = no retry)</label><input id="m-att" type="number" min={1} max={3} value={d.execution.max_attempts} onChange={(e) => patch("execution", { max_attempts: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="m-cap">Call cap (budget guard)</label><input id="m-cap" type="number" min={1} value={d.execution.max_calls} onChange={(e) => patch("execution", { max_calls: Number(e.target.value) })} /></div>
            <div className="field"><label htmlFor="m-cost">Cost cap (USD, optional)</label><input id="m-cost" type="number" min={0} step="0.01" value={d.execution.max_cost_usd ?? ""} onChange={(e) => patch("execution", { max_cost_usd: e.target.value === "" ? null : Number(e.target.value) })} /></div>
          </div>
          {d.model.transport === "live" ? <Notice tone="warn" title="Live execution is gated.">It needs SOCIETYTWIN_ENABLE_LIVE_EXECUTION, a provider key in the API server environment and the MatrAIx runtime. Calls cost money; the review step lists every blocker.</Notice> : null}
        </section>
      ) : null}

      {step === 5 ? (
        <section className="card stack" aria-labelledby="r-h"><h2 id="r-h">Review</h2>
          <dl className="kv">
            <dt>Title</dt><dd>{d.title || <span className="muted">missing</span>}</dd>
            <dt>Scenario</dt><dd>{d.scenario.title || <span className="muted">missing</span>} {d.scenario.hypothetical ? <Badge tone="neutral">hypothetical</Badge> : null}</dd>
            <dt>Task</dt><dd>{d.task.instruction || <span className="muted">missing</span>} · {d.task.options.length} options</dd>
            <dt>Environment</dt><dd>{d.environment.province_code ? geo.data?.provinces.find((p) => p.province_code === d.environment.province_code)?.province_name : "Each persona's own province"} · {d.environment.context_indicators.length} context indicators</dd>
            <dt>Cohort</dt><dd>{valid.find((c) => c.cohort_id === d.cohort.cohort_id)?.name ?? <span className="muted">none selected</span>} · sample {d.cohort.sample_size} ({d.cohort.sampling_method}, seed {d.cohort.seed})</dd>
            <dt>Model</dt><dd>{d.model.backend} / {d.model.transport}{d.model.model ? ` / ${d.model.model}` : ""} · temperature {d.model.temperature}</dd>
          </dl>
          <div><button type="button" className="button primary" disabled={busy} onClick={review}>{busy && !plan ? "Saving and planning…" : "Save and review plan"}</button></div>
          {error ? <ErrorState error={error} /> : null}
          {plan ? (
            <div className="stack">
              <div className="tiles">
                <div className="tile"><div className="tile-label">Eligible records</div><div className="tile-value">{fmtInt(plan.eligible_records)}</div><div className="tile-sub">{fmtInt(plan.eligible_weighted_population)} represented</div></div>
                <div className="tile"><div className="tile-label">Selected / active personas</div><div className="tile-value">{fmtInt(plan.active_personas)}</div><div className="tile-sub">{plan.minors_in_sample} minors</div></div>
                <div className="tile"><div className="tile-label">Estimated calls</div><div className="tile-value">{fmtInt(plan.calls.planned)}</div><div className="tile-sub">max {plan.calls.maximum_with_retries} with retries · cap {plan.calls.cap} · provider {plan.calls.provider_calls_expected}</div></div>
                <div className="tile"><div className="tile-label">Estimated cost</div><div className="tile-value">{fmtUsd(plan.cost.estimate_usd)}</div><div className="tile-sub">{plan.cost.basis}</div></div>
              </div>
              <p className="small muted">≈{fmtInt(plan.tokens.input_estimate_per_repetition)} input tokens per repetition ({plan.tokens.method}); output capped at {plan.tokens.max_output_tokens_per_call} per call.</p>
              {plan.blockers.length ? <div className="notice crit" role="alert"><strong>Execution is blocked:</strong><ul>{plan.blockers.map((b) => <li key={b.code}><code>{b.code}</code>: {b.message}</li>)}</ul></div> : null}
              {plan.warnings.length ? <div className="notice warn"><strong>Warnings and missing data</strong><ul>{plan.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div> : null}
              {plan.example_prompt ? <details><summary>Exact prompt for {plan.example_prompt.synthetic_id}</summary><div className="details-body">
                <h3>System (persona card)</h3><pre className="prompt">{plan.example_prompt.system}</pre><h3>User (environment, scenario, task)</h3><pre className="prompt">{plan.example_prompt.user}</pre></div></details> : null}
              <label className="check"><input type="checkbox" checked={confirm} disabled={!plan.executable} onChange={(e) => setConfirm(e.target.checked)} />
                I reviewed this plan: {plan.calls.planned} calls for {plan.active_personas} personas{plan.calls.provider_calls_expected ? `, ${plan.calls.provider_calls_expected} of them to a paid provider` : ", no provider calls"}.</label>
              <div><button type="button" className="button primary" disabled={!plan.executable || !confirm || busy} onClick={run}>Run experiment</button></div>
            </div>
          ) : null}
        </section>
      ) : null}

      <div className="wizard-actions">
        <button type="button" className="button" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>Back</button>
        <button type="button" className="button" disabled={step === STEPS.length - 1} onClick={() => setStep((s) => s + 1)}>Next</button>
      </div>
    </div>
  );
}

export default function NewExperimentPage() {
  return (
    <>
      <PageHeader title="New Experiment">Controlled persona-conditioned AI experiment: scenario, task, environment, cohort and model are set separately and reviewed before anything runs.</PageHeader>
      <Notice tone="info">Experiments test the pipeline and explore hypotheses. Their outputs are not predictions of what real residents of Türkiye would do.</Notice>
      <PopulationGate what="the experiment builder">{(id) => <Builder populationId={id} />}</PopulationGate>
    </>
  );
}
