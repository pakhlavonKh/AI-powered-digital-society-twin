"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { describeDetails, toApiError } from "@/lib/api/client";
import { Notice } from "@/components/Notices";
import { Badge } from "@/components/StatusBadge";
import {
  ExecutiveAnswerCard,
  UniversityQueryStats,
} from "@/components/university/UniversityQueryStats";
import {
  v2,
  type ElasticityPreset,
  type PlacementProgramsCatalog,
  type SnapshotUniversityItem,
  type UniversityQueryPlanResponse,
  type UniversityQueryRunListItem,
  type UniversityQueryRunResponse,
  type UniversityQuerySpec,
  type UniversityRegistryStatus,
} from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";

const EXAMPLE_PROMPTS = [
  "How many students would apply to this uni if tuition increased by 30%?",
  "How would applications and cutoffs change if this uni's ranking got higher or lower?",
  "If we raise tuition by 25% and add 15% scholarship aid, how do revenue and low-income applicants change?",
  "Which rival universities gain applicants if full-fee tuition rises by 30%?",
  "How does a 20% tuition hike affect 4-semester student retention and dropout at this uni?",
];

function formatApiError(err: unknown): string {
  const apiErr = toApiError(err);
  const details = describeDetails(apiErr.details);
  return `${apiErr.message}${details ? ` (${details})` : ""}`;
}

type Props = {
  catalog: PlacementProgramsCatalog | null;
  regStatus: UniversityRegistryStatus | null;
  populationId: string | null;
  populationLabel: string | null;
  initialRuns: UniversityQueryRunListItem[];
  onApplyLeversToNumericStudio: (spec: UniversityQuerySpec) => void;
  showNumericStudio: boolean;
  onToggleNumericStudio: () => void;
};

