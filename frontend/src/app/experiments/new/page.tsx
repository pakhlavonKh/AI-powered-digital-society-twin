"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import { CopyId } from "@/components/CopyId";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { PreflightView } from "@/components/PreflightView";
import { ErrorState, Loading, UnavailableState } from "@/components/States";
import { KeyValues } from "@/components/StatTile";
import { Badge, RunStateBadge } from "@/components/StatusBadge";
import { api, toApiError, unwrap, type ApiError, type Schemas } from "@/lib/api/client";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

type PersonaSource = "legacy_fixture_pair" | "legacy_fixture_single" | "cohort";
type Mode = "preflight" | "smoke" | "legacy_ab_live";
type Form = {
  name: string; personaSource: PersonaSource; cohortId: string; scenarioKind: "none" | "draft"; scenarioText: string;
  environment: "SURVEY" | "SCENARIO"; mode: Mode; model: string; temperature: string; callsLimit: string;
};

const STEPS = ["Personas", "Scenario, task, environment", "Execution settings", "Save draft", "Preflight review", "Explicit start"];

function Steps({ current, done }: { current: number; done: number }) {
  return (
    <ol className="steps" aria-label="Experiment steps">
      {STEPS.map((s, i) => (
        <li key={s} aria-current={i === current ? "step" : undefined} className={i < done ? "done" : undefined}>
          <span aria-hidden="true">{i < done ? "✓" : i + 1}</span> {s}
        </li>
      ))}
    </ol>
  );
}

function ModeBadge({ mode }: { mode: Schemas["ModeCapability"] | undefined }) {
  if (!mode) return null;
  return mode.available ? <Badge tone="good" glyph="✓">Available here</Badge> : <Badge tone="neutral" glyph="·">Unavailable here</Badge>;
}

export default function NewExperimentPage() {
  const params = useSearchParams();
  const draftId = params.get("draft");
  return (
    <>
      <PageHeader title="New Experiment">
        Define a scenario, task and environment for your synthetic personas.
      </PageHeader>
      <SyntheticNotice kind="responses" />
      {draftId ? <DraftView draftId={draftId} /> : <DraftForm />}
    </>
  );
}

