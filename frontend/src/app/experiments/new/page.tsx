"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { PopulationGate, useCapabilities } from "@/components/national/common";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import {
  v2,
  type Cohort,
  type CompiledScenarioResponse,
  type Experiment,
  type ExperimentDefinition,
  type Geography,
  type Plan,
  type RunView,
  type ScenarioList,
} from "@/lib/api/v2";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

function blank(cohortId: string): ExperimentDefinition {
  return {
    title: "",
    scenario: { title: "", description: "", parameters: [], hypothetical: true, source_note: null },
    task: {
      instruction: "",
      options: [
        { id: "option_a", label: "" },
        { id: "option_b", label: "" },
      ],
      allow_other_text: false,
      ask_rationale: true,
      adult_only: true,
    },
    environment: { province_code: null, context_indicators: [] },
    cohort: { cohort_id: cohortId, sample_size: 20, sampling_method: "weighted", seed: 7, strata_field: null },
    model: { backend: "matraix", transport: "fake", model: null, temperature: 0, seed: null, max_output_tokens: 512 },
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
  const geo = useApi(`v2:geo:${populationId}`, (signal) =>
    v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }),
  );
  const scenarios = useApi("v2:scenarios", (signal) => v2<ScenarioList>("/scenarios", { signal }));

  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("transport_fare_001");
  const [selectedQuestionId, setSelectedQuestionId] = useState<string>("");
  const [showCustomize, setShowCustomize] = useState<boolean>(false);
  const [promptText, setPromptText] = useState<string>("");
  const [compilingPrompt, setCompilingPrompt] = useState<boolean>(false);
  const [promptFeedback, setPromptFeedback] = useState<string | null>(null);
  const [d, setD] = useState<ExperimentDefinition>(() => blank(params.get("cohort") ?? ""));

  const valid = cohorts.data?.items.filter((c) => c.status === "valid" && c.population_id === populationId) ?? [];

  const patch = <K extends keyof ExperimentDefinition>(key: K, value: Partial<ExperimentDefinition[K]>) =>
    setD((cur) => ({ ...cur, [key]: { ...(cur[key] as object), ...(value as object) } }));

  const activeScenario =
    scenarios.data?.items.find((s) => s.scenario_id === selectedScenarioId) ?? scenarios.data?.items[0];

  const ensureCompatibleCohort = async (
    provinces?: string[] | null,
    ageMin?: number | null,
    ageMax?: number | null,
    provinceName?: string,
  ): Promise<string> => {
    const wantProvs = provinces && provinces.length > 0 ? [...provinces].sort() : null;
    const wantMin = ageMin ?? 18;
    const wantMax = ageMax ?? null;

    const matches = (c: Cohort) => {
      const f = c.filters ?? {};
      if ((f.age_min ?? 0) < wantMin) return false;
      if (wantMax !== null && (f.age_max === undefined || f.age_max === null || f.age_max > wantMax)) return false;
      if (wantMax === null && f.age_max !== undefined && f.age_max !== null) return false;
      if (wantProvs) {
        const cProvs = f.province_codes ? [...f.province_codes].sort() : [];
        if (cProvs.length === 0 || !cProvs.every((p) => wantProvs.includes(p))) return false;
      }
      return true;
    };

    const current = valid.find((c) => c.cohort_id === d.cohort.cohort_id);
    if (current && matches(current)) return current.cohort_id;

    const existing = valid.find(matches);
    if (existing) return existing.cohort_id;

    const provLabel = provinceName || (wantProvs ? wantProvs.join(", ") : "National");
    const ageLabel = wantMax ? `Ages ${wantMin}–${wantMax}` : `Adults ${wantMin}+`;
    const filters: Record<string, unknown> = { age_min: wantMin, adult_only: wantMin >= 18 };
    if (wantMax !== null) filters.age_max = wantMax;
    if (wantProvs) filters.province_codes = wantProvs;

    setPromptFeedback(`Sampling matching cohort (${provLabel} · ${ageLabel})…`);
    try {
      const createdCohort = await v2<Cohort>("/cohorts", {
        method: "POST",
        body: {
          name: `${provLabel} (${ageLabel})`,
          population_id: populationId,
          filters,
        },
      });
      await cohorts.reload();
      return createdCohort.cohort_id;
    } catch {
      if (valid[0]) return valid[0].cohort_id;
      const fallback = await v2<Cohort>("/cohorts", {
        method: "POST",
        body: {
          name: "Representative Adult Sample",
          population_id: populationId,
          filters: { age_min: 18 },
        },
      });
      await cohorts.reload();
      return fallback.cohort_id;
    }
  };

  const executeDefinition = async (fullDef: ExperimentDefinition) => {
    setPromptFeedback("Building execution plan & persona prompts…");
    const created = await v2<Experiment>("/experiments", { method: "POST", body: fullDef });
    const planRes = await v2<Plan>(`/experiments/${created.experiment_id}/plan`, { method: "POST", body: {} });
    if (!planRes.executable || planRes.blockers.length > 0) {
      const reasons = planRes.blockers.map((b) => `${b.code}: ${b.message}`).join(" | ");
      throw new Error(reasons || "Execution plan has blockers.");
    }

    setPromptFeedback("Simulating persona responses across cohort…");
    const out = await v2<{ run: RunView }>(`/experiments/${created.experiment_id}/runs`, {
      method: "POST",
      body: {
        plan_hash: planRes.plan_hash,
        idempotency_key: `ui-${planRes.plan_hash.slice(0, 24)}`,
        confirm: true,
      },
    });

    router.push(withPop(`/results/${out.run.run_id}`, pop));
  };

  const handleSimulateDirectly = async (customPrompt?: string) => {
    const raw = (customPrompt ?? promptText).trim();
    if (raw.length < 3) return;
    setCompilingPrompt(true);
    setPromptFeedback("Analyzing prompt and compiling policy parameters…");
    try {
      setPromptFeedback("Synthesizing scenario and calibrated questions…");
      const res = await v2<CompiledScenarioResponse>("/scenarios/from-prompt", {
        method: "POST",
        body: { prompt: raw, save: true },
      });
      await scenarios.reload();
      setSelectedScenarioId(res.scenario_id);
      setSelectedQuestionId("");

      const tp = res.target_population;
      const targetProvs = tp?.province_codes?.length ? tp.province_codes : [res.location.province_code];
      const cohortId = await ensureCompatibleCohort(
        targetProvs,
        tp?.minimum_age ?? 18,
        tp?.maximum_age ?? null,
        res.location.province_name,
      );

      setPromptFeedback("Preparing experiment definition…");
      const ex = await v2<ExperimentDefinition>(`/scenarios/${res.scenario_id}/experiment-definition`, {
        query: { cohort_id: cohortId },
      });

      const liveModel = d.model.transport === "live" ? d.model.model || "openai/gpt-4o-mini" : null;
      const sampleSize = d.cohort.sample_size || ex.cohort.sample_size;

      const fullDef: ExperimentDefinition = {
        ...ex,
        cohort: {
          ...ex.cohort,
          cohort_id: cohortId,
          sample_size: sampleSize,
        },
        execution: {
          ...ex.execution,
          max_calls: Math.max(ex.execution.max_calls, sampleSize * ex.execution.repetitions),
        },
        model: {
          ...ex.model,
          backend: d.model.backend,
          transport: d.model.transport,
          model: liveModel,
        },
        environment: {
          ...ex.environment,
          province_code: ex.environment.province_code ?? d.environment.province_code,
        },
        persona: { visible_fields: null },
      };
      setD(fullDef);

      await executeDefinition(fullDef);
    } catch (err: unknown) {
      setPromptFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setCompilingPrompt(false);
    }
  };

  const loadPolicyScenario = async (scenarioId: string, qId?: string) => {
    const baseCohortId = d.cohort.cohort_id || valid.find((c) => !c.minors)?.cohort_id || valid[0]?.cohort_id || "";
    const query: Record<string, string> = {};
    if (baseCohortId) query.cohort_id = baseCohortId;
    if (qId) query.question_id = qId;
    const ex = await v2<ExperimentDefinition>(`/scenarios/${scenarioId}/experiment-definition`, { query });
    const ref = ex.scenario_ref;
    const targetProvs = ref?.province_codes?.length
      ? ref.province_codes
      : ex.environment.province_code
        ? [ex.environment.province_code]
        : null;
    const matchedCohortId = await ensureCompatibleCohort(
      targetProvs,
      ref?.minimum_age ?? 18,
      ref?.maximum_age ?? null,
    );
    setD((cur) => {
      const sampleSize = cur.cohort.sample_size || ex.cohort.sample_size;
      return {
        ...ex,
        cohort: {
          ...ex.cohort,
          cohort_id: matchedCohortId || cur.cohort.cohort_id || ex.cohort.cohort_id || baseCohortId,
          sample_size: sampleSize,
        },
        execution: {
          ...ex.execution,
          max_calls: Math.max(ex.execution.max_calls, sampleSize * ex.execution.repetitions),
        },
        model: {
          ...ex.model,
          backend: cur.model.backend,
          transport: cur.model.transport,
          model: cur.model.transport === "live" ? cur.model.model || "openai/gpt-4o-mini" : null,
        },
        persona: { visible_fields: null },
      };
    });
  };

  const handleCompilePrompt = async (customPrompt?: string) => {
    const raw = (customPrompt ?? promptText).trim();
    if (raw.length < 3) return;
    setCompilingPrompt(true);
    setPromptFeedback(null);
    try {
      const res = await v2<CompiledScenarioResponse>("/scenarios/from-prompt", {
        method: "POST",
        body: { prompt: raw, save: true },
      });
      await scenarios.reload();
      setSelectedScenarioId(res.scenario_id);
      setSelectedQuestionId("");
      await loadPolicyScenario(res.scenario_id);
      setShowCustomize(true);
      setPromptFeedback(
        `Compiled "${res.name}" (${res.location.province_name}). You can review or edit the question and options below before running.`,
      );
    } catch (err: unknown) {
      setPromptFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCompilingPrompt(false);
    }
  };

  const handleLoadTemplate = async () => {
    if (!activeScenario) return;
    setCompilingPrompt(true);
    setPromptFeedback(null);
    try {
      await loadPolicyScenario(activeScenario.scenario_id, selectedQuestionId || undefined);
      setPromptFeedback(`Loaded template "${activeScenario.name}".`);
    } catch (err: unknown) {
      setPromptFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCompilingPrompt(false);
    }
  };

  const handleRunCustomized = async () => {
    setCompilingPrompt(true);
    setPromptFeedback("Preparing customized simulation…");
    try {
      const ref = d.scenario_ref;
      const targetProvs = ref?.province_codes?.length
        ? ref.province_codes
        : d.environment.province_code
          ? [d.environment.province_code]
          : null;
      const cohortId = await ensureCompatibleCohort(
        targetProvs,
        ref?.minimum_age ?? 18,
        ref?.maximum_age ?? null,
      );
      const sampleSize = d.cohort.sample_size || 20;
      const liveModel = d.model.transport === "live" ? d.model.model || "openai/gpt-4o-mini" : null;
      const fullDef: ExperimentDefinition = {
        ...d,
        title: d.title.trim() || d.scenario.title.trim() || "Custom Policy Simulation",
        scenario: {
          ...d.scenario,
          title: d.scenario.title.trim() || d.title.trim() || "Custom Policy Scenario",
        },
        cohort: {
          ...d.cohort,
          cohort_id: cohortId,
          sample_size: sampleSize,
        },
        execution: {
          ...d.execution,
          max_calls: Math.max(d.execution.max_calls, sampleSize * d.execution.repetitions),
        },
        model: {
          ...d.model,
          model: liveModel,
        },
      };
      setD(fullDef);
      await executeDefinition(fullDef);
    } catch (err: unknown) {
      setPromptFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setCompilingPrompt(false);
    }
  };

  return (
    <div className="stack" style={{ gap: 18 }}>
      {/* 1. HERO CARD: Minimal Prompt-First Policy Simulator */}
      <section
        className="card"
        style={{
          background: "linear-gradient(145deg, #122130, #0c1824)",
          border: "1px solid #233e56",
          boxShadow: "0 8px 24px rgba(0, 0, 0, 0.25)",
          padding: "22px 26px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <div className="row" style={{ alignItems: "center", gap: 10 }}>
            <span
              style={{
                display: "inline-grid",
                placeItems: "center",
                width: 32,
                height: 32,
                borderRadius: "50%",
                background: "linear-gradient(135deg, #2d81ff, #1452e6)",
                color: "#fff",
                fontWeight: 700,
                fontSize: 16,
              }}
            >
              ✦
            </span>
            <div>
              <h2 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 650, color: "var(--text-primary)" }}>
                Policy Simulation Prompt
              </h2>
              <span className="small muted" style={{ fontSize: "0.8rem" }}>
                Zero-shot scenario engine · Calibrates parameters, selects target populations &amp; simulates citizen agent responses
              </span>
            </div>
          </div>
          <div className="row" style={{ gap: 6, alignItems: "center" }}>
            <span
              style={{
                fontSize: "0.72rem",
                background: "var(--info-bg)",
                color: "var(--info-ink)",
                padding: "2px 8px",
                borderRadius: "10px",
                fontWeight: 600,
                border: "1px solid #264a70",
              }}
            >
              Natural Language (TR / EN)
            </span>
            <span
              style={{
                fontSize: "0.72rem",
                background: "var(--fake-bg)",
                color: "var(--fake-ink)",
                padding: "2px 8px",
                borderRadius: "10px",
                fontWeight: 600,
                border: "1px solid #483974",
              }}
            >
              AI Citizen Agents
            </span>
          </div>
        </div>

        {/* Big Search-like Input Bar */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "stretch",
              background: "var(--surface-1)",
              padding: "6px",
              borderRadius: "10px",
              border: "1px solid #314b64",
              boxShadow: "inset 0 2px 6px rgba(0,0,0,0.3)",
            }}
          >
            <textarea
              id="prompt-scenario-input"
              rows={2}
              style={{
                flex: 1,
                padding: "8px 12px",
                fontSize: "0.95rem",
                lineHeight: 1.4,
                background: "transparent",
                border: "none",
                outline: "none",
                color: "var(--text-primary)",
                resize: "vertical",
                boxShadow: "none",
              }}
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSimulateDirectly();
                }
              }}
              placeholder="e.g. What if bus and subway fares in Ankara increase by 30%? Will people switch to walking or driving?"
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 6, justifyContent: "center" }}>
              <button
                type="button"
                className="button primary"
                disabled={compilingPrompt || promptText.trim().length < 3}
                onClick={() => handleSimulateDirectly()}
                style={{
                  minWidth: "160px",
                  padding: "8px 16px",
                  fontWeight: 600,
                  fontSize: "0.9rem",
                  height: "100%",
                  maxHeight: "44px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                }}
              >
                {compilingPrompt ? <span>Simulating…</span> : <span>Simulate Policy</span>}
              </button>
            </div>
          </div>

          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            {/* Prompt Suggestion Chips */}
            <div className="row" style={{ gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <span className="small muted" style={{ fontSize: "0.76rem" }}>
                Examples:
              </span>
              {[
                "Ankara transit fares increase by 30%: switch to walking or driving?",
                "Simulate an 18% electricity tariff increase in Bursa for households",
                "How would university students in Istanbul respond to a 50% transit pass discount?",
              ].map((example) => (
                <button
                  key={example}
                  type="button"
                  className="button small"
                  style={{
                    fontSize: "0.75rem",
                    padding: "3px 9px",
                    background: "var(--surface-2)",
                    border: "1px solid var(--border)",
                    borderRadius: "12px",
                    color: "var(--text-secondary)",
                    cursor: "pointer",
                  }}
                  onClick={() => {
                    setPromptText(example);
                    setPromptFeedback(null);
                  }}
                  title="Click to populate prompt input"
                >
                  {example.slice(0, 48)}...
                </button>
              ))}
            </div>

            <button
              type="button"
              className="button small"
              disabled={compilingPrompt || promptText.trim().length < 3}
              onClick={() => handleCompilePrompt()}
              style={{ fontSize: "0.78rem" }}
              title="Compile prompt into a survey question so you can preview or edit the options before running"
            >
              Preview &amp; Edit Question ↓
            </button>
          </div>
        </div>

        {/* Live Feedback Banner */}
        {promptFeedback ? (
          <div
            className={`notice ${promptFeedback.startsWith("Error") ? "crit" : "info"}`}
            style={{
              fontSize: "0.85rem",
              padding: "10px 14px",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            {compilingPrompt ? <span style={{ animation: "spin 1s linear infinite" }}>⏳</span> : null}
            <span>{promptFeedback}</span>
          </div>
        ) : null}
      </section>

      {/* 2. QUICK SETTINGS BAR & OPTIONAL QUESTION CUSTOMIZER TOGGLE */}
      <div
        className="card"
        style={{
          padding: "12px 18px",
          background: showCustomize ? "var(--surface-2)" : "var(--surface-1)",
          borderColor: showCustomize ? "var(--border-strong)" : "var(--border)",
          transition: "all 0.15s ease",
        }}
      >
        <div
          className="row"
          style={{
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 14,
            fontSize: "0.84rem",
          }}
        >
          <div className="row" style={{ gap: 16, alignItems: "center", flexWrap: "wrap" }}>
            <div className="row" style={{ alignItems: "center", gap: 6 }}>
              <label htmlFor="quick-sample-size" className="small muted">
                Sample Size:
              </label>
              <select
                id="quick-sample-size"
                className="small"
                value={d.cohort.sample_size}
                onChange={(e) => patch("cohort", { sample_size: Number(e.target.value) })}
              >
                <option value={10}>10 personas (fastest)</option>
                <option value={20}>20 personas (standard)</option>
                <option value={50}>50 personas (balanced)</option>
                <option value={100}>100 personas (deep)</option>
              </select>
            </div>

            <div className="row" style={{ alignItems: "center", gap: 6 }}>
              <label htmlFor="quick-backend" className="small muted">
                Execution Engine:
              </label>
              <select
                id="quick-backend"
                className="small"
                value={`${d.model.backend}:${d.model.transport}`}
                onChange={(e) => {
                  const [backend, transport] = e.target.value.split(":") as ["stub" | "matraix", "fake" | "live"];
                  patch("model", {
                    backend,
                    transport,
                    model: transport === "live" ? d.model.model || "openai/gpt-4o-mini" : null,
                  });
                }}
              >
                <option value="matraix:fake" disabled={!caps.data?.backends.matraix_fake.available}>
                  AI Citizen Agents (Zero-cost simulation)
                </option>
                <option value="matraix:live">AI Citizen Agents (Live LLM provider)</option>
                <option value="stub:fake">Pipeline Test (No AI / Offline)</option>
              </select>
            </div>

            <div className="row" style={{ alignItems: "center", gap: 6 }}>
              <label htmlFor="quick-province" className="small muted">
                Target Region:
              </label>
              <select
                id="quick-province"
                className="small"
                value={d.environment.province_code ?? ""}
                onChange={(e) =>
                  patch("environment", { province_code: e.target.value || null, context_indicators: [] })
                }
              >
                <option value="">Auto / Detected from prompt</option>
                {geo.data?.provinces
                  .filter((p) => p.has_population_controls || p.context_indicators > 0)
                  .map((p) => (
                    <option key={p.province_code} value={p.province_code}>
                      {p.province_name}
                    </option>
                  ))}
              </select>
            </div>
          </div>

          <button
            type="button"
            className="button small"
            onClick={() => setShowCustomize((cur) => !cur)}
            style={{ fontWeight: 600 }}
          >
            {showCustomize ? "▲ Hide Question & Templates" : "▼ Customize Question & Templates"}
          </button>
        </div>
      </div>

      {/* 3. SIMPLIFIED SINGLE-CARD QUESTION & TEMPLATE DRAWER */}
      {showCustomize ? (
        <section className="card stack" aria-label="Customize question and policy template" style={{ gap: 16 }}>
          {/* Built-in / Saved Template Picker */}
          <div
            className="row"
            style={{
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 10,
              paddingBottom: 12,
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div>
              <strong style={{ fontSize: "0.95rem" }}>Saved Policy Templates &amp; Survey Question</strong>
              <p className="small muted" style={{ margin: "2px 0 0 0" }}>
                Load a benchmark scenario template or customize the survey question and multiple-choice options below.
              </p>
            </div>
            <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <label htmlFor="scenario-select" className="small muted">
                Template:
              </label>
              <select
                id="scenario-select"
                className="small"
                value={activeScenario?.scenario_id ?? selectedScenarioId}
                onChange={(e) => {
                  setSelectedScenarioId(e.target.value);
                  setSelectedQuestionId("");
                }}
              >
                {scenarios.data?.items.map((s) => (
                  <option key={s.scenario_id} value={s.scenario_id}>
                    {s.name} ({s.category})
                  </option>
                ))}
              </select>
              {activeScenario && activeScenario.questions.length > 1 ? (
                <select
                  id="question-select"
                  className="small"
                  value={selectedQuestionId || activeScenario.questions[0].id}
                  onChange={(e) => setSelectedQuestionId(e.target.value)}
                  title="Select question from this template"
                >
                  {activeScenario.questions.map((q) => (
                    <option key={q.id} value={q.id}>
                      {q.id}: {q.text.slice(0, 42)}...
                    </option>
                  ))}
                </select>
              ) : null}
              <button
                type="button"
                className="button small primary"
                onClick={handleLoadTemplate}
                disabled={!activeScenario || compilingPrompt}
              >
                Load Template
              </button>
            </div>
          </div>

          {/* Scenario Summary & Question Editor */}
          <div className="field">
            <label htmlFor="sc-desc">Policy Context / Description (shown to AI citizen personas)</label>
            <textarea
              id="sc-desc"
              rows={2}
              placeholder="Describe the policy change being evaluated..."
              value={d.scenario.description}
              onChange={(e) => patch("scenario", { description: e.target.value })}
            />
          </div>

          <div className="field">
            <label htmlFor="t-ins">Survey Question</label>
            <textarea
              id="t-ins"
              rows={2}
              placeholder="What question should each synthetic citizen answer?"
              value={d.task.instruction}
              onChange={(e) => patch("task", { instruction: e.target.value })}
            />
          </div>

          <fieldset>
            <legend>Answer Choices</legend>
            {d.task.options.map((o, i) => (
              <div className="option-row" key={i} style={{ marginBottom: 6 }}>
                <input
                  aria-label={`Option ${i + 1} id`}
                  type="text"
                  value={o.id}
                  onChange={(e) =>
                    patch("task", {
                      options: d.task.options.map((q, j) => (j === i ? { ...q, id: e.target.value } : q)),
                    })
                  }
                />
                <input
                  aria-label={`Option ${i + 1} label`}
                  type="text"
                  value={o.label}
                  onChange={(e) =>
                    patch("task", {
                      options: d.task.options.map((q, j) => (j === i ? { ...q, label: e.target.value } : q)),
                    })
                  }
                />
                <button
                  type="button"
                  className="button small"
                  disabled={d.task.options.length <= 2}
                  onClick={() => patch("task", { options: d.task.options.filter((_, j) => j !== i) })}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="button small"
              disabled={d.task.options.length >= 8}
              onClick={() =>
                patch("task", {
                  options: [...d.task.options, { id: `option_${d.task.options.length + 1}`, label: "" }],
                })
              }
            >
              + Add Option
            </button>
          </fieldset>

          <div className="row" style={{ justifyContent: "flex-end", gap: 10 }}>
            <button
              type="button"
              className="button primary"
              disabled={
                compilingPrompt ||
                !d.scenario.description.trim() ||
                !d.task.instruction.trim() ||
                d.task.options.some((o) => !o.id.trim() || !o.label.trim())
              }
              onClick={handleRunCustomized}
            >
              {compilingPrompt ? "Running Simulation…" : "Run Customized Simulation"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export default function NewExperimentPage() {
  return (
    <>
      <PageHeader title="New Experiment">
        Controlled persona-conditioned AI experiment: describe a policy scenario in natural language or load a benchmark template.
      </PageHeader>
      <Notice tone="info">
        Experiments test the pipeline and explore hypotheses. Their outputs are not predictions of what real residents of Türkiye would do.
      </Notice>
      <PopulationGate what="the experiment builder">{(id) => <Builder populationId={id} />}</PopulationGate>
    </>
  );
}