export function UniversityQueryStudio({
  catalog,
  regStatus,
  populationId,
  populationLabel,
  initialRuns,
  onApplyLeversToNumericStudio,
  showNumericStudio,
  onToggleNumericStudio,
}: Props) {
  const [prompt, setPrompt] = useState(EXAMPLE_PROMPTS[0]);
  const [snapshotId, setSnapshotId] = useState<string>("");
  const [admissionYear, setAdmissionYear] = useState<string>("");
  const [snapshotUniversities, setSnapshotUniversities] = useState<SnapshotUniversityItem[]>([]);
  const [contextUniversityId, setContextUniversityId] = useState<string>("");
  const [usePopulationCohort, setUsePopulationCohort] = useState<boolean>(false);
  const [cohortSize, setCohortSize] = useState<number>(200);
  const [seed, setSeed] = useState<number>(42);
  const [elasticityPreset, setElasticityPreset] = useState<ElasticityPreset>("medium");

  const [plan, setPlan] = useState<UniversityQueryPlanResponse | null>(null);
  const [editableSpec, setEditableSpec] = useState<UniversityQuerySpec | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [running, setRunning] = useState(false);
  const [queryRuns, setQueryRuns] = useState<UniversityQueryRunListItem[]>(initialRuns);
  const [activeRun, setActiveRun] = useState<UniversityQueryRunResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    setQueryRuns(initialRuns);
  }, [initialRuns]);

  const snapshots = useMemo(
    () => (regStatus && Array.isArray(regStatus.snapshots) ? regStatus.snapshots : []),
    [regStatus],
  );
  const autoSelectedSnapshot = useRef(false);
  useEffect(() => {
    if (!autoSelectedSnapshot.current && !snapshotId && snapshots.length > 0) {
      autoSelectedSnapshot.current = true;
      setSnapshotId(snapshots[0].snapshot_id);
    }
  }, [snapshots, snapshotId]);
  const activeSnapshot = useMemo(
    () => snapshots.find((s) => s.snapshot_id === snapshotId) ?? null,
    [snapshots, snapshotId],
  );

  const demoUniversities = useMemo(() => {
    const map = new Map<string, { university_id: string; university_name: string; university_type: string }>();
    for (const p of catalog?.programs ?? []) {
      if (!map.has(p.university_id)) {
        map.set(p.university_id, {
          university_id: p.university_id,
          university_name: p.university_name,
          university_type: p.university_type,
        });
      }
    }
    return Array.from(map.values());
  }, [catalog]);

  const universityOptions = useMemo(() => {
    if (snapshotId && snapshotUniversities.length > 0) {
      return snapshotUniversities.map((u) => ({
        university_id: u.university_id,
        university_name: u.university_name,
        university_type: u.university_type,
      }));
    }
    return demoUniversities;
  }, [snapshotId, snapshotUniversities, demoUniversities]);

  useEffect(() => {
    if (!contextUniversityId && universityOptions.length > 0) {
      const preferred =
        universityOptions.find((u) => u.university_type === "foundation") ?? universityOptions[0];
      if (preferred) setContextUniversityId(preferred.university_id);
    }
  }, [contextUniversityId, universityOptions]);

  useEffect(() => {
    if (!snapshotId) {
      setSnapshotUniversities([]);
      if (
        demoUniversities.length > 0 &&
        !demoUniversities.some((u) => u.university_id === contextUniversityId)
      ) {
        const preferred =
          demoUniversities.find((u) => u.university_type === "foundation") ?? demoUniversities[0];
        if (preferred) setContextUniversityId(preferred.university_id);
      }
      return;
    }
    let cancelled = false;
    v2<{ snapshot_id: string; items: SnapshotUniversityItem[] }>(
      `/university-registry/snapshots/${encodeURIComponent(snapshotId)}/universities`,
    )
      .then((res) => {
        if (cancelled) return;
        const items = Array.isArray(res?.items) ? res.items : [];
        setSnapshotUniversities(items);
        if (items.length > 0) {
          const preferred =
            items.find((u) => u.university_type === "foundation") ?? items[0];
          setContextUniversityId(preferred.university_id);
        }
      })
      .catch(() => {
        if (!cancelled) setSnapshotUniversities([]);
      });
    return () => {
      cancelled = true;
    };
  }, [snapshotId, demoUniversities]);

  const selectedSnapshotYears = useMemo(() => {
    const snap = snapshots.find((s) => s.snapshot_id === snapshotId);
    return snap?.admission_years ?? [];
  }, [snapshots, snapshotId]);

  async function compilePlan(overridePrompt?: string, overrideUniversityId?: string) {
    const effectivePrompt = (overridePrompt ?? prompt).trim();
    if (!effectivePrompt) return;
    setCompiling(true);
    setErrorMsg(null);
    try {
      const targetUid = overrideUniversityId !== undefined ? overrideUniversityId : contextUniversityId;
      const res = await v2<UniversityQueryPlanResponse>("/university/query/plan", {
        method: "POST",
        body: {
          prompt: effectivePrompt,
          context_university_id: targetUid || null,
          snapshot_id: snapshotId || null,
          admission_year: admissionYear ? Number(admissionYear) : null,
          population_id: usePopulationCohort && populationId ? populationId : null,
          cohort_size: cohortSize,
          seed,
          elasticity_preset: elasticityPreset,
        },
      });
      setPlan(res);
      setEditableSpec(res.query_spec);
      onApplyLeversToNumericStudio(res.query_spec);
    } catch (e) {
      setErrorMsg(formatApiError(e));
    } finally {
      setCompiling(false);
    }
  }

  async function runCompiledQuery() {
    if (!editableSpec) return;
    setRunning(true);
    setErrorMsg(null);
    try {
      const res = await v2<UniversityQueryRunResponse>("/university/query/runs", {
        method: "POST",
        body: {
          prompt: editableSpec.original_prompt,
          query_spec: editableSpec,
          context_university_id: contextUniversityId || editableSpec.focus_university_id || null,
          snapshot_id: snapshotId || editableSpec.snapshot_id || null,
          admission_year: admissionYear ? Number(admissionYear) : editableSpec.admission_year,
          population_id: usePopulationCohort && populationId ? populationId : null,
          cohort_size: cohortSize,
          seed,
          elasticity_preset: elasticityPreset,
        },
      });
      setActiveRun(res);
      setQueryRuns((prev) => [
        {
          run_id: res.run_id,
          prompt: res.prompt,
          intent: res.intent,
          snapshot_id: res.snapshot_id,
          focus_university_id: res.focus_university_id,
          focus_university_name: res.focus_university_name,
          osym_verified: res.osym_verified,
          coefficients_calibrated: res.coefficients_calibrated,
          headline: res.summary.headline,
          direct_answer: res.summary.direct_answer,
          created_at: res.created_at,
        },
        ...prev.filter((item) => item.run_id !== res.run_id),
      ]);
    } catch (e) {
      setErrorMsg(formatApiError(e));
    } finally {
      setRunning(false);
    }
  }

  async function inspectPastRun(runId: string) {
    setErrorMsg(null);
    try {
      const run = await v2<UniversityQueryRunResponse>(`/university/query/runs/${encodeURIComponent(runId)}`);
      setActiveRun(run);
      setEditableSpec(run.query_spec);
      setPrompt(run.prompt);
    } catch (e) {
      setErrorMsg(formatApiError(e));
    }
  }

  function updateSpecLever(
    key: "tuition_change_pct" | "ranking_change_pct" | "ranking_rank_delta" | "capacity_change_pct" | "aid_budget_change_pct",
    rawVal: string,
  ) {
    if (!editableSpec) return;
    const trimmed = rawVal.trim();
    const parsed = trimmed === "" ? null : Number(trimmed);
    const val = parsed !== null && Number.isFinite(parsed) ? parsed : key === "ranking_change_pct" || key === "ranking_rank_delta" ? null : 0;
    const nextSpec: UniversityQuerySpec = {
      ...editableSpec,
      levers: {
        ...editableSpec.levers,
        [key]: val,
      },
      comparison_variants:
        key === "ranking_change_pct" && typeof val === "number"
          ? editableSpec.comparison_variants.map((v) =>
              v.variant_id === "ranking_higher"
                ? {
                    ...v,
                    label: `Higher Ranking (+${Math.abs(val)}%)`,
                    intervention: { ...v.intervention, ranking_change_pct: Math.abs(val) },
                  }
                : v.variant_id === "ranking_lower"
                  ? {
                      ...v,
                      label: `Lower Ranking (-${Math.abs(val)}%)`,
                      intervention: { ...v.intervention, ranking_change_pct: -Math.abs(val) },
                    }
                  : v,
            )
          : editableSpec.comparison_variants,
      assumptions: editableSpec.assumptions.map((a) =>
        a.key === key ? { ...a, value: val, source: "user" as const } : a,
      ),
    };
    setEditableSpec(nextSpec);
    onApplyLeversToNumericStudio(nextSpec);
  }

  return (
    <div className="stack" aria-label="Prompt-driven university simulation studio">
      {/* Prompt Hero Card */}
      <section className="card stack" aria-labelledby="uq-hero-h">
        <div className="card-head">
          <div>
            <span className="eyebrow">Question-Driven Counterfactual Studio</span>
            <h2 id="uq-hero-h">Ask a University Policy Question</h2>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              className="button small"
              onClick={onToggleNumericStudio}
              aria-expanded={showNumericStudio}
            >
              {showNumericStudio ? "Hide Customize Parameters" : "Customize Parameters"}
            </button>
          </div>
        </div>

        <p className="small muted" style={{ margin: 0 }}>
          Ask in plain language (tuition changes, exogenous prestige/ranking shifts, quota/aid changes, revenue
          trade-offs, or competitor demand flows). Rivals stay fixed; uncalibrated elasticities report a Low / Medium /
          High range using Common Random Numbers (CRN).
        </p>

        {errorMsg ? <Notice tone="crit" title="Query error:">{errorMsg}</Notice> : null}

        {/* Target university + prompt */}
        <div className="field">
          <label htmlFor="uq-target-uni">Target university (&ldquo;this uni&rdquo;)</label>
          <select
            id="uq-target-uni"
            value={contextUniversityId}
            onChange={(e) => setContextUniversityId(e.target.value)}
          >
            {universityOptions.length === 0 ? <option value="">Demo catalog loading…</option> : null}
            {universityOptions.map((u) => (
              <option key={u.university_id} value={u.university_id}>
                {u.university_name} ({u.university_type})
              </option>
            ))}
          </select>
          <span className="small muted">
            {activeSnapshot
              ? `Connected to SQLite snapshot: ${activeSnapshot.source_filename} (${universityOptions.length} universities)`
              : regStatus && !regStatus.available
                ? `Built-in 5-university demo catalog (no SQLite DB found at ${regStatus.db_path})`
                : "Built-in demo catalog"}
          </span>
        </div>

        {/* Prompt box */}
        <div className="field">
          <label htmlFor="uq-prompt">Policy question</label>
          <textarea
            id="uq-prompt"
            rows={3}
            value={prompt}
            placeholder="e.g., How many students would apply to this uni if tuition increased by 30%?"
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>

        <details>
          <summary className="small">
            Advanced query options (Catalog: {snapshotId ? "SQLite snapshot" : "Demo"} · Cohort:{" "}
            {usePopulationCohort && populationId ? "TÜİK" : `Standalone ${cohortSize}`} · Elasticity: {elasticityPreset})
          </summary>
          <div className="details-body">
            <div className="grid-3">
              <div className="field">
                <label htmlFor="uq-snapshot">Catalog source</label>
                <select
                  id="uq-snapshot"
                  value={snapshotId}
                  onChange={(e) => {
                    setSnapshotId(e.target.value);
                    setAdmissionYear("");
                  }}
                >
                  <option value="">Built-in Demo Catalog</option>
                  {snapshots.map((s) => (
                    <option key={s.snapshot_id} value={s.snapshot_id}>
                      SQLite: {s.source_filename} ({s.counts.universities} unis)
                    </option>
                  ))}
                </select>
              </div>

              {snapshotId && selectedSnapshotYears.length > 0 ? (
                <div className="field">
                  <label htmlFor="uq-year">Admission year</label>
                  <select
                    id="uq-year"
                    value={admissionYear}
                    onChange={(e) => setAdmissionYear(e.target.value)}
                  >
                    <option value="">Latest year</option>
                    {selectedSnapshotYears.map((y) => (
                      <option key={y} value={String(y)}>
                        {y}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="field">
                  <label htmlFor="uq-cohort-source">Candidate cohort</label>
                  <select
                    id="uq-cohort-source"
                    value={usePopulationCohort && populationId ? "tuik" : "standalone"}
                    onChange={(e) => setUsePopulationCohort(e.target.value === "tuik")}
                  >
                    <option value="standalone">Standalone synthetic cohort ({cohortSize})</option>
                    <option value="tuik" disabled={!populationId}>
                      {populationId ? `TÜİK: ${populationLabel ?? populationId}` : "TÜİK population (none active)"}
                    </option>
                  </select>
                </div>
              )}

              <div className="field">
                <label htmlFor="uq-elasticity">Central elasticity preset &amp; cohort size</label>
                <div className="row" style={{ gap: 6 }}>
                  <select
                    id="uq-elasticity"
                    value={elasticityPreset}
                    onChange={(e) => setElasticityPreset(e.target.value as ElasticityPreset)}
                    style={{ flex: 1 }}
                  >
                    <option value="low">Low elasticity</option>
                    <option value="medium">Medium elasticity</option>
                    <option value="high">High elasticity</option>
                  </select>
                  <input
                    aria-label="Query cohort size"
                    type="number"
                    min={20}
                    max={2000}
                    step={20}
                    value={cohortSize}
                    onChange={(e) => setCohortSize(Math.max(20, Math.min(2000, Number(e.target.value) || 200)))}
                    style={{ width: 78 }}
                  />
                </div>
              </div>
            </div>
          </div>
        </details>

        {/* Example Question Chips */}
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }} aria-label="Example university policy questions">
          {EXAMPLE_PROMPTS.map((ex) => (
            <button
              key={ex}
              type="button"
              className="button small"
              onClick={() => {
                setPrompt(ex);
                void compilePlan(ex);
              }}
              disabled={compiling || running}
            >
              {ex}
            </button>
          ))}
        </div>

        <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button
            type="button"
            className="button primary"
            onClick={() => void compilePlan()}
            disabled={compiling || running || prompt.trim().length < 3}
          >
            {compiling ? "Compiling query plan…" : "Compile Query Plan"}
          </button>
          <span className="small muted">
            Zero simulation cost · Compiles question into editable assumptions before running CRN engine
          </span>
        </div>
      </section>

      {/* Reviewable Plan & Editable Assumptions Strip */}
      {plan && editableSpec ? (
        <section className="card stack" aria-labelledby="uq-plan-h">
          <div className="card-head">
            <div>
              <span className="eyebrow">Step 2 · Review &amp; Edit Query Plan</span>
              <h3 id="uq-plan-h">
                Compiled Plan: {editableSpec.intent} ({editableSpec.focus_university_name ?? "Targeted Programs"})
              </h3>
            </div>
            <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              <Badge tone="info">Mode: {editableSpec.simulation_mode}</Badge>
              <Badge tone="neutral">
                Programs: {plan.catalog.targeted_programs}/{plan.catalog.total_programs}
              </Badge>
              <Badge tone="neutral">Rivals fixed</Badge>
              <Badge tone="warn">osym_verified: {String(plan.osym_verified)}</Badge>
              <Badge tone="warn">coefficients_calibrated: {String(plan.coefficients_calibrated)}</Badge>
            </div>
          </div>

          {plan.blockers.length > 0 ? (
            <Notice tone="crit" title="Blocked — clarification needed before running:">
              <ul style={{ margin: "6px 0 0 0", paddingLeft: 18 }}>
                {plan.blockers.map((b, idx) => (
                  <li key={idx} className="small">
                    <strong>{b.code}:</strong> {b.message}
                  </li>
                ))}
              </ul>
              {editableSpec.unresolved_entities.some((u) => u.candidates.length > 0) ? (
                <div className="row" style={{ gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                  <span className="small">Did you mean:</span>
                  {editableSpec.unresolved_entities.flatMap((u) => u.candidates).map((c) =>
                    c.university_id ? (
                      <button
                        key={c.university_id}
                        type="button"
                        className="button small"
                        onClick={() => {
                          setContextUniversityId(c.university_id!);
                          void compilePlan(prompt, c.university_id!);
                        }}
                      >
                        Use {c.university_name ?? c.university_id}
                      </button>
                    ) : null,
                  )}
                </div>
              ) : null}
            </Notice>
          ) : null}

          {plan.warnings.length > 0 ? (
            <Notice tone="warn" title="Plan notes:">
              <ul style={{ margin: "6px 0 0 0", paddingLeft: 18 }}>
                {plan.warnings.map((w, idx) => (
                  <li key={idx} className="small">
                    {w}
                  </li>
                ))}
              </ul>
            </Notice>
          ) : null}

          {/* Editable lever fields synced into QuerySpec */}
          <div className="grid-4">
            <div className="field">
              <label htmlFor="uq-edit-tuition">Tuition change (%)</label>
              <input
                id="uq-edit-tuition"
                type="number"
                step={5}
                min={-100}
                max={300}
                value={editableSpec.levers.tuition_change_pct ?? 0}
                onChange={(e) => updateSpecLever("tuition_change_pct", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="uq-edit-rank-pct">Exogenous ranking shift (%)</label>
              <input
                id="uq-edit-rank-pct"
                type="number"
                step={5}
                min={-95}
                max={200}
                placeholder="none"
                value={editableSpec.levers.ranking_change_pct ?? ""}
                onChange={(e) => updateSpecLever("ranking_change_pct", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="uq-edit-aid">Scholarship / aid budget (%)</label>
              <input
                id="uq-edit-aid"
                type="number"
                step={5}
                min={-100}
                max={200}
                value={editableSpec.levers.aid_budget_change_pct ?? 0}
                onChange={(e) => updateSpecLever("aid_budget_change_pct", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="uq-edit-quota">Quota / capacity change (%)</label>
              <input
                id="uq-edit-quota"
                type="number"
                step={5}
                min={-100}
                max={100}
                value={editableSpec.levers.capacity_change_pct ?? 0}
                onChange={(e) => updateSpecLever("capacity_change_pct", e.target.value)}
              />
            </div>
          </div>

          {editableSpec.assumptions.length > 0 ? (
            <div className="stack" style={{ gap: 4 }}>
              <strong className="small">Compiled Assumptions &amp; Provenance</strong>
              <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                {editableSpec.assumptions.map((a) => (
                  <Badge key={a.key} tone={a.source === "user" ? "good" : "neutral"}>
                    {a.label}: {String(a.value)}
                    {a.unit ? ` ${a.unit}` : ""} ({a.source})
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          {editableSpec.comparison_variants.length > 0 ? (
            <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              <span className="small muted">Comparison variants:</span>
              {editableSpec.comparison_variants.map((v) => (
                <Badge key={v.variant_id} tone={v.is_baseline ? "neutral" : "info"}>
                  {v.label}
                </Badge>
              ))}
            </div>
          ) : null}

          <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              className="button primary"
              onClick={() => void runCompiledQuery()}
              disabled={!plan.executable || running}
            >
              {running ? "Running counterfactual simulation…" : "Run Counterfactual Simulation"}
            </button>
            <button
              type="button"
              className="button"
              onClick={() => {
                onApplyLeversToNumericStudio(editableSpec);
                if (!showNumericStudio) onToggleNumericStudio();
              }}
            >
              Apply to Numeric Controls
            </button>
            <span className="small muted">
              Plan hash: <code>{plan.plan_hash}</code> · Seed: {seed}
            </span>
          </div>
        </section>
      ) : null}

      {/* Question-Specific Answer + Tailored Statistics */}
      {activeRun ? (
        <div className="stack">
          <ExecutiveAnswerCard run={activeRun} />
          <UniversityQueryStats sections={activeRun.detailed_statistics} />
        </div>
      ) : null}

      {/* Past Query History */}
      {queryRuns.length > 0 ? (
        <section className="card stack" aria-labelledby="uq-history-h">
          <div className="card-head">
            <h3 id="uq-history-h">Recent University Question Runs</h3>
            <span className="small muted">{fmtInt(queryRuns.length)} saved</span>
          </div>
          <div className="stack" style={{ gap: 6 }}>
            {queryRuns.slice(0, 6).map((item) => (
              <div
                key={item.run_id}
                className="row"
                style={{
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "6px 8px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                }}
              >
                <div className="stack" style={{ gap: 2 }}>
                  <span className="small">
                    <strong>{item.prompt}</strong> <Badge tone="info">{item.intent}</Badge>
                  </span>
                  <span className="small muted">{item.headline}</span>
                </div>
                <button
                  type="button"
                  className="button small"
                  onClick={() => void inspectPastRun(item.run_id)}
                >
                  Inspect
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