function DraftForm() {
  const router = useRouter();
  const params = useSearchParams();
  const linkBuild = params.get("build");
  const cohortParam = params.get("cohort");
  const caps = useApi("capabilities", (signal) => unwrap(api.GET("/api/v1/capabilities", { signal })));
  const cohorts = useApi("cohorts", (signal) => unwrap(api.GET("/api/v1/cohorts", { signal })));
  const tasks = useApi("tasks", (signal) => unwrap(api.GET("/api/v1/tasks", { signal })));
  const envs = useApi("environments", (signal) => unwrap(api.GET("/api/v1/environments", { signal })));
  const [form, setForm] = useState<Form>({
    name: "", personaSource: cohortParam ? "cohort" : "legacy_fixture_pair", cohortId: cohortParam ?? "", scenarioKind: "none",
    scenarioText: "", environment: "SURVEY", mode: "preflight", model: "", temperature: "0", callsLimit: "0",
  });
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | undefined>();
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));
  const selectedCohort = cohorts.data?.items.find((c) => c.cohort_id === form.cohortId);
  const personaIndex = useApi(selectedCohort ? `persona-index:${selectedCohort.build_id}` : null, (signal) =>
    unwrap(api.GET("/api/v1/personas/{build_id}", { params: { path: { build_id: selectedCohort!.build_id } }, signal })));
  const fixed = caps.data?.runner.fixed_persona_ids ?? [];
  const ready = selectedCohort ? selectedCohort.realized.record_ids.filter((id) => personaIndex.data?.items.some((i) => i.record_id === id)).length : 0;

  useEffect(() => {
    setForm((f) => ({ ...f, callsLimit: f.mode === "legacy_ab_live" ? "2" : "0" }));
  }, [form.mode]);

  const hints: string[] = [];
  if (form.mode === "smoke" && form.personaSource !== "legacy_fixture_single") hints.push("Smoke runs only the single fixture persona through the fake transport.");
  if (form.mode !== "smoke" && form.personaSource !== "legacy_fixture_pair") hints.push("The A/B preflight and live path accept only the existing two-persona fixture.");
  if (form.personaSource === "cohort") hints.push("A cohort draft is saved for design only: no verified runner accepts arbitrary cohorts, and the fixture personas are never substituted.");
  if (form.scenarioKind === "draft") hints.push("A draft scenario cannot be passed to the fixed runner, so execution will be blocked.");
  if (form.environment === "SCENARIO") hints.push("SCENARIO is a draft-only environment.");

  async function save() {
    setSaving(true);
    setError(undefined);
    try {
      const created = await unwrap(api.POST("/api/v1/experiments", {
        body: {
          name: form.name.trim() || "Untitled draft",
          persona_source: form.personaSource,
          cohort_id: form.personaSource === "cohort" ? form.cohortId || null : null,
          scenario: form.scenarioKind === "draft" ? { kind: "draft", text: form.scenarioText } : { kind: "none" },
          task: { id: "product_feedback_v1" },
          environment: form.environment,
          mode: form.mode,
          model: form.mode === "smoke" ? null : form.model.trim() || null,
          temperature: form.mode === "smoke" || form.temperature === "" ? null : Number(form.temperature),
          calls_limit: Number(form.callsLimit),
        },
      }));
      router.replace(withBuild("/experiments/new", linkBuild, { draft: created.experiment_id }));
    } catch (err) {
      setError(toApiError(err));
      setSaving(false);
    }
  }

  return (
    <div className="stack">
      {caps.error ? <ErrorState error={caps.error} onRetry={caps.reload} what="capabilities" /> : null}

      <ol className="steps reference-wizard" aria-label="Design experiment steps">
        {[["Scenario","What is happening?"],["Task","What should personas do?"],["Environment","How will they respond?"],["Cohort","Who will participate?"]].map(([title,hint],i)=><li key={title} aria-current={step===i?"step":undefined} className={i<step?"done":undefined}><button type="button" aria-label={`Step ${i+1}: ${title}`} onClick={()=>setStep(i)}><span>{i<step?"✓":i+1}</span><span>{title}<small>{hint}</small></span></button></li>)}
      </ol>
      {step===0 ? <div className="wizard-panels"><section className="card stack wizard-panel"><h2><Icon name="sources"/> Scenario</h2><div className="field"><label htmlFor="scenario-title">Title</label><input id="scenario-title" type="text" maxLength={120} value={form.name} onChange={e=>set("name",e.target.value)} placeholder="Name your experiment"/></div><p className="small muted">Describe the situation presented to personas. Custom scenarios are saved as drafts until a compatible runner exists.</p>
          <fieldset>
            <legend>Scenario (the condition)</legend>
            <label className="check"><input type="radio" name="scenario" checked={form.scenarioKind === "none"} onChange={() => set("scenarioKind", "none")} /> None: task unchanged</label>
            <label className="check"><input type="radio" name="scenario" checked={form.scenarioKind === "draft"} onChange={() => set("scenarioKind", "draft")} /> Custom scenario (draft only)</label>
            {form.scenarioKind === "draft" ? (
              <div className="field" style={{ marginTop: 8 }}>
                <label htmlFor="scenario-text">Scenario text</label>
                <textarea id="scenario-text" maxLength={4000} value={form.scenarioText} onChange={(e) => set("scenarioText", e.target.value)} />
                <span className="field-hint">Saved with the draft. Execution stays disabled: the fixed runner has no scenario input.</span>
              </div>
            ) : null}
          </fieldset>
      </section><section className="card stack wizard-panel"><h2>Scenario preview</h2><div className="scenario-preview"><span className="scenario-symbol"><Icon name={form.scenarioKind==='draft'?"location":"experiment"} size={40}/></span><h3>{form.name.trim() || (form.scenarioKind==='draft'?"Your research scenario":"Product feedback survey")}</h3><p>{form.scenarioKind==='draft'?(form.scenarioText||"Your scenario description will appear here."):"The existing survey task is used without a scenario manipulation."}</p><Badge tone={form.scenarioKind==='draft'?"warn":"info"} glyph="·">{form.scenarioKind==='draft'?"Draft only":"Existing task"}</Badge></div><p className="small muted">Illustrative preview. No responses have been generated.</p></section></div> : null}
      {step===1 ? <section className="card stack wizard-panel"><h2><Icon name="sources"/> Task</h2>          <fieldset>
            <legend>Task (instrument and response schema)</legend>
            {tasks.data?.items.map((t) => (
              <div key={t.id}>
                <label className="check"><input type="radio" name="task" checked readOnly /> {t.title}</label>
                <p className="small muted">Instrument <code>{t.instrument_id}</code>{t.question_count_from_snapshots ? `, ${t.question_count_from_snapshots} questions in recorded snapshots` : ""}.
                  External task content: {t.external_content_available ? "available" : "not available in this environment"}.</p>
                <ul className="small muted">{t.notes.map((n) => <li key={n}>{n}</li>)}</ul>
              </div>
            )) ?? <Loading what="tasks" />}
          </fieldset></section> : null}
      {step===2 ? <section className="card stack wizard-panel"><h2><Icon name="layers"/> Environment</h2>          <fieldset>
            <legend>Environment (the execution mechanism)</legend>
            {envs.data?.items.map((e) => (
              <div key={e.name}>
                <label className="check">
                  <input type="radio" name="environment" checked={form.environment === e.name} onChange={() => set("environment", e.name as Form["environment"])} />
                  {e.name} {e.status === "draft_only" ? <Badge tone="neutral" glyph="·">Draft only</Badge> : null}
                </label>
                <p className="small muted">{e.description}{e.reasons.length ? ` ${e.reasons.join(" ")}` : ""}</p>
              </div>
            )) ?? <Loading what="environments" />}
          </fieldset></section> : null}
      {step===3 ? <>
      <section className="card stack" aria-labelledby="s1">
        <h2 id="s1">1. Personas</h2>
        <fieldset>
          <legend>Who answers</legend>
          <div className="stack">
            <label className="option-card">
              <input type="radio" name="source" checked={form.personaSource === "legacy_fixture_pair"} onChange={() => set("personaSource", "legacy_fixture_pair")} />
              <span><strong>Existing two-persona fixture (A/B)</strong><br />
                <span className="small muted">{fixed.length ? fixed.join(" and ") : "Fixed IDs read from the runner"}. These personas differ in age band and in marital status, so this is not a single-attribute contrast.</span></span>
            </label>
            <label className="option-card">
              <input type="radio" name="source" checked={form.personaSource === "legacy_fixture_single"} onChange={() => set("personaSource", "legacy_fixture_single")} />
              <span><strong>Existing single fixture persona (smoke)</strong><br />
                <span className="small muted">{fixed[0] ?? "The first fixture persona"} only, as the smoke runner is hard-wired.</span></span>
            </label>
            <label className="option-card">
              <input type="radio" name="source" checked={form.personaSource === "cohort"} onChange={() => set("personaSource", "cohort")} />
              <span><strong>A saved cohort (draft only)</strong><br />
                <span className="small muted">Records the exact realized IDs. Cannot be executed with the existing runners.</span></span>
            </label>
          </div>
        </fieldset>
        {form.personaSource === "cohort" ? (
          <div className="field">
            <label htmlFor="cohort-select">Cohort</label>
            <select id="cohort-select" value={form.cohortId} onChange={(e) => set("cohortId", e.target.value)}>
              <option value="">Choose a saved cohort</option>
              {(cohorts.data?.items ?? []).map((c) => (
                <option key={c.cohort_id} value={c.cohort_id} disabled={c.current.status !== "valid"}>
                  {c.name || c.cohort_id} · {c.realized.selected_count} residents{c.current.status !== "valid" ? " · source changed" : ""}
                </option>
              ))}
            </select>
            {cohorts.data && cohorts.data.items.length === 0 ? <span className="field-hint">No cohorts yet. <Link href={withBuild("/cohorts", linkBuild)}>Create one</Link>.</span> : null}
            {selectedCohort ? (
              <p className="small">
                {selectedCohort.realized.selected_count} realized IDs: {selectedCohort.realized.record_ids.slice(0, 8).join(", ")}
                {selectedCohort.realized.record_ids.length > 8 ? " …" : ""}. Persona readiness: {ready} of {selectedCohort.realized.selected_count} have a stored
                persona YAML; the rest are source cards only.
              </p>
            ) : null}
          </div>
        ) : null}
      </section>      <section className="card stack" aria-labelledby="s3">
        <h2 id="s3">3. Execution settings</h2>
        <fieldset>
          <legend>Mode</legend>
          <div className="stack">
            {([
              ["preflight", "Preflight only (default)", "Prepares and reviews the exact prompts with the existing A/B runner. Zero provider calls.", caps.data?.modes.preflight],
              ["smoke", "Fake smoke run", "Runs the real survey agent once with a deterministic fake transport. Zero provider calls; answers are not persona behaviour.", caps.data?.modes.smoke],
              ["legacy_ab_live", "Live two-persona A/B", "Exactly two provider calls, one per fixture persona, zero automatic retries, after an explicit start.", caps.data?.modes.legacy_ab_live],
            ] as [Mode, string, string, Schemas["ModeCapability"] | undefined][]).map(([value, title, text, cap]) => (
              <label className="option-card" key={value}>
                <input type="radio" name="mode" checked={form.mode === value} onChange={() => set("mode", value)} />
                <span><strong>{title}</strong> <ModeBadge mode={cap} /><br /><span className="small muted">{text}</span>
                  {cap && !cap.available && cap.reasons[0] ? <><br /><span className="small muted">Why unavailable: {cap.reasons[0]}</span></> : null}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid-3">
          <div className="field">
            <label htmlFor="model">Model (provider/model)</label>
            <input id="model" type="text" value={form.model} disabled={form.mode === "smoke"} onChange={(e) => set("model", e.target.value)} placeholder="provider/model" aria-describedby="model-hint" />
            <span className="field-hint" id="model-hint">
              {form.mode === "smoke" ? "Smoke uses the fake transport model." : `Accepted prefixes: ${(caps.data?.runner.provider_prefixes ?? []).join(", ")}. This list does not show that a model is available.`}
            </span>
          </div>
          <div className="field">
            <label htmlFor="temperature">Temperature</label>
            <input id="temperature" type="number" min={0} max={1} step={0.1} value={form.temperature} disabled={form.mode === "smoke"} onChange={(e) => set("temperature", e.target.value)} />
            <span className="field-hint">Checked by the runner to lie in [0, 1].</span>
          </div>
          <div className="field">
            <label htmlFor="calls">Provider-call limit</label>
            <input id="calls" type="number" min={0} max={10} step={1} value={form.callsLimit} onChange={(e) => set("callsLimit", e.target.value)} />
            <span className="field-hint">The live A/B path makes exactly 2 calls; preflight and smoke make none.</span>
          </div>
        </div>
      </section>      <section className="card stack" aria-labelledby="s4">
        <h2 id="s4">4. Save draft</h2>
        <div className="field">
          <label htmlFor="name">Draft name</label>
          <input id="name" type="text" maxLength={120} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Untitled draft" />
        </div>
        {hints.length ? <Notice tone="info" title="What this draft can and cannot do:"><ul>{hints.map((h) => <li key={h}>{h}</li>)}</ul></Notice> : null}
        {error ? <ErrorState error={error} what="saving the draft" /> : null}
        <div className="row">
          <button type="button" className="button primary" disabled={saving || (form.personaSource === "cohort" && !form.cohortId)} onClick={save}>
            {saving ? "Saving…" : "Save draft"}
          </button>
          <span className="small muted">Saving records the configuration only. Nothing is queued or run.</span>
        </div>
      </section>
      </> : null}
      <div className="wizard-actions"><button type="button" className="button" disabled={step===0} onClick={()=>setStep(n=>n-1)}>Back</button><span className="small muted">Step {step+1} of 4 · Nothing is run when a draft is saved</span>{step<3?<button type="button" className="button primary" onClick={()=>setStep(n=>n+1)}>Next <Icon name="arrow" size={14}/></button>:<span/>}</div>
    </div>
  );
}

function DraftView({ draftId }: { draftId: string }) {
  const params = useSearchParams();
  const linkBuild = params.get("build");
  const detail = useApi(`experiment:${draftId}`, (signal) =>
    unwrap(api.GET("/api/v1/experiments/{experiment_id}", { params: { path: { experiment_id: draftId } }, signal })));
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ApiError | undefined>();
  const [confirmLive, setConfirmLive] = useState(false);
  const d = detail.data;
  const plan = d?.preflights[0];
  const job = plan ? d?.jobs.find((j) => j.preflight_hash === plan.preflight_hash) : undefined;
  const idempotencyKey = useMemo(() => (plan ? `ui-${plan.preflight_hash.slice(0, 12)}-${crypto.randomUUID().replace(/-/g, "")}` : ""), [plan?.preflight_hash]); // eslint-disable-line react-hooks/exhaustive-deps
  const active = job && (job.state === "queued" || job.state === "running");

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => detail.reload(), 2000);
    return () => clearInterval(timer);
  }, [active, detail]);

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setActionError(undefined);
    try {
      await fn();
      detail.reload();
    } catch (err) {
      setActionError(toApiError(err));
    } finally {
      setBusy(null);
    }
  }

  if (detail.loading && !d) return <Loading what="draft" />;
  if (detail.error && !d) return <ErrorState error={detail.error} onRetry={detail.reload} what="draft" />;
  if (!d || !d.config) return <UnavailableState title="This is not a managed draft." />;
  const c = d.config;
  const executable = c.mode !== "preflight";
  const stepNow = job ? 5 : plan ? (executable ? 5 : 4) : 4;

  return (
    <div className="stack">
      <Steps current={stepNow} done={job?.state === "completed" ? 6 : plan ? 5 : 4} />
      <section className="card stack" aria-labelledby="draft-h">
        <div className="card-head"><h2 id="draft-h">Draft: {d.name}</h2><RunStateBadge state={d.display_state} /></div>
        <p className="small muted">{d.display_state_reason}</p>
        <KeyValues items={[
          ["Experiment ID", <CopyId key="id" value={c.experiment_id} label="experiment ID" />],
          ["Personas", c.persona_source === "cohort" ? <span key="p">Cohort <Link href={withBuild(`/cohorts/${c.cohort_id}`, linkBuild)}>{c.cohort_id}</Link></span> : c.persona_source.replaceAll("_", " ")],
          ["Realized IDs", c.realized_ids.join(", ")],
          ["Scenario", c.scenario.kind === "draft" ? `Draft: ${c.scenario.text}` : "None"],
          ["Task", <span key="t"><code>{c.task.task_path}</code> · content hash {c.task.content_hash ? <code>{c.task.content_hash.slice(0, 16)}…</code> : "unknown"}</span>],
          ["Environment", c.environment],
          ["Mode", c.mode],
          ["Model and temperature", c.mode === "smoke" ? "Fake transport (smoke/fake)" : `${c.model ?? "not set"} · ${c.temperature ?? "not set"}`],
          ["Provider-call limit", String(c.calls_limit)],
          ["Configuration hash", <code key="h">{c.config_hash}</code>],
        ]} />
        {c.provenance_gaps.length ? <ul className="small muted">{c.provenance_gaps.map((g) => <li key={g}>{g}</li>)}</ul> : null}
        {d.blockers.length ? (
          <Notice tone="warn" title="Saved as a draft. Execution is blocked:">
            <ul>{d.blockers.map((b) => <li key={b.code}>{b.message} <code className="small">{b.code}</code></li>)}</ul>
          </Notice>
        ) : null}
        {d.preparation_status === "blocked_by_dependencies" ? (
          <UnavailableState title="Preflight needs the external runtime, which is not available here." reasons={d.dependency_reasons} />
        ) : null}
        <p className="small"><Link href={withBuild("/experiments/new", linkBuild)}>Start another draft</Link></p>
      </section>

      <section className="card stack" aria-labelledby="pf-h">
        <h2 id="pf-h">5. Preflight review</h2>
        <p className="small">Validates the draft, runs the existing runner in prepare-only mode where applicable, and records an immutable plan. It makes zero provider calls.</p>
        <div className="row">
          <button type="button" className="button" disabled={Boolean(busy) || d.blockers.length > 0}
            onClick={() => run("preflight", () => unwrap(api.POST("/api/v1/experiments/{experiment_id}/preflight", { params: { path: { experiment_id: c.experiment_id } } })))}>
            {busy === "preflight" ? "Preparing…" : plan ? "Prepare a new preflight" : "Run preflight"}
          </button>
          {d.preflights.length > 1 ? <span className="small muted">{d.preflights.length} plans recorded; the newest is shown.</span> : null}
        </div>
        {actionError ? <ErrorState error={actionError} what={busy ?? "the last action"} /> : null}
        {plan ? <PreflightView plan={plan} /> : <p className="muted">No preflight yet.</p>}
      </section>

      {plan && executable ? (
        <section className="card stack" aria-labelledby="start-h">
          <h2 id="start-h">6. Explicit start</h2>
          {job ? (
            <div className="stack">
              <p className="row"><span>Job <code>{job.job_id}</code></span><RunStateBadge state={job.state} /></p>
              {job.error_message ? <Notice tone="crit" title={`Ended with ${job.error_code}:`}>{job.error_message}</Notice> : null}
              {job.state === "queued" ? (
                <button type="button" className="button small" disabled={Boolean(busy)}
                  onClick={() => run("cancel", () => unwrap(api.POST("/api/v1/experiments/{experiment_id}/jobs/{job_id}/cancel", { params: { path: { experiment_id: c.experiment_id, job_id: job.job_id } } })))}>
                  Cancel before it starts
                </button>
              ) : null}
              {job.state === "running" ? <p className="small muted">Running jobs are not interrupted: a request already sent cannot be retracted.</p> : null}
              {job.state === "completed" || job.state === "failed" ? (
                <Link className="button" href={withBuild(`/results/${encodeURIComponent(c.experiment_id)}`, linkBuild, { job: job.job_id })}>Open results</Link>
              ) : null}
              <p className="small muted">This reviewed plan has been used. Prepare a new preflight to run again.</p>
            </div>
          ) : (
            <div className="stack">
              {plan.execution_blockers.length ? (
                <UnavailableState title="This plan cannot be started:" reasons={plan.execution_blockers.map((b) => b.message)} />
              ) : null}
              {c.mode === "legacy_ab_live" ? (
                <label className="check">
                  <input type="checkbox" checked={confirmLive} onChange={(e) => setConfirmLive(e.target.checked)} />
                  I reviewed this plan and want to send exactly {plan.planned_provider_calls} requests to <code>{plan.model}</code>, with no automatic retries.
                </label>
              ) : null}
              <div className="row">
                <button type="button" className="button primary"
                  disabled={Boolean(busy) || plan.execution_blockers.length > 0 || (c.mode === "legacy_ab_live" && !confirmLive)}
                  onClick={() => run("start", () => unwrap(api.POST("/api/v1/experiments/{experiment_id}/execute", {
                    params: { path: { experiment_id: c.experiment_id } },
                    body: { preflight_hash: plan.preflight_hash, mode: c.mode as "smoke" | "legacy_ab_live", idempotency_key: idempotencyKey },
                  })))}>
                  {busy === "start" ? "Starting…" : c.mode === "smoke" ? "Start fake smoke run" : "Start live run"}
                </button>
                <span className="small muted">Repeated clicks reuse one idempotency key, so this plan can create at most one job.</span>
              </div>
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
