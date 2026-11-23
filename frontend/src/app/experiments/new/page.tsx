"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { PopulationGate, useCapabilities } from "@/components/national/common";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { StatTile } from "@/components/StatTile";
import { Badge } from "@/components/StatusBadge";
import {
  v2,
  type Capabilities,
  type Cohort,
  type CompiledScenarioResponse,
  type Experiment,
  type ExperimentDefinition,
  type Geography,
  type Plan,
  type RunView,
  type ScenarioList,
} from "@/lib/api/v2";
import { fmtInt, fmtUsd } from "@/lib/format";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

const MODEL_PRESETS = [
  "openai/gpt-4o-mini",
  "openai/gpt-4o",
  "anthropic/claude-3-5-sonnet-latest",
  "gemini/gemini-2.5-flash",
];

const STRATA_OPTIONS = [
  "province_code",
  "sex",
  "age_group",
  "marital_status",
  "education_level",
  "labour_status",
  "urbanicity",
];

function defaultLiveModel(caps?: Capabilities): string {
  const keys = caps?.provider_key_present ?? {};
  if (keys.openai) return "openai/gpt-4o-mini";
  if (keys.anthropic) return "anthropic/claude-3-5-sonnet-latest";
  if (keys.gemini || keys.google) return "gemini/gemini-2.5-flash";
  return "openai/gpt-4o-mini";
}

