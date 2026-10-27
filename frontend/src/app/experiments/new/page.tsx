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
import { v2, type Cohort, type CompiledScenarioResponse, type Environment, type Experiment, type ExperimentDefinition, type Geography, type Plan, type RunView, type ScenarioList } from "@/lib/api/v2";
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
    model: { backend: "matraix", transport: "fake", model: null, temperature: 0, seed: null, max_output_tokens: 512 },
    execution: { repetitions: 1, max_attempts: 1, max_calls: 20, max_cost_usd: null },
    persona: { visible_fields: null },
  };
}

type CustomScenarioModalProps = {
  open: boolean;
  onClose: () => void;
  onCreated: (scenarioId: string) => Promise<void>;
};

function CustomScenarioModal({ open, onClose, onCreated }: CustomScenarioModalProps) {
  const [modalPrompt, setModalPrompt] = useState("");
  const [autofilling, setAutofilling] = useState(false);
  const [scenarioId, setScenarioId] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("housing");
  const [policyType, setPolicyType] = useState("rent_control");
  const [provinceCode, setProvinceCode] = useState("06");
  const [provinceName, setProvinceName] = useState("Ankara");
  const [description, setDescription] = useState("");
  const [baselineFare, setBaselineFare] = useState("12000");
  const [newFare, setNewFare] = useState("15000");
  const [increasePercentage, setIncreasePercentage] = useState("25");
  const [currency, setCurrency] = useState("TL/month");
  const [questionId, setQuestionId] = useState("q1_affordability");
  const [questionText, setQuestionText] = useState("Can your household afford this adjusted monthly rate?");
  const [options, setOptions] = useState([
    { id: "yes_comfortably", label: "Yes, comfortably" },
    { id: "neutral_stretched", label: "Manageable, but financially stretched" },
    { id: "no_unaffordable", label: "No, unaffordable for our household" },
  ]);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handlePromptAutofill = async () => {
    const raw = modalPrompt.trim();
    if (raw.length < 3) return;
    setAutofilling(true);
    setErrorMsg(null);
    try {
      const res = await v2<CompiledScenarioResponse>("/scenarios/from-prompt", {
        method: "POST",
        body: { prompt: raw, save: false },
      });
      setScenarioId(res.scenario_id);
      setName(res.name);
      setDescription(res.description);
      setProvinceCode(res.location.province_code);
      setProvinceName(res.location.province_name);
      setCategory(res.policy.category);
      setPolicyType(res.policy.type);
      if (res.policy.parameters) {
        if (res.policy.parameters.baseline_fare) setBaselineFare(String(res.policy.parameters.baseline_fare));
        if (res.policy.parameters.new_fare) setNewFare(String(res.policy.parameters.new_fare));
        if (res.policy.parameters.increase_percentage !== undefined) setIncreasePercentage(String(res.policy.parameters.increase_percentage));
        if (res.policy.parameters.currency) setCurrency(res.policy.parameters.currency);
      }
      if (res.questions && res.questions[0]) {
        setQuestionId(res.questions[0].id);
        setQuestionText(res.questions[0].text);
        if (res.questions[0].options && res.questions[0].options.length >= 2) {
          setOptions(res.questions[0].options);
        }
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setAutofilling(false);
    }
  };

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErrorMsg(null);
    try {
      const cleanId = (scenarioId || name.toLowerCase().replace(/[^a-z0-9]+/g, "_")).replace(/^_+|_+$/g, "");
      if (!cleanId.match(/^[a-z][a-z0-9_]{1,63}$/)) {
        throw new Error("Scenario ID must start with a lowercase letter and contain only lowercase letters, digits, or underscores (2-64 chars).");
      }
      if (!name.trim()) throw new Error("Scenario title is required.");
      if (description.trim().length < 10) throw new Error("Description must be at least 10 characters.");
      if (!questionText.trim()) throw new Error("Question text is required.");
      if (options.length < 2) throw new Error("At least 2 question options are required.");

      const bVal = parseFloat(baselineFare) || 0;
      const nVal = parseFloat(newFare) || 0;
      const pct = parseFloat(increasePercentage) || 0;

      const payload = {
        scenario_id: cleanId,
        version: "1.0.0",
        name: name.trim(),
        description: description.trim(),
        location: { province_code: provinceCode, province_name: provinceName },
        metadata: { hypothetical: true, source_note: "Custom policy simulation" },
        policy: {
          category,
          type: policyType,
          parameters: {
            baseline_fare: bVal > 0 ? bVal : undefined,
            new_fare: nVal > 0 ? nVal : undefined,
            increase_percentage: pct !== 0 ? pct : undefined,
            currency: currency || "TL",
          },
        },
        questions: [
          {
            id: questionId.trim() || "q1",
            text: questionText.trim(),
            type: "single_choice",
            options: options.map((o) => ({ id: o.id.trim(), label: o.label.trim() })),
            allow_other: false,
            ask_rationale: true,
          },
        ],
      };

      await v2<unknown>("/scenarios", { method: "POST", body: payload });
      await onCreated(cleanId);
      onClose();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="custom-sc-title"
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(0, 0, 0, 0.8)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: "16px",
      }}
    >
      <div
        className="card stack"
        style={{
          width: "100%",
          maxWidth: "680px",
          maxHeight: "90vh",
          overflowY: "auto",
          padding: "24px",
          backgroundColor: "var(--surface-1)",
          boxShadow: "0 16px 48px rgba(0,0,0,0.6)",
        }}
      >
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h2 id="custom-sc-title" style={{ margin: 0 }}>Create Custom Policy Scenario</h2>
          <button type="button" className="button small" onClick={onClose} aria-label="Close dialog">✕</button>
        </div>

        <p className="small muted">
          Define a custom policy intervention and survey questionnaire. Saving it writes a validated policy scenario directly to the twin’s scenario library.
        </p>

        {errorMsg ? <div className="notice crit"><strong>Error:</strong> {errorMsg}</div> : null}

        <div style={{
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "12px 14px",
          display: "flex",
          flexDirection: "column",
          gap: "8px",
        }}>
          <label htmlFor="modal-prompt-input" style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--info-ink)" }}>
            ⚡ Quick-fill form from prompt
          </label>
          <div className="row" style={{ gap: "8px" }}>
            <input
              id="modal-prompt-input"
              type="text"
              style={{ flex: 1 }}
              placeholder="e.g. 25% transit fare increase in Ankara affecting commuters"
              value={modalPrompt}
              onChange={(e) => setModalPrompt(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handlePromptAutofill(); } }}
            />
            <button
              type="button"
              className="button small primary"
              onClick={handlePromptAutofill}
              disabled={autofilling || modalPrompt.trim().length < 3}
            >
              {autofilling ? "Extracting..." : "Auto-fill"}
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="stack">
          <div className="form-grid">
            <div className="field">
              <label htmlFor="cs-id">Scenario ID (lowercase_identifier)</label>
              <input
                id="cs-id"
                type="text"
                placeholder="e.g. rent_cap_001"
                value={scenarioId}
                onChange={(e) => setScenarioId(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))}
              />
            </div>
            <div className="field">
              <label htmlFor="cs-name">Scenario Title</label>
              <input
                id="cs-name"
                type="text"
                placeholder="e.g. Ankara Residential Rent Cap"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (!scenarioId) {
                    setScenarioId(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 32));
                  }
                }}
                required
              />
            </div>
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="cs-cat">Category</label>
              <select id="cs-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="housing">Housing & Urban</option>
                <option value="transportation">Transportation</option>
                <option value="energy">Energy & Utilities</option>
                <option value="taxation">Taxation & Fiscal</option>
                <option value="social_welfare">Social Welfare & Subsidies</option>
                <option value="education">Education</option>
                <option value="healthcare">Healthcare</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="cs-type">Policy Type</label>
              <input
                id="cs-type"
                type="text"
                placeholder="e.g. rent_control, subsidy, fare_increase"
                value={policyType}
                onChange={(e) => setPolicyType(e.target.value)}
              />
            </div>
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="cs-prov-code">Province Code</label>
              <input
                id="cs-prov-code"
                type="text"
                placeholder="06"
                maxLength={2}
                value={provinceCode}
                onChange={(e) => setProvinceCode(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="cs-prov-name">Province Name</label>
              <input
                id="cs-prov-name"
                type="text"
                placeholder="Ankara"
                value={provinceName}
                onChange={(e) => setProvinceName(e.target.value)}
              />
            </div>
          </div>

          <div className="field">
            <label htmlFor="cs-desc">Description (Narrative of the policy change)</label>
            <textarea
              id="cs-desc"
              rows={3}
              placeholder="Describe the policy change, its scope, and context for AI respondents..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
            />
          </div>

          <fieldset>
            <legend>Policy Parameters (Optional)</legend>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="cs-base">Baseline Value</label>
                <input
                  id="cs-base"
                  type="number"
                  step="any"
                  placeholder="e.g. 10000"
                  value={baselineFare}
                  onChange={(e) => setBaselineFare(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="cs-new">Proposed Value</label>
                <input
                  id="cs-new"
                  type="number"
                  step="any"
                  placeholder="e.g. 12500"
                  value={newFare}
                  onChange={(e) => setNewFare(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="cs-pct">Change (%)</label>
                <input
                  id="cs-pct"
                  type="number"
                  step="any"
                  placeholder="e.g. 25"
                  value={increasePercentage}
                  onChange={(e) => setIncreasePercentage(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="cs-curr">Unit / Currency</label>
                <input
                  id="cs-curr"
                  type="text"
                  placeholder="TL/month"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                />
              </div>
            </div>
          </fieldset>

          <fieldset>
            <legend>Survey Question for Synthetic Citizens</legend>
            <div className="field">
              <label htmlFor="cs-qtext">Question / Prompt</label>
              <textarea
                id="cs-qtext"
                rows={2}
                value={questionText}
                onChange={(e) => setQuestionText(e.target.value)}
                required
              />
            </div>

            <div className="stack" style={{ marginTop: 8 }}>
              <label className="small" style={{ fontWeight: 600 }}>Choice Options:</label>
              {options.map((opt, idx) => (
                <div key={idx} className="row" style={{ alignItems: "center" }}>
                  <input
                    type="text"
                    style={{ flex: "0 0 160px" }}
                    placeholder="option_id"
                    value={opt.id}
                    onChange={(e) =>
                      setOptions(options.map((o, j) => (j === idx ? { ...o, id: e.target.value } : o)))
                    }
                    aria-label={`Option ${idx + 1} ID`}
                  />
                  <input
                    type="text"
                    style={{ flex: 1 }}
                    placeholder="Option label text"
                    value={opt.label}
                    onChange={(e) =>
                      setOptions(options.map((o, j) => (j === idx ? { ...o, label: e.target.value } : o)))
                    }
                    aria-label={`Option ${idx + 1} Label`}
                  />
                  <button
                    type="button"
                    className="button small"
                    disabled={options.length <= 2}
                    onClick={() => setOptions(options.filter((_, j) => j !== idx))}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="button small"
                disabled={options.length >= 8}
                onClick={() =>
                  setOptions([...options, { id: `option_${options.length + 1}`, label: "" }])
                }
              >
                + Add Option
              </button>
            </div>
          </fieldset>

          <div className="row" style={{ justifyContent: "flex-end", gap: 10, marginTop: 12 }}>
            <button type="button" className="button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="button primary" disabled={busy}>
              {busy ? "Saving to Catalog…" : "Save Scenario & Load"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Builder({ populationId }: { populationId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const pop = useLinkPop();
  const caps = useCapabilities();
  const cohorts = useApi("v2:cohorts", (signal) => v2<{ items: Cohort[] }>("/cohorts", { signal }));
  const geo = useApi(`v2:geo:${populationId}`, (signal) => v2<Geography>("/geography/provinces", { query: { population_id: populationId }, signal }));
  const scenarios = useApi("v2:scenarios", (signal) => v2<ScenarioList>("/scenarios", { signal }));
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("transport_fare_001");
  const [selectedQuestionId, setSelectedQuestionId] = useState<string>("");
  const [showCustomModal, setShowCustomModal] = useState<boolean>(false);
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [promptText, setPromptText] = useState<string>("");
  const [compilingPrompt, setCompilingPrompt] = useState<boolean>(false);
  const [promptFeedback, setPromptFeedback] = useState<string | null>(null);
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

  const activeScenario = scenarios.data?.items.find((s) => s.scenario_id === selectedScenarioId)
    ?? scenarios.data?.items[0];

  const handleAutoCreateCohort = async () => {
    try {
      setCompilingPrompt(true);
      setPromptFeedback("Sampling representative adult cohort for population...");
      await v2<Cohort>("/cohorts", {
        method: "POST",
        body: {
          name: "Representative Adult Sample",
          population_id: populationId,
          filters: { age_min: 18 },
        },
      });
      await cohorts.reload();
      setPromptFeedback("Representative adult cohort created!");
    } catch (err) {
      setPromptFeedback(`Error creating cohort: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCompilingPrompt(false);
    }
  };

  const handleSimulateDirectly = async (customPrompt?: string) => {
    const raw = (customPrompt ?? promptText).trim();
    if (raw.length < 3) return;
    setCompilingPrompt(true);
    setPromptFeedback("Analyzing prompt and compiling policy parameters…");
    try {
      // 1. Ensure cohort exists or auto-create default adult cohort
      let cohortId = d.cohort.cohort_id || valid[0]?.cohort_id;
      if (!cohortId) {
        setPromptFeedback("Sampling initial representative adult cohort…");
        const newCohort = await v2<Cohort>("/cohorts", {
          method: "POST",
          body: {
            name: "Representative Adult Sample",
            population_id: populationId,
            filters: { age_min: 18 },
          },
        });
        await cohorts.reload();
        cohortId = newCohort.cohort_id;
      }

      // 2. Compile scenario from prompt
      setPromptFeedback("Synthesizing scenario and calibrated questions…");
      const res = await v2<CompiledScenarioResponse>("/scenarios/from-prompt", {
        method: "POST",
        body: { prompt: raw, save: true },
      });
      await scenarios.reload();
      setSelectedScenarioId(res.scenario_id);
      setSelectedQuestionId("");

      // 3. Transform to experiment definition
      setPromptFeedback("Preparing experiment definition…");
      const ex = await v2<ExperimentDefinition>(`/scenarios/${res.scenario_id}/experiment-definition`, {
        query: { cohort_id: cohortId },
      });

      const fullDef: ExperimentDefinition = {
        ...ex,
        cohort: {
          ...ex.cohort,
          cohort_id: cohortId,
          sample_size: d.cohort.sample_size || ex.cohort.sample_size,
        },
        model: {
          ...ex.model,
          backend: d.model.backend,
          transport: d.model.transport,
        },
        environment: {
          ...ex.environment,
          province_code: d.environment.province_code ?? ex.environment.province_code,
        },
        persona: { visible_fields: null },
      };
      setD(fullDef);

      // 4. Create experiment & plan
      setPromptFeedback("Building execution plan & persona prompts…");
      const created = await v2<Experiment>("/experiments", { method: "POST", body: fullDef });
      setExp(created);
      const planRes = await v2<Plan>(`/experiments/${created.experiment_id}/plan`, { method: "POST", body: {} });
      setPlan(planRes);

      // 5. Run simulation
      setPromptFeedback("Simulating persona responses across cohort…");
      const out = await v2<{ run: RunView }>(`/experiments/${created.experiment_id}/runs`, {
        method: "POST",
        body: {
          plan_hash: planRes.plan_hash,
          idempotency_key: `ui-${planRes.plan_hash.slice(0, 24)}`,
          confirm: true,
        },
      });

      // 6. Direct transition to results
      router.push(withPop(`/results/${out.run.run_id}`, pop));
    } catch (err: unknown) {
      setPromptFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
      setCompilingPrompt(false);
    }
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
      setPromptFeedback(
        `Compiled "${res.name}" in ${res.location.province_name} with ${res.questions?.length ?? 1} question(s). Loaded into manual form below.`
      );
    } catch (err: unknown) {
      setPromptFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCompilingPrompt(false);
    }
  };

  const loadPolicyScenario = async (scenarioId: string, qId?: string) => {
    const cohortId = d.cohort.cohort_id || valid.find((c) => !c.minors)?.cohort_id || valid[0]?.cohort_id || "";
    const query: Record<string, string> = {};
    if (cohortId) query.cohort_id = cohortId;
    if (qId) query.question_id = qId;
    const ex = await v2<ExperimentDefinition>(`/scenarios/${scenarioId}/experiment-definition`, { query });
    setD((cur) => ({
      ...ex,
      cohort: {
        ...ex.cohort,
        cohort_id: cur.cohort.cohort_id || ex.cohort.cohort_id || cohortId,
      },
      persona: { visible_fields: null },
    }));
  };

  const loadExample = async () => {
    if (activeScenario) {
      await loadPolicyScenario(activeScenario.scenario_id, selectedQuestionId || undefined);
    } else {
      const cohortId = d.cohort.cohort_id || valid.find((c) => !c.minors)?.cohort_id || valid[0]?.cohort_id || "";
      const ex = await v2<ExperimentDefinition>("/examples/fare-experiment", { query: { cohort_id: cohortId || "default" } });
      setD({ ...ex, persona: { visible_fields: null } });
    }
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
                {compilingPrompt ? (
                  <span>Simulating…</span>
                ) : (
                  <>
                    <span>Simulate Policy</span>
                  </>
                )}
              </button>
            </div>
          </div>

          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            {/* Prompt Suggestion Chips */}
            <div className="row" style={{ gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <span className="small muted" style={{ fontSize: "0.76rem" }}>Examples:</span>
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
                    handleSimulateDirectly(example);
                  }}
                  title="Click to run this example simulation directly"
                >
                  {example.slice(0, 48)}...
                </button>
              ))}
            </div>

            <button
              type="button"
              className="button small"
              disabled={compilingPrompt || promptText.trim().length < 3}
              onClick={() => {
                handleCompilePrompt();
                setShowAdvanced(true);
              }}
              style={{ fontSize: "0.78rem" }}
              title="Compile prompt into parameters and open wizard to customize before running"
            >
              Compile &amp; Customize in Wizard →
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

      {/* 2. ADVANCED TOGGLE HEADER & QUICK SETTINGS */}
      <div
        className="card"
        style={{
          padding: "12px 18px",
          background: showAdvanced ? "var(--surface-2)" : "var(--surface-1)",
          borderColor: showAdvanced ? "var(--border-strong)" : "var(--border)",
          transition: "all 0.15s ease",
        }}
      >
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <div className="row" style={{ alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: "1rem" }}>⚙</span>
            <strong style={{ fontSize: "0.9rem" }}>Advanced Settings &amp; Multi-Step Wizard</strong>
            <span className="badge" style={{ fontSize: "0.75rem", background: "var(--surface-3)", color: "var(--text-muted)" }}>
              {showAdvanced ? "Expanded" : "Collapsed"}
            </span>
            <span className="small muted">
              (Sample: {d.cohort.sample_size} personas · {d.model.backend === "stub" ? "Offline Test Pipeline" : d.model.transport === "live" ? "Live Cloud LLM" : "AI Citizen Agents (Simulated)"} · {d.environment.province_code ? geo.data?.provinces.find((p) => p.province_code === d.environment.province_code)?.province_name : "Persona's province"})
            </span>
          </div>

          <div className="row" style={{ gap: 8 }}>
            <button
              type="button"
              className="button small"
              onClick={() => setShowAdvanced((cur) => !cur)}
              style={{ fontWeight: 600, minWidth: "130px" }}
            >
              {showAdvanced ? "▲ Hide Advanced" : "▼ Show Advanced"}
            </button>
          </div>
        </div>

        {/* Quick Toggles Bar */}
        <div
          className="row"
          style={{
            marginTop: 10,
            paddingTop: 10,
            borderTop: "1px solid var(--border)",
            gap: 16,
            alignItems: "center",
            flexWrap: "wrap",
            fontSize: "0.82rem",
          }}
        >
          <div className="row" style={{ alignItems: "center", gap: 6 }}>
            <label htmlFor="quick-sample-size" className="small muted">Sample Size:</label>
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
            <label htmlFor="quick-backend" className="small muted">Execution Engine:</label>
            <select
              id="quick-backend"
              className="small"
              value={`${d.model.backend}:${d.model.transport}`}
              onChange={(e) => {
                const [backend, transport] = e.target.value.split(":") as ["stub" | "matraix", "fake" | "live"];
                patch("model", { backend, transport });
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
            <label htmlFor="quick-province" className="small muted">Target Region:</label>
            <select
              id="quick-province"
              className="small"
              value={d.environment.province_code ?? ""}
              onChange={(e) => patch("environment", { province_code: e.target.value || null, context_indicators: [] })}
            >
              <option value="">Auto / Each persona&apos;s own province</option>
              {geo.data?.provinces.filter((p) => p.has_population_controls || p.context_indicators > 0).map((p) => (
                <option key={p.province_code} value={p.province_code}>{p.province_name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* 3. FULL 6-STEP WIZARD (Shown when showAdvanced === true) */}
      {showAdvanced ? (
        <div className="stack" style={{ gap: 16 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <ol className="builder-steps" aria-label="Experiment design steps">
              {STEPS.map((s, i) => (
                <li key={s}>
                  <button
                    type="button"
                    aria-current={i === step ? "step" : undefined}
                    onClick={() => setStep(i)}
                    aria-label={`Step ${i + 1}: ${s}`}
                  >
                    <span>{i + 1}</span>
                    {s}
                  </button>
                </li>
              ))}
            </ol>
            <div className="row" style={{ alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <label htmlFor="scenario-select" className="small" style={{ fontWeight: 600 }}>Policy Template:</label>
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
                  title="Select specific question from this scenario questionnaire"
                >
                  {activeScenario.questions.map((q) => (
                    <option key={q.id} value={q.id}>
                      {q.id}: {q.text.slice(0, 40)}...
                    </option>
                  ))}
                </select>
              ) : null}
              <button type="button" className="button small primary" onClick={loadExample} disabled={!activeScenario}>
                Load Template
              </button>
              <button type="button" className="button small" onClick={() => setShowCustomModal(true)}>
                + Custom Template
              </button>
            </div>
          </div>

          {cohorts.data && valid.length === 0 ? (
            <div className="notice warn" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>No cohort saved for this population. Experiments require a representative cohort.</span>
              <button type="button" className="button small primary" onClick={handleAutoCreateCohort} disabled={compilingPrompt}>
                Auto-Create Sample Cohort
              </button>
            </div>
          ) : null}

          {step === 0 ? (
            <section className="card stack" aria-labelledby="s-h">
              <div className="notice info" style={{ marginBottom: 4 }}>
                <strong>Scenario Configuration:</strong> Edit experiment title, policy parameter names, numeric values and units. Or click <strong>+ Custom Template</strong> above to save a new reusable template.
              </div>
              <h2 id="s-h">Scenario — what is happening?</h2>
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
                  <option value="">Each persona&apos;s own province</option>
                  {geo.data?.provinces.filter((p) => p.has_population_controls || p.context_indicators > 0).map((p) => <option key={p.province_code} value={p.province_code}>{p.province_name}</option>)}
                </select></div>
              <fieldset><legend>Context dimensions shown to the agent{envCode ? ` (indicators of ${env.data?.province.province_name ?? envCode})` : ""}</legend>
                {env.loading && !env.data ? <Loading what="environment" /> : null}
                {env.data && indicators.length === 0 ? <p className="small muted">No context indicators are loaded for this province.</p> : null}
                {env.data ? Object.entries(env.data.domains).map(([domain, rows]) => {
                  const usable = rows.filter((i) => i.value !== null);
                  const chosen = usable.filter((i) => d.environment.context_indicators.includes(i.indicator_id)).length;
                  return usable.length ? (
                    <details key={domain} open={chosen > 0}>
                      <summary>{domain} <span className="small muted">({usable.length}{chosen ? `, ${chosen} selected` : ""})</span></summary>
                      <div className="checks">{usable.map((i) => (
                        <label className="check" key={i.indicator_id}><input type="checkbox" checked={d.environment.context_indicators.includes(i.indicator_id)}
                          onChange={(e) => patch("environment", { context_indicators: e.target.checked ? [...d.environment.context_indicators, i.indicator_id] : d.environment.context_indicators.filter((x) => x !== i.indicator_id) })} />
                          {i.label} ({i.source_period ?? i.source_year})</label>))}</div>
                    </details>
                  ) : null;
                }) : null}
                <p className="field-hint">Each indicator is shown with its own reference period (a year or a published multi-year period). Missing indicators and projections are omitted, never invented. At most 20 can be selected.</p>
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
                <div className="field"><label htmlFor="m-backend">Execution Engine</label>
                  <select id="m-backend" value={`${d.model.backend}:${d.model.transport}`} onChange={(e) => { const [backend, transport] = e.target.value.split(":") as ["stub" | "matraix", "fake" | "live"]; patch("model", { backend, transport }); }}>
                    <option value="matraix:fake" disabled={!caps.data?.backends.matraix_fake.available}>AI Citizen Agents (Zero-cost simulation){caps.data?.backends.matraix_fake.available ? "" : " — unavailable"}</option>
                    <option value="matraix:live">AI Citizen Agents (Live cloud LLM provider — gated)</option>
                    <option value="stub:fake">Pipeline Test (Deterministic placeholder — offline, no AI model)</option>
                  </select></div>
                <div className="field"><label htmlFor="m-model">Provider/model</label><input id="m-model" type="text" placeholder="e.g. anthropic/claude-haiku-5-5" value={d.model.model ?? ""} disabled={d.model.transport !== "live"} onChange={(e) => patch("model", { model: e.target.value || null })} /></div>
                <div className="field"><label htmlFor="m-temp">Temperature</label><input id="m-temp" type="number" step="0.1" min={0} max={2} value={d.model.temperature} onChange={(e) => patch("model", { temperature: Number(e.target.value) })} /></div>
                <div className="field"><label htmlFor="m-reps">Repetitions per persona</label><input id="m-reps" type="number" min={1} max={5} value={d.execution.repetitions} onChange={(e) => patch("execution", { repetitions: Number(e.target.value) })} /></div>
                <div className="field"><label htmlFor="m-att">Attempts per call (1 = no retry)</label><input id="m-att" type="number" min={1} max={3} value={d.execution.max_attempts} onChange={(e) => patch("execution", { max_attempts: Number(e.target.value) })} /></div>
                <div className="field"><label htmlFor="m-cap">Call cap (budget guard)</label><input id="m-cap" type="number" min={1} value={d.execution.max_calls} onChange={(e) => patch("execution", { max_calls: Number(e.target.value) })} /></div>
                <div className="field"><label htmlFor="m-cost">Cost cap (USD, optional)</label><input id="m-cost" type="number" min={0} step="0.01" value={d.execution.max_cost_usd ?? ""} onChange={(e) => patch("execution", { max_cost_usd: e.target.value === "" ? null : Number(e.target.value) })} /></div>
              </div>
              {d.model.transport === "live" ? <Notice tone="warn" title="Live execution is gated.">Live AI agent execution requires SOCIETYTWIN_ENABLE_LIVE_EXECUTION and a provider API key in the server environment. Calls invoke cloud models; the review step lists all requirements.</Notice> : null}
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
                <dt>Execution</dt><dd>{d.model.backend === "stub" ? "Pipeline Test (No AI)" : d.model.transport === "live" ? `AI Citizen Agent (Live: ${d.model.model || "provider default"})` : "AI Citizen Agent (Zero-Cost Simulation)"} · temperature {d.model.temperature}</dd>
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
      ) : null}

      <CustomScenarioModal
        open={showCustomModal}
        onClose={() => setShowCustomModal(false)}
        onCreated={async (newId) => {
          await scenarios.reload();
          setSelectedScenarioId(newId);
          await loadPolicyScenario(newId);
        }}
      />
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