function blank(cohortId: string): ExperimentDefinition {
  return {
    title: "",
    scenario: { title: "", description: "", parameters: [], hypothetical: true, source_note: null },
    task: {
      instruction: "",
      response_type: "single_choice",
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
  const urlCohort = params.get("cohort") ?? "";
  const cohorts = useApi("v2:cohorts", (signal) => v2<{ items: Cohort[] }>("/cohorts", { signal }));
  const geo = useApi(`v2:geo:${populationId}`, (signal) =>
    v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }),
  );
  const scenarios = useApi("v2:scenarios", (signal) => v2<ScenarioList>("/scenarios", { signal }));

  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("transport_fare_001");
  const [selectedQuestionId, setSelectedQuestionId] = useState<string>("");
  const [showCustomize, setShowCustomize] = useState<boolean>(false);
  const [promptText, setPromptText] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [engineTouched, setEngineTouched] = useState<boolean>(false);
  const [explicitCohort, setExplicitCohort] = useState<boolean>(Boolean(urlCohort));
  const [d, setD] = useState<ExperimentDefinition>(() => blank(urlCohort));
  const [reviewed, setReviewed] = useState<{ experimentId: string; plan: Plan } | null>(null);
  const [confirmed, setConfirmed] = useState<boolean>(false);
  const [running, setRunning] = useState<boolean>(false);

  const valid = cohorts.data?.items.filter((c) => c.status === "valid" && c.population_id === populationId) ?? [];
  const activeScenario =
    scenarios.data?.items.find((s) => s.scenario_id === selectedScenarioId) ?? scenarios.data?.items[0];

  useEffect(() => {
    if (!caps.data || engineTouched) return;
    if (d.model.backend === "matraix" && d.model.transport === "fake" && !caps.data.backends.matraix_fake.available) {
      setD((cur) => ({
        ...cur,
        model: { ...cur.model, backend: "stub", transport: "fake", model: null },
      }));
    }
  }, [caps.data, engineTouched, d.model.backend, d.model.transport]);

  const invalidatePlan = () => {
    setReviewed(null);
    setConfirmed(false);
  };

  const patch = <K extends keyof ExperimentDefinition>(key: K, value: Partial<ExperimentDefinition[K]>) => {
    invalidatePlan();
    setD((cur) => ({ ...cur, [key]: { ...(cur[key] as object), ...(value as object) } }));
  };

  const resolveModelConfig = (cur: ExperimentDefinition["model"]): ExperimentDefinition["model"] => {
    const backend =
      cur.backend === "matraix" && cur.transport === "fake" && caps.data && !caps.data.backends.matraix_fake.available && !engineTouched
        ? "stub"
        : cur.backend;
    return {
      ...cur,
      backend,
      model: cur.transport === "live" ? cur.model || defaultLiveModel(caps.data) : null,
    };
  };

  const ensureCompatibleCohort = async (
    provinces?: string[] | null,
    ageMin?: number | null,
    ageMax?: number | null,
    provinceName?: string,
  ): Promise<string> => {
    if (explicitCohort && d.cohort.cohort_id) {
      return d.cohort.cohort_id;
    }

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

    setFeedback(`Sampling matching cohort (${provLabel} · ${ageLabel})…`);
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

  const buildPlanForDefinition = async (fullDef: ExperimentDefinition) => {
    setFeedback("Saving experiment and generating reviewed execution plan (0 backend calls)…");
    const created = await v2<Experiment>("/experiments", { method: "POST", body: fullDef });
    const planRes = await v2<Plan>(`/experiments/${created.experiment_id}/plan`, { method: "POST", body: {} });
    setReviewed({ experimentId: created.experiment_id, plan: planRes });
    setConfirmed(false);
    setFeedback(
      planRes.executable
        ? "Execution plan ready below. Review calls, cost, and prompt details, then check confirmation to run."
        : "Execution plan created with blockers. Resolve the blockers below before running.",
    );
  };

  const handleRunConfirmed = async () => {
    if (!reviewed || !reviewed.plan.executable || !confirmed) return;
    setRunning(true);
    setFeedback("Simulating persona responses across cohort…");
    try {
      const out = await v2<{ run: RunView }>(`/experiments/${reviewed.experimentId}/runs`, {
        method: "POST",
        body: {
          plan_hash: reviewed.plan.plan_hash,
          idempotency_key: `ui-${reviewed.plan.plan_hash.slice(0, 24)}-${Date.now()}`,
          confirm: true,
        },
      });
      router.push(withPop(`/results/${out.run.run_id}`, pop));
    } catch (err: unknown) {
      setFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setRunning(false);
    }
  };

  const handleCompileAndReview = async (customPrompt?: string) => {
    const raw = (customPrompt ?? promptText).trim();
    if (raw.length < 3) return;
    setBusy(true);
    invalidatePlan();
    setFeedback("Analyzing prompt and compiling policy parameters…");
    try {
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

      setFeedback("Preparing experiment definition…");
      const ex = await v2<ExperimentDefinition>(`/scenarios/${res.scenario_id}/experiment-definition`, {
        query: { cohort_id: cohortId, seed: d.cohort.seed },
      });

      const sampleSize = d.cohort.sample_size || ex.cohort.sample_size;
      const reps = d.execution.repetitions || ex.execution.repetitions;
      const fullDef: ExperimentDefinition = {
        ...ex,
        cohort: {
          ...ex.cohort,
          cohort_id: cohortId,
          sample_size: sampleSize,
          sampling_method: d.cohort.sampling_method,
          seed: d.cohort.seed,
          strata_field: d.cohort.sampling_method === "stratified" ? d.cohort.strata_field || "province_code" : null,
        },
        execution: {
          ...d.execution,
          repetitions: reps,
          max_calls: Math.max(d.execution.max_calls, sampleSize * reps * d.execution.max_attempts),
        },
        model: resolveModelConfig(d.model),
        environment: {
          ...ex.environment,
          province_code: d.environment.province_code ?? ex.environment.province_code,
          context_indicators:
            d.environment.context_indicators.length > 0 ? d.environment.context_indicators : ex.environment.context_indicators,
        },
        persona: d.persona ?? { visible_fields: null },
      };
      setD(fullDef);
      await buildPlanForDefinition(fullDef);
    } catch (err: unknown) {
      setFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const loadPolicyScenario = async (scenarioId: string, qId?: string, syncPrompt: boolean = true) => {
    invalidatePlan();
    const baseCohortId =
      d.cohort.cohort_id || valid.find((c) => !c.minors)?.cohort_id || valid[0]?.cohort_id || "";
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
    const matchedCohortId = explicitCohort && d.cohort.cohort_id
      ? d.cohort.cohort_id
      : await ensureCompatibleCohort(targetProvs, ref?.minimum_age ?? 18, ref?.maximum_age ?? null);

    setD((cur) => {
      const sampleSize = cur.cohort.sample_size || ex.cohort.sample_size;
      const reps = cur.execution.repetitions || ex.execution.repetitions;
      return {
        ...ex,
        cohort: {
          ...ex.cohort,
          cohort_id: matchedCohortId || cur.cohort.cohort_id || ex.cohort.cohort_id || baseCohortId,
          sample_size: sampleSize,
          sampling_method: cur.cohort.sampling_method,
          seed: cur.cohort.seed,
          strata_field: cur.cohort.sampling_method === "stratified" ? cur.cohort.strata_field || "province_code" : null,
        },
        execution: {
          ...cur.execution,
          repetitions: reps,
          max_calls: Math.max(cur.execution.max_calls, sampleSize * reps * cur.execution.max_attempts),
        },
        model: resolveModelConfig(cur.model),
        persona: cur.persona ?? { visible_fields: null },
      };
    });
    if (syncPrompt) {
      const scenarioPrompt = ex.scenario.description
        ? ex.scenario.description.trim()
        : `${ex.scenario.title}. ${ex.task.instruction.trim()}`;
      setPromptText(scenarioPrompt);
    }
  };

  const handleCompilePrompt = async (customPrompt?: string) => {
    const raw = (customPrompt ?? promptText).trim();
    if (raw.length < 3) return;
    setBusy(true);
    setFeedback(null);
    invalidatePlan();
    try {
      const res = await v2<CompiledScenarioResponse>("/scenarios/from-prompt", {
        method: "POST",
        body: { prompt: raw, save: true },
      });
      await scenarios.reload();
      setSelectedScenarioId(res.scenario_id);
      setSelectedQuestionId("");
      await loadPolicyScenario(res.scenario_id, undefined, false);
      setShowCustomize(true);
      setFeedback(
        `Compiled "${res.name}" (${res.location.province_name}). Review or edit parameters, question, and controls below, then click Save & review plan.`,
      );
    } catch (err: unknown) {
      setFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleLoadTemplate = async () => {
    if (!activeScenario) return;
    setBusy(true);
    setFeedback(null);
    try {
      await loadPolicyScenario(activeScenario.scenario_id, selectedQuestionId || undefined);
      setFeedback(`Loaded template "${activeScenario.name}".`);
    } catch (err: unknown) {
      setFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleReviewCustomized = async () => {
    setBusy(true);
    invalidatePlan();
    setFeedback("Preparing experiment definition & plan…");
    try {
      const ref = d.scenario_ref;
      const targetProvs = ref?.province_codes?.length
        ? ref.province_codes
        : d.environment.province_code
          ? [d.environment.province_code]
          : null;
      const cohortId =
        explicitCohort && d.cohort.cohort_id
          ? d.cohort.cohort_id
          : await ensureCompatibleCohort(targetProvs, ref?.minimum_age ?? 18, ref?.maximum_age ?? null);

      const sampleSize = d.cohort.sample_size || 20;
      const reps = d.execution.repetitions || 1;
      const fullDef: ExperimentDefinition = {
        ...d,
        title: d.title.trim() || d.scenario.title.trim() || "Custom Policy Simulation",
        scenario: {
          ...d.scenario,
          title: d.scenario.title.trim() || d.title.trim() || "Custom Policy Scenario",
          description: d.scenario.description.trim() || d.task.instruction.trim() || "Custom Policy Simulation",
        },
        cohort: {
          ...d.cohort,
          cohort_id: cohortId,
          sample_size: sampleSize,
          strata_field: d.cohort.sampling_method === "stratified" ? d.cohort.strata_field || "province_code" : null,
        },
        execution: {
          ...d.execution,
          repetitions: reps,
          max_calls: Math.max(d.execution.max_calls, sampleSize * reps * d.execution.max_attempts),
        },
        model: resolveModelConfig(d.model),
      };
      setD(fullDef);
      await buildPlanForDefinition(fullDef);
    } catch (err: unknown) {
      setFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const matraixFakeReason = caps.data?.backends.matraix_fake.available
    ? null
    : caps.data?.backends.matraix_fake.reasons[0] ?? null;
  const matraixLiveReason = caps.data?.backends.matraix_live.available
    ? null
    : caps.data?.backends.matraix_live.reasons[0] ?? null;

  return (
    <div className="stack" style={{ gap: 18 }}>
      {/* 1. HERO CARD: Prompt-First Policy Simulator */}
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
                Scenario engine · Compiles scenario, builds reviewed call/cost plan, and runs after explicit confirmation
              </span>
            </div>
          </div>
          <div className="row" style={{ gap: 6, alignItems: "center" }}>
            <Badge tone="info">Natural Language (TR / EN)</Badge>
            <Badge tone="fake">Reviewed Plan Required</Badge>
          </div>
        </div>

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
              aria-label="Policy simulation prompt"
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
              onChange={(e) => {
                setPromptText(e.target.value);
                invalidatePlan();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleCompileAndReview();
                }
              }}
              placeholder="e.g. What if bus and subway fares in Ankara increase by 30%? Will people switch to walking or driving?"
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 6, justifyContent: "center" }}>
              <button
                type="button"
                className="button primary"
                disabled={busy || running || promptText.trim().length < 3}
                onClick={() => handleCompileAndReview()}
                style={{
                  minWidth: "170px",
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
                {busy ? "Planning…" : "Compile & review plan"}
              </button>
            </div>
          </div>

          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
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
                    setFeedback(null);
                    invalidatePlan();
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
              disabled={busy || running || promptText.trim().length < 3}
              onClick={() => handleCompilePrompt()}
              style={{ fontSize: "0.78rem" }}
              title="Compile prompt into a survey question so you can preview or edit the options before planning"
            >
              Preview &amp; Edit Question ↓
            </button>
          </div>
        </div>

        {feedback ? (
          <div
            className={`notice ${feedback.startsWith("Error") ? "crit" : "info"}`}
            style={{ fontSize: "0.85rem", padding: "10px 14px", display: "flex", alignItems: "center", gap: 8 }}
          >
            <span>{feedback}</span>
          </div>
        ) : null}
      </section>

      {/* 2. QUICK SETTINGS BAR */}
      <div
        className="card stack"
        style={{
          padding: "12px 18px",
          background: showCustomize ? "var(--surface-2)" : "var(--surface-1)",
          borderColor: showCustomize ? "var(--border-strong)" : "var(--border)",
          gap: 10,
        }}
      >
        <div
          className="row"
          style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, fontSize: "0.84rem" }}
        >
          <div className="row" style={{ gap: 14, alignItems: "center", flexWrap: "wrap" }}>
            <div className="row" style={{ alignItems: "center", gap: 6 }}>
              <label htmlFor="cohort-select" className="small muted">
                Saved cohort:
              </label>
              <select
                id="cohort-select"
                className="small"
                value={explicitCohort ? d.cohort.cohort_id : ""}
                onChange={(e) => {
                  const id = e.target.value;
                  setExplicitCohort(Boolean(id));
                  patch("cohort", { cohort_id: id });
                }}
              >
                <option value="">Auto-create matching adult cohort</option>
                {valid.map((c) => (
                  <option key={c.cohort_id} value={c.cohort_id}>
                    {c.name} ({fmtInt(c.eligible_records)}
                    {c.minors ? `, ${c.minors} minors` : ""})
                  </option>
                ))}
              </select>
            </div>

            <div className="row" style={{ alignItems: "center", gap: 6 }}>
              <label htmlFor="quick-sample-size" className="small muted">
                Sample Size:
              </label>
              <select
                id="quick-sample-size"
                className="small"
                value={[10, 20, 50, 100].includes(d.cohort.sample_size) ? String(d.cohort.sample_size) : "custom"}
                onChange={(e) => {
                  if (e.target.value !== "custom") {
                    const sz = Number(e.target.value);
                    patch("cohort", { sample_size: sz });
                  }
                }}
              >
                <option value="10">10 personas (fastest)</option>
                <option value="20">20 personas (standard)</option>
                <option value="50">50 personas (balanced)</option>
                <option value="100">100 personas (deep)</option>
                {![10, 20, 50, 100].includes(d.cohort.sample_size) ? (
                  <option value="custom">{d.cohort.sample_size} personas (custom)</option>
                ) : null}
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
                  setEngineTouched(true);
                  const [backend, transport] = e.target.value.split(":") as ["stub" | "matraix", "fake" | "live"];
                  patch("model", {
                    backend,
                    transport,
                    model: transport === "live" ? d.model.model || defaultLiveModel(caps.data) : null,
                  });
                }}
              >
                <option
                  value="matraix:fake"
                  disabled={!caps.data?.backends.matraix_fake.available}
                  title={matraixFakeReason ?? undefined}
                >
                  AI Citizen Agents (Zero-cost simulation){matraixFakeReason ? " — unavailable" : ""}
                </option>
                <option
                  value="matraix:live"
                  disabled={caps.data ? !caps.data.backends.matraix_live.available : false}
                  title={matraixLiveReason ?? undefined}
                >
                  AI Citizen Agents (Live LLM provider){matraixLiveReason ? " — unavailable" : ""}
                </option>
                <option value="stub:fake">Pipeline Test (No AI / Offline stub)</option>
              </select>
            </div>

            {d.model.transport === "live" ? (
              <div className="row" style={{ alignItems: "center", gap: 6 }}>
                <label htmlFor="live-model-select" className="small muted">
                  Model:
                </label>
                <select
                  id="live-model-select"
                  className="small"
                  value={MODEL_PRESETS.includes(d.model.model ?? "") ? d.model.model ?? "" : "__custom__"}
                  onChange={(e) => {
                    if (e.target.value !== "__custom__") patch("model", { model: e.target.value });
                  }}
                >
                  {MODEL_PRESETS.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                  <option value="__custom__">Custom provider/model…</option>
                </select>
                <input
                  id="live-model-input"
                  aria-label="Live model identifier"
                  type="text"
                  className="small"
                  style={{ width: 190 }}
                  placeholder="provider/model"
                  value={d.model.model ?? ""}
                  onChange={(e) => patch("model", { model: e.target.value || null })}
                />
              </div>
            ) : null}

            <div className="row" style={{ alignItems: "center", gap: 6 }}>
              <label htmlFor="quick-province" className="small muted">
                Target Region:
              </label>
              <select
                id="quick-province"
                className="small"
                value={d.environment.province_code ?? ""}
                onChange={(e) => patch("environment", { province_code: e.target.value || null })}
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
            onClick={() => {
              if (!showCustomize && promptText.trim().length >= 3 && !d.task.instruction.trim()) {
                handleCompilePrompt();
              } else {
                setShowCustomize((cur) => !cur);
              }
            }}
            style={{ fontWeight: 600 }}
          >
            {showCustomize ? "▲ Hide Question & Templates" : "▼ Customize Question & Templates"}
          </button>
        </div>

        {matraixFakeReason && d.model.backend === "stub" ? (
          <p className="small muted" style={{ margin: 0 }}>
            Defaulting to <strong>stub</strong> pipeline test mode because MatrAIx runtime is unavailable here: {matraixFakeReason}
          </p>
        ) : null}
      </div>

      {/* 3. QUESTION, PARAMETERS & EXECUTION CUSTOMIZER */}
      {showCustomize ? (
        <section className="card stack" aria-label="Customize question and policy template" style={{ gap: 16 }}>
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
                Load a benchmark scenario template or customize scenario fields, parameters, cohort sampling, and execution caps.
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
                onChange={async (e) => {
                  const newId = e.target.value;
                  setSelectedScenarioId(newId);
                  setSelectedQuestionId("");
                  await loadPolicyScenario(newId, undefined, true);
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
                disabled={!activeScenario || busy || running}
              >
                Load Template
              </button>
              {activeScenario && activeScenario.category.startsWith("university_") ? (
                <Link className="button small" href={withPop("/university", pop, { scenario: activeScenario.scenario_id })}>
                  Open in University Sim →
                </Link>
              ) : null}
            </div>
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="sc-title">Scenario title</label>
              <input
                id="sc-title"
                type="text"
                value={d.scenario.title}
                onChange={(e) => patch("scenario", { title: e.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="sc-source">Source note {d.scenario.hypothetical ? "(optional)" : "(required for non-hypothetical)"}</label>
              <input
                id="sc-source"
                type="text"
                value={d.scenario.source_note ?? ""}
                onChange={(e) => patch("scenario", { source_note: e.target.value || null })}
              />
            </div>
          </div>

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

          {d.scenario.parameters.length > 0 ? (
            <fieldset>
              <legend>Scenario parameters (must match text if referenced)</legend>
              <div className="stack" style={{ gap: 6 }}>
                {d.scenario.parameters.map((p, idx) => (
                  <div key={p.name} className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <code style={{ minWidth: 150 }}>{p.name}</code>
                    <span className="small muted" style={{ minWidth: 160 }}>{p.label}</span>
                    <input
                      aria-label={`Parameter ${p.name} value`}
                      type="text"
                      style={{ width: 120 }}
                      value={String(p.value)}
                      onChange={(e) => {
                        const raw = e.target.value;
                        const num = Number(raw);
                        const nextVal = raw !== "" && !Number.isNaN(num) && typeof p.value === "number" ? num : raw;
                        patch("scenario", {
                          parameters: d.scenario.parameters.map((item, j) =>
                            j === idx ? { ...item, value: nextVal } : item,
                          ),
                        });
                      }}
                    />
                    {p.unit ? <span className="small muted">{p.unit}</span> : null}
                  </div>
                ))}
              </div>
            </fieldset>
          ) : null}

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

          <div className="row" style={{ gap: 18, flexWrap: "wrap" }}>
            <label className="check">
              <input
                type="checkbox"
                checked={d.scenario.hypothetical}
                onChange={(e) => patch("scenario", { hypothetical: e.target.checked })}
              />
              Hypothetical scenario
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={d.task.ask_rationale}
                onChange={(e) => patch("task", { ask_rationale: e.target.checked })}
              />
              Ask rationale
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={d.task.adult_only}
                onChange={(e) => patch("task", { adult_only: e.target.checked })}
              />
              Adult-only task (age ≥ 18)
            </label>
          </div>

          <div className="field">
            <label style={{ fontWeight: 600 }}>Question Response Format</label>
            <div className="row" style={{ gap: 20, marginTop: 4 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: "0.88rem" }}>
                <input
                  type="radio"
                  name="task_response_type"
                  value="single_choice"
                  checked={d.task.response_type !== "free_text"}
                  onChange={() => {
                    patch("task", {
                      response_type: "single_choice",
                      options: d.task.options.length >= 2 ? d.task.options : [
                        { id: "support", label: "Support the policy" },
                        { id: "oppose", label: "Oppose the policy" },
                      ],
                    });
                  }}
                />
                <span><strong>Single Choice</strong> (Categorical options)</span>
              </label>

              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: "0.88rem" }}>
                <input
                  type="radio"
                  name="task_response_type"
                  value="free_text"
                  checked={d.task.response_type === "free_text"}
                  onChange={() => {
                    patch("task", {
                      response_type: "free_text",
                      options: [],
                      ask_rationale: true,
                    });
                  }}
                />
                <span><strong>Free-Text Answer</strong> (Open-ended text in citizen&apos;s own words)</span>
              </label>
            </div>
          </div>

          {d.task.response_type === "free_text" ? (
            <div className="notice info" style={{ padding: "12px 16px", fontSize: "0.86rem" }}>
              <strong>Free-Text Question Mode Active:</strong> Synthetic citizen agents will answer with open-ended textual explanations and perspectives in their own words. Full text responses and qualitative quotes will appear directly on the results page.
            </div>
          ) : (
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
          )}

          <details>
            <summary>Sampling, Model &amp; Execution Budget Controls</summary>
            <div className="details-body stack" style={{ gap: 12 }}>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="adv-sample-size">Sample size (active personas)</label>
                  <input
                    id="adv-sample-size"
                    type="number"
                    min={1}
                    max={caps.data?.max_agents_per_run ?? 200}
                    value={d.cohort.sample_size}
                    onChange={(e) => patch("cohort", { sample_size: Math.max(1, Number(e.target.value) || 1) })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="adv-sampling">Sampling method</label>
                  <select
                    id="adv-sampling"
                    value={d.cohort.sampling_method}
                    onChange={(e) => {
                      const method = e.target.value;
                      patch("cohort", {
                        sampling_method: method,
                        strata_field: method === "stratified" ? d.cohort.strata_field || "province_code" : null,
                      });
                    }}
                  >
                    <option value="weighted">weighted</option>
                    <option value="simple_random">simple_random</option>
                    <option value="stratified">stratified</option>
                  </select>
                </div>
                {d.cohort.sampling_method === "stratified" ? (
                  <div className="field">
                    <label htmlFor="adv-strata">Strata field</label>
                    <select
                      id="adv-strata"
                      value={d.cohort.strata_field ?? "province_code"}
                      onChange={(e) => patch("cohort", { strata_field: e.target.value })}
                    >
                      {STRATA_OPTIONS.map((f) => (
                        <option key={f} value={f}>{f}</option>
                      ))}
                    </select>
                  </div>
                ) : null}
                <div className="field">
                  <label htmlFor="adv-seed">Cohort sampling seed</label>
                  <input
                    id="adv-seed"
                    type="number"
                    min={0}
                    value={d.cohort.seed}
                    onChange={(e) => patch("cohort", { seed: Math.max(0, Number(e.target.value) || 0) })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="adv-call-cap">Call cap (budget guard)</label>
                  <input
                    id="adv-call-cap"
                    type="number"
                    min={1}
                    max={5000}
                    value={d.execution.max_calls}
                    onChange={(e) => patch("execution", { max_calls: Math.max(1, Number(e.target.value) || 1) })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="adv-reps">Repetitions</label>
                  <input
                    id="adv-reps"
                    type="number"
                    min={1}
                    max={5}
                    value={d.execution.repetitions}
                    onChange={(e) => patch("execution", { repetitions: Math.min(5, Math.max(1, Number(e.target.value) || 1)) })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="adv-temp">Temperature</label>
                  <input
                    id="adv-temp"
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={d.model.temperature}
                    onChange={(e) => patch("model", { temperature: Number(e.target.value) || 0 })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="adv-max-tokens">Max output tokens</label>
                  <input
                    id="adv-max-tokens"
                    type="number"
                    min={16}
                    max={4096}
                    value={d.model.max_output_tokens ?? 512}
                    onChange={(e) => patch("model", { max_output_tokens: Math.max(16, Number(e.target.value) || 512) })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="adv-cost-cap">Max cost cap (USD, optional)</label>
                  <input
                    id="adv-cost-cap"
                    type="number"
                    min={0}
                    step={0.01}
                    placeholder="No cap"
                    value={d.execution.max_cost_usd ?? ""}
                    onChange={(e) => patch("execution", { max_cost_usd: e.target.value === "" ? null : Number(e.target.value) })}
                  />
                </div>
                <div className="field">
                  <label htmlFor="adv-env-indicators">Context indicators (comma-separated)</label>
                  <input
                    id="adv-env-indicators"
                    type="text"
                    placeholder="total_population, population_density"
                    value={d.environment.context_indicators.join(", ")}
                    onChange={(e) =>
                      patch("environment", {
                        context_indicators: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                      })
                    }
                  />
                </div>
              </div>
            </div>
          </details>

          <div className="row" style={{ justifyContent: "flex-end", gap: 10 }}>
            <button
              type="button"
              className="button primary"
              disabled={
                busy ||
                running ||
                !d.task.instruction.trim() ||
                (d.task.response_type !== "free_text" &&
                  (d.task.options.length < 2 || d.task.options.some((o) => !o.id.trim() || !o.label.trim())))
              }
              onClick={handleReviewCustomized}
            >
              {busy ? "Building plan…" : "Save and review plan"}
            </button>
          </div>
        </section>
      ) : null}

      {/* 4. REVIEWED EXECUTION PLAN & EXPLICIT CONFIRMATION */}
      {reviewed ? (
        <section id="reviewed-plan" className="card stack" aria-label="Reviewed execution plan">
          <div className="card-head" style={{ marginBottom: 0 }}>
            <h2 style={{ margin: 0 }}>Reviewed execution plan</h2>
            <Badge tone={reviewed.plan.executable ? "good" : "crit"} glyph={reviewed.plan.executable ? "✓" : "×"}>
              {reviewed.plan.executable ? "Executable after confirmation" : "Blocked"}
            </Badge>
          </div>

          <div className="tiles">
            <StatTile
              label="Active personas"
              value={fmtInt(reviewed.plan.active_personas)}
              sub={`of ${fmtInt(reviewed.plan.eligible_records)} eligible records`}
            />
            <StatTile
              label="Estimated calls"
              value={fmtInt(reviewed.plan.calls.planned)}
              sub={`Max ${fmtInt(reviewed.plan.calls.maximum_with_retries)} · Cap ${fmtInt(reviewed.plan.calls.cap)}`}
            />
            <StatTile
              label="Input tokens est."
              value={fmtInt(reviewed.plan.tokens.input_estimate_per_repetition)}
              sub={reviewed.plan.tokens.method}
            />
            <StatTile
              label="Estimated cost"
              value={fmtUsd(reviewed.plan.cost.estimate_usd)}
              sub={reviewed.plan.cost.basis}
            />
          </div>

          {reviewed.plan.blockers.length > 0 ? (
            <div className="notice crit" role="alert">
              <strong>Execution is blocked:</strong>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {reviewed.plan.blockers.map((b) => (
                  <li key={b.code}>
                    <code>{b.code}</code>: {b.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {reviewed.plan.warnings.length > 0 ? (
            <div className="notice warn">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {reviewed.plan.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {reviewed.plan.example_prompt ? (
            <details>
              <summary>Inspect example prompt for {reviewed.plan.example_prompt.synthetic_id}</summary>
              <div className="details-body stack">
                <strong>System prompt</strong>
                <pre className="prompt">{reviewed.plan.example_prompt.system}</pre>
                <strong>User prompt</strong>
                <pre className="prompt">{reviewed.plan.example_prompt.user}</pre>
              </div>
            </details>
          ) : null}

          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <label className="check">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={!reviewed.plan.executable || running}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              I reviewed this plan, persona sample, and call/cost budget
            </label>
            <button
              type="button"
              className="button primary"
              disabled={!reviewed.plan.executable || !confirmed || running}
              onClick={handleRunConfirmed}
            >
              {running ? "Running experiment…" : "Run experiment"}
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
        Controlled persona-conditioned AI experiment: describe a policy scenario in natural language or load a benchmark template, review the plan, then confirm execution.
      </PageHeader>
      <Notice tone="info">
        Experiments test the pipeline and explore hypotheses. Their outputs are not predictions of what real residents of Türkiye would do.
      </Notice>
      <PopulationGate what="the experiment builder">{(id) => <Builder populationId={id} />}</PopulationGate>
    </>
  );
}
