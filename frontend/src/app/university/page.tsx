"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { describeDetails, toApiError } from "@/lib/api/client";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { StatTile } from "@/components/StatTile";
import { Badge } from "@/components/StatusBadge";
import {
  RetentionTrajectoryChart,
  TuitionSweepChart,
} from "@/components/university/UniversityCharts";
import { UniversityQueryStudio } from "@/components/university/UniversityQueryStudio";
import {
  v2,
  type PlacementProgramsCatalog,
  type PlacementRunResponse,
  type UniversityQueryRunListItem,
  type UniversityQuerySpec,
  type UniversityRegistryStatus,
  type UniversityRunResponse,
  type UniversitySweepResponse,
} from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { usePopulation } from "@/lib/population";

function fmtSigned(value: number | null | undefined, digits = 2, suffix = ""): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

function formatErr(err: unknown): string {
  const apiErr = toApiError(err);
  const details = describeDetails(apiErr.details);
  return `${apiErr.message}${details ? ` (${details})` : ""}`;
}

function NumField({
  value,
  onChange,
  min,
  max,
  step,
  disabled,
  style,
}: {
  value: number;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  style?: React.CSSProperties;
}) {
  const [raw, setRaw] = useState<string>(String(value));
  useEffect(() => {
    setRaw(String(value));
  }, [value]);
  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      style={style}
      value={raw}
      onChange={(e) => {
        const nextRaw = e.target.value;
        setRaw(nextRaw);
        const parsed = Number(nextRaw);
        if (nextRaw.trim() !== "" && Number.isFinite(parsed)) {
          onChange(parsed);
        }
      }}
      onBlur={() => {
        const parsed = Number(raw);
        if (raw.trim() === "" || !Number.isFinite(parsed)) {
          setRaw(String(value));
          return;
        }
        let clamped = parsed;
        if (min !== undefined && clamped < min) clamped = min;
        if (max !== undefined && clamped > max) clamped = max;
        setRaw(String(clamped));
        if (clamped !== value) onChange(clamped);
      }}
    />
  );
}

type ScenarioDetail = {
  scenario_id: string;
  name: string;
  policy?: {
    category?: string;
    parameters?: {
      custom_details?: {
        simulation_mode?: string;
        university_intervention?: {
          capacity_change_pct?: number | null;
          tuition_change_pct?: number | null;
          aid_budget_change_pct?: number | null;
          installment_count?: number | null;
          attendance_min_pct?: number | null;
          grading_difficulty_shift?: number | null;
          semester_count?: number | null;
          replications?: number | null;
          rank_threshold_overrides?: Record<string, number> | null;
        };
      };
    };
  };
};

function UniversitySimulatorWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialScenario = searchParams.get("scenario") ?? "";
  const { population } = usePopulation();

  const [tab, setTab] = useState<"placement" | "multiterm">("placement");
  const [catalog, setCatalog] = useState<PlacementProgramsCatalog | null>(null);
  const [placementRuns, setPlacementRuns] = useState<PlacementRunResponse[]>([]);
  const [universityRuns, setUniversityRuns] = useState<UniversityRunResponse[]>([]);
  const [activeScenarioId, setActiveScenarioId] = useState<string>(initialScenario);
  const [linkedScenario, setLinkedScenario] = useState<ScenarioDetail | null>(null);
  const [interventionDirty, setInterventionDirty] = useState<boolean>(false);

  // Placement form controls (Milestone 1)
  const [useTuikCohort, setUseTuikCohort] = useState(false);
  const [placeSize, setPlaceSize] = useState(200);
  const [placeQuotaPct, setPlaceQuotaPct] = useState(-15);
  const [placeTuitionPct, setPlaceTuitionPct] = useState(0);
  const [placeAidPct, setPlaceAidPct] = useState(0);
  const [placeInstallments, setPlaceInstallments] = useState(1);
  const [placeBarajEng, setPlaceBarajEng] = useState(300000);
  const [activePlacement, setActivePlacement] = useState<PlacementRunResponse | null>(null);
  const [runningPlacement, setRunningPlacement] = useState(false);

  // Multi-semester form controls (Milestone 2)
  const [linkedPlacementId, setLinkedPlacementId] = useState<string>("");
  const [uniSize, setUniSize] = useState(200);
  const [uniSemesters, setUniSemesters] = useState(4);
  const [uniReplications, setUniReplications] = useState(8);
  const [uniTuitionPct, setUniTuitionPct] = useState(20);
  const [uniAidPct, setUniAidPct] = useState(0);
  const [uniInstallments, setUniInstallments] = useState(1);
  const [uniAttendanceMin, setUniAttendanceMin] = useState(70);
  const [uniGradingShift, setUniGradingShift] = useState(0);
  const [uniCapacityPct, setUniCapacityPct] = useState(0);
  const [activeUniversity, setActiveUniversity] = useState<UniversityRunResponse | null>(null);
  const [runningUniversity, setRunningUniversity] = useState(false);
  const [sweepData, setSweepData] = useState<UniversitySweepResponse | null>(null);
  const [runningSweep, setRunningSweep] = useState(false);
  const [inspectingId, setInspectingId] = useState<string | null>(null);
  const [regStatus, setRegStatus] = useState<UniversityRegistryStatus | null>(null);
  const [queryRuns, setQueryRuns] = useState<UniversityQueryRunListItem[]>([]);
  const [showNumericStudio, setShowNumericStudio] = useState<boolean>(() => Boolean(initialScenario));

  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const applyQuerySpecToNumericStudio = (spec: UniversityQuerySpec) => {
    const lev = spec.levers ?? {};
    if (typeof lev.capacity_change_pct === "number") {
      setPlaceQuotaPct(lev.capacity_change_pct);
      setUniCapacityPct(lev.capacity_change_pct);
    }
    if (typeof lev.tuition_change_pct === "number") {
      setPlaceTuitionPct(lev.tuition_change_pct);
      setUniTuitionPct(lev.tuition_change_pct);
    }
    if (typeof lev.aid_budget_change_pct === "number") {
      setPlaceAidPct(lev.aid_budget_change_pct);
      setUniAidPct(lev.aid_budget_change_pct);
    }
    if (typeof lev.installment_count === "number") {
      setPlaceInstallments(lev.installment_count);
      setUniInstallments(lev.installment_count);
    }
    if (typeof lev.attendance_min_pct === "number") setUniAttendanceMin(lev.attendance_min_pct);
    if (typeof lev.grading_difficulty_shift === "number") setUniGradingShift(lev.grading_difficulty_shift);
    if (typeof lev.semester_count === "number") setUniSemesters(lev.semester_count);
    if (typeof lev.replications === "number") setUniReplications(lev.replications);
    if (typeof spec.cohort_size === "number") {
      setPlaceSize(spec.cohort_size);
      setUniSize(spec.cohort_size);
    }
    if (spec.simulation_mode === "retention") {
      setTab("multiterm");
    } else if (spec.simulation_mode === "placement") {
      setTab("placement");
    }
  };

  useEffect(() => {
    setActiveScenarioId(initialScenario);
    setInterventionDirty(false);
    if (initialScenario) {
      setShowNumericStudio(true);
    } else {
      setLinkedScenario(null);
    }
  }, [initialScenario]);

  useEffect(() => {
    let cancelled = false;
    async function loadInitial() {
      try {
        const [cat, pList, uList, reg, qList, sc] = await Promise.all([
          v2<PlacementProgramsCatalog>("/placement/programs"),
          v2<{ items: PlacementRunResponse[] }>("/placement/runs"),
          v2<{ items: UniversityRunResponse[] }>("/university/runs"),
          v2<UniversityRegistryStatus>("/university-registry/status").catch(() => null),
          v2<{ items: UniversityQueryRunListItem[] }>("/university/query/runs").catch(() => null),
          initialScenario
            ? v2<ScenarioDetail>(`/scenarios/${encodeURIComponent(initialScenario)}`).catch(() => null)
            : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setCatalog(cat);
        setPlacementRuns(pList.items);
        setUniversityRuns(uList.items);
        if (reg && typeof reg.available === "boolean") setRegStatus(reg);
        if (qList && Array.isArray(qList.items)) setQueryRuns(qList.items);
        if (sc) {
          setLinkedScenario(sc);
          const custom = sc.policy?.parameters?.custom_details;
          const ui = custom?.university_intervention;
          if (custom?.simulation_mode === "university_decision_hybrid") {
            setTab("multiterm");
          }
          if (ui) {
            if (typeof ui.capacity_change_pct === "number") {
              setPlaceQuotaPct(ui.capacity_change_pct);
              setUniCapacityPct(ui.capacity_change_pct);
            }
            if (typeof ui.tuition_change_pct === "number") {
              setPlaceTuitionPct(ui.tuition_change_pct);
              setUniTuitionPct(ui.tuition_change_pct);
            }
            if (typeof ui.aid_budget_change_pct === "number") {
              setPlaceAidPct(ui.aid_budget_change_pct);
              setUniAidPct(ui.aid_budget_change_pct);
            }
            if (typeof ui.installment_count === "number") {
              setPlaceInstallments(ui.installment_count);
              setUniInstallments(ui.installment_count);
            }
            if (typeof ui.attendance_min_pct === "number") setUniAttendanceMin(ui.attendance_min_pct);
            if (typeof ui.grading_difficulty_shift === "number") setUniGradingShift(ui.grading_difficulty_shift);
            if (typeof ui.semester_count === "number") setUniSemesters(ui.semester_count);
            if (typeof ui.replications === "number") setUniReplications(ui.replications);
            if (typeof ui.rank_threshold_overrides?.engineering === "number") {
              setPlaceBarajEng(ui.rank_threshold_overrides.engineering);
            }
          }
        }
        if (pList.items.length > 0) {
          const detail = await v2<PlacementRunResponse>(`/placement/runs/${pList.items[0].run_id}`);
          if (!cancelled) setActivePlacement(detail);
        }
        if (uList.items.length > 0) {
          const detail = await v2<UniversityRunResponse>(`/university/runs/${uList.items[0].run_id}`);
          if (!cancelled) setActiveUniversity(detail);
        }
      } catch (err) {
        if (!cancelled) setErrorMsg(formatErr(err));
      }
    }
    loadInitial();
    return () => {
      cancelled = true;
    };
  }, [initialScenario]);

  const handleRunPlacement = async () => {
    setErrorMsg(null);
    setRunningPlacement(true);
    try {
      const res = await v2<PlacementRunResponse>("/placement/runs", {
        method: "POST",
        body: {
          scenario_id: activeScenarioId || null,
          population_id: useTuikCohort && population ? population.population_id : null,
          cohort_size: placeSize,
          seed: 42,
          compare_baseline: true,
          intervention:
            activeScenarioId && !interventionDirty
              ? null
              : {
                  capacity_change_pct: placeQuotaPct,
                  tuition_change_pct: placeTuitionPct,
                  aid_budget_change_pct: placeAidPct,
                  installment_count: placeInstallments,
                  affordability_filter_mode: placeTuitionPct !== 0 || placeAidPct !== 0 ? "hard_exclude" : "none",
                  rank_threshold_overrides: { engineering: placeBarajEng },
                },
        },
      });
      setActivePlacement(res);
      setPlacementRuns((prev) => [res, ...prev.filter((r) => r.run_id !== res.run_id)]);
    } catch (err) {
      setErrorMsg(formatErr(err));
    } finally {
      setRunningPlacement(false);
    }
  };

  const handleRunUniversity = async (overridePlacementId?: string) => {
    setErrorMsg(null);
    setRunningUniversity(true);
    const chosenPlacementId = overridePlacementId !== undefined ? overridePlacementId : linkedPlacementId;
    try {
      const res = await v2<UniversityRunResponse>("/university/runs", {
        method: "POST",
        body: {
          scenario_id: activeScenarioId || null,
          placement_run_id: chosenPlacementId || null,
          cohort_size: uniSize,
          semester_count: uniSemesters,
          replications: uniReplications,
          seed: 42,
          compare_baseline: true,
          intervention:
            activeScenarioId && !interventionDirty
              ? null
              : {
                  tuition_change_pct: uniTuitionPct,
                  aid_budget_change_pct: uniAidPct,
                  installment_count: uniInstallments,
                  attendance_min_pct: uniAttendanceMin,
                  grading_difficulty_shift: uniGradingShift,
                  capacity_change_pct: uniCapacityPct,
                  semester_count: uniSemesters,
                  replications: uniReplications,
                },
        },
      });
      setActiveUniversity(res);
      setUniversityRuns((prev) => [res, ...prev.filter((r) => r.run_id !== res.run_id)]);
    } catch (err) {
      setErrorMsg(formatErr(err));
    } finally {
      setRunningUniversity(false);
    }
  };

  const handleRunSweep = async () => {
    setErrorMsg(null);
    setRunningSweep(true);
    try {
      const res = await v2<UniversitySweepResponse>("/university/sweep", {
        method: "POST",
        body: {
          placement_run_id: linkedPlacementId || null,
          cohort_size: Math.min(uniSize, 200),
          semester_count: uniSemesters,
          replications: Math.min(uniReplications, 8),
          seed: 42,
          tuition_pcts: [0, 5, 10, 15, 20, 25, 30],
          aid_budget_pct: uniAidPct !== 0 ? uniAidPct : null,
        },
      });
      setSweepData(res);
    } catch (err) {
      setErrorMsg(formatErr(err));
    } finally {
      setRunningSweep(false);
    }
  };

  const handleHandoffToMultiTerm = async (placementRunId: string) => {
    setLinkedPlacementId(placementRunId);
    setTab("multiterm");
    await handleRunUniversity(placementRunId);
  };

  const activeDisclaimer =
    tab === "multiterm"
      ? (activeUniversity?.disclaimer ??
          activeUniversity?.comparison?.disclaimer ??
          activeUniversity?.summary?.disclaimer)
      : (activePlacement?.disclaimer ??
          activePlacement?.result?.comparison?.disclaimer ??
          activePlacement?.summary?.disclaimer);

  const disclaimerText =
    activeDisclaimer ??
    activeUniversity?.disclaimer ??
    activeUniversity?.summary?.disclaimer ??
    activePlacement?.disclaimer ??
    activePlacement?.summary?.disclaimer ??
    catalog?.disclaimer ??
    "HYPOTHETICAL / UNCALIBRATED PROTOTYPE: Uses synthetic cohorts, general quotas, and uncalibrated default coefficients. Does not claim exact official ÖSYM placement reproduction.";

  const pMetrics = activePlacement?.result?.placement_result?.aggregate_metrics as Record<string, number | null> | undefined;
  const pComp = activePlacement?.result?.comparison;
  const uEffects = activeUniversity?.comparison?.policy_effects;

  const clearLinkedScenario = () => {
    setActiveScenarioId("");
    setLinkedScenario(null);
    setInterventionDirty(false);
    const next = new URLSearchParams(searchParams.toString());
    next.delete("scenario");
    const qs = next.toString();
    router.replace(qs ? `/university?${qs}` : "/university", { scroll: false });
  };

  return (
    <div className="stack">
      <Notice tone="warn" title="Hypothetical / Uncalibrated Prototype (osym_verified = false):">
        {disclaimerText}
      </Notice>

      {activeScenarioId ? (
        <Notice tone="info" title={`Linked scenario: ${linkedScenario?.name ?? activeScenarioId}`}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <span className="small">
              {interventionDirty
                ? "Using modified slider parameters alongside the linked scenario metadata."
                : "Pre-filled from the linked scenario; untouched runs apply its full configured intervention."}
            </span>
            <button type="button" className="button small" onClick={clearLinkedScenario}>
              Clear scenario
            </button>
          </div>
        </Notice>
      ) : null}

      {errorMsg ? (
        <Notice tone="crit" title="Simulation error:">
          {errorMsg}
        </Notice>
      ) : null}

      <UniversityQueryStudio
        catalog={catalog}
        regStatus={regStatus}
        populationId={population?.population_id ?? null}
        populationLabel={population?.label ?? null}
        initialRuns={queryRuns}
        onApplyLeversToNumericStudio={applyQuerySpecToNumericStudio}
        showNumericStudio={showNumericStudio}
        onToggleNumericStudio={() => setShowNumericStudio((v) => !v)}
      />

      {showNumericStudio ? (
        <>
      <div className="row" role="tablist" aria-label="University simulation modules">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "placement"}
          className={tab === "placement" ? "button primary" : "button"}
          onClick={() => setTab("placement")}
        >
          1. Central Placement &amp; Quotas (Milestone 1)
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "multiterm"}
          className={tab === "multiterm" ? "button primary" : "button"}
          onClick={() => setTab("multiterm")}
        >
          2. Multi-Semester Policy Dynamics (Milestone 2)
        </button>
      </div>

      {tab === "placement" ? (
        <div className="stack">
          <section className="card stack">
            <div className="card-head">
              <h2>Offline Deterministic Placement Controls (General Quotas Only)</h2>
              <Badge tone="neutral" glyph="!">osym_verified: false</Badge>
            </div>
            <div className="grid-3">
              <label className="stack">
                <span className="small muted">Candidate Cohort Size</span>
                <NumField
                  min={20}
                  max={2000}
                  value={placeSize}
                  onChange={setPlaceSize}
                />
              </label>
              <label className="stack">
                <span className="small muted">Quota Change % (UNI-005)</span>
                <NumField
                  min={-90}
                  max={200}
                  value={placeQuotaPct}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setPlaceQuotaPct(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Engineering Rank Baraj (≤)</span>
                <NumField
                  min={10000}
                  max={1000000}
                  step={10000}
                  value={placeBarajEng}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setPlaceBarajEng(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Tuition Change % (UNI-001)</span>
                <NumField
                  min={-100}
                  max={300}
                  value={placeTuitionPct}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setPlaceTuitionPct(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Need-Based Aid % (UNI-002)</span>
                <NumField
                  min={-100}
                  max={500}
                  value={placeAidPct}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setPlaceAidPct(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Installment Count (UNI-006)</span>
                <NumField
                  min={1}
                  max={12}
                  value={placeInstallments}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setPlaceInstallments(n);
                  }}
                />
              </label>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <label className="row small">
                <input
                  type="checkbox"
                  checked={useTuikCohort && Boolean(population)}
                  disabled={!population}
                  onChange={(e) => setUseTuikCohort(e.target.checked)}
                />
                <span>
                  Anchor candidates to active TÜİK population{" "}
                  {population ? `(${population.label})` : "(generate a population first, or run standalone synthetic)"}
                </span>
              </label>
              <button
                type="button"
                className="button primary"
                disabled={runningPlacement}
                onClick={handleRunPlacement}
              >
                {runningPlacement ? "Running Placement…" : "Run Counterfactual Placement"}
              </button>
            </div>
          </section>

          {activePlacement?.result ? (
            <section className="card stack">
              <div className="card-head">
                <div>
                  <h2>Placement Results ({activePlacement.run_id})</h2>
                  <p className="small muted">{activePlacement.summary.headline}</p>
                </div>
                <button
                  type="button"
                  className="button"
                  onClick={() => handleHandoffToMultiTerm(activePlacement.run_id)}
                >
                  Handoff Admitted Cohort ({activePlacement.result.admitted_count}) → Multi-Semester Sim
                </button>
              </div>
              <div className="tiles">
                <StatTile
                  label="Placed Candidates"
                  value={fmtInt(pMetrics?.placed_count ?? null)}
                  sub={`Rate: ${typeof pMetrics?.placement_rate === "number" ? `${(pMetrics.placement_rate * 100).toFixed(1)}%` : "—"}`}
                />
                <StatTile
                  label="1st-Choice Placement"
                  value={typeof pMetrics?.first_choice_rate === "number" ? `${(pMetrics.first_choice_rate * 100).toFixed(1)}%` : "—"}
                  sub={`${fmtInt(pMetrics?.first_choice_count ?? null)} first-choice matches`}
                />
                <StatTile
                  label="Seat Utilization"
                  value={typeof pMetrics?.seat_utilization_rate === "number" ? `${(pMetrics.seat_utilization_rate * 100).toFixed(1)}%` : "—"}
                  sub={`${fmtInt(pMetrics?.total_filled ?? null)} / ${fmtInt(pMetrics?.total_capacity ?? null)} seats`}
                />
                <StatTile
                  label="Displaced / Newly Placed"
                  value={pComp ? `${pComp.transitions.displaced_to_unplaced} / +${pComp.transitions.newly_placed}` : "—"}
                  sub={pComp ? `Rank Δ improved: ${pComp.transitions.improved_preference}` : "No baseline delta"}
                />
              </div>

              {pComp?.program_deltas?.length ? (
                <div className="table-wrap">
                  <table>
                    <caption>Program Cutoff &amp; Capacity Shifts (General Quotas Only)</caption>
                    <thead>
                      <tr>
                        <th scope="col">Program</th>
                        <th scope="col" className="num">Base Cap</th>
                        <th scope="col" className="num">Policy Cap</th>
                        <th scope="col" className="num">Filled</th>
                        <th scope="col" className="num">Base Cutoff</th>
                        <th scope="col" className="num">Policy Cutoff</th>
                        <th scope="col" className="num">Cutoff Δ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pComp.program_deltas.map((row) => (
                        <tr key={row.program_id}>
                          <td className="mono">{row.program_id}</td>
                          <td className="num">{row.baseline_capacity}</td>
                          <td className="num">{row.policy_capacity}</td>
                          <td className="num">{row.policy_filled}</td>
                          <td className="num">{row.baseline_cutoff_score !== null ? row.baseline_cutoff_score.toFixed(2) : "—"}</td>
                          <td className="num">{row.policy_cutoff_score !== null ? row.policy_cutoff_score.toFixed(2) : "—"}</td>
                          <td className="num">{fmtSigned(row.cutoff_score_delta, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : (
        <div className="stack">
          <section className="card stack">
            <div className="card-head">
              <h2>Multi-Semester Policy Controls (UNI-001 to UNI-006)</h2>
              <Badge tone="neutral" glyph="!">coefficients_calibrated: false</Badge>
            </div>
            <div className="grid-3">
              <label className="stack">
                <span className="small muted">Input Cohort Source</span>
                <select
                  value={linkedPlacementId}
                  onChange={(e) => setLinkedPlacementId(e.target.value)}
                >
                  <option value="">Synthetic Multi-Year Cohort (Years 1–4)</option>
                  {placementRuns.map((pr) => (
                    <option key={pr.run_id} value={pr.run_id}>
                      Placement Handoff: {pr.run_id} ({pr.created_at.slice(0, 19)})
                    </option>
                  ))}
                </select>
              </label>
              <label className="stack">
                <span className="small muted">Semesters</span>
                <NumField
                  min={1}
                  max={8}
                  value={uniSemesters}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniSemesters(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">CRN Replications</span>
                <NumField
                  min={1}
                  max={100}
                  value={uniReplications}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniReplications(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Tuition Change % (UNI-001)</span>
                <NumField
                  min={-100}
                  max={300}
                  value={uniTuitionPct}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniTuitionPct(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Aid Budget % (UNI-002)</span>
                <NumField
                  min={-100}
                  max={500}
                  value={uniAidPct}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniAidPct(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Installments (UNI-006)</span>
                <NumField
                  min={1}
                  max={12}
                  value={uniInstallments}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniInstallments(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Min Attendance % (UNI-003)</span>
                <NumField
                  min={0}
                  max={100}
                  value={uniAttendanceMin}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniAttendanceMin(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Grading Difficulty Shift (UNI-004)</span>
                <NumField
                  min={-2}
                  max={2}
                  step={0.1}
                  value={uniGradingShift}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniGradingShift(n);
                  }}
                />
              </label>
              <label className="stack">
                <span className="small muted">Course Seats % (UNI-005)</span>
                <NumField
                  min={-90}
                  max={200}
                  value={uniCapacityPct}
                  onChange={(n) => {
                    setInterventionDirty(true);
                    setUniCapacityPct(n);
                  }}
                />
              </label>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <label className="row small">
                <span>Cohort Size (when not using Placement Handoff):</span>
                <NumField
                  min={20}
                  max={1000}
                  style={{ width: 90 }}
                  disabled={Boolean(linkedPlacementId)}
                  value={uniSize}
                  onChange={setUniSize}
                />
              </label>
              <div className="row">
                <button
                  type="button"
                  className="button"
                  disabled={runningSweep}
                  onClick={handleRunSweep}
                >
                  {runningSweep ? "Sweeping…" : "Run 0–30% Tuition Sweep"}
                </button>
                <button
                  type="button"
                  className="button primary"
                  disabled={runningUniversity}
                  onClick={() => handleRunUniversity()}
                >
                  {runningUniversity ? "Simulating Terms…" : "Run Paired CRN Simulation"}
                </button>
              </div>
            </div>
          </section>

          {activeUniversity ? (
            <section className="card stack">
              <div className="card-head">
                <div>
                  <h2>Multi-Semester Policy Impact ({activeUniversity.run_id})</h2>
                  <p className="small muted">{activeUniversity.summary.headline}</p>
                </div>
              </div>
              {uEffects ? (
                <div className="tiles">
                  <StatTile
                    label="Retention Delta"
                    value={fmtSigned(
                      typeof uEffects.cumulative_retention_rate?.mean === "number"
                        ? uEffects.cumulative_retention_rate.mean * 100
                        : null,
                      2,
                      " pp",
                    )}
                    sub={`Policy: ${typeof uEffects.cumulative_retention_rate?.policy_mean === "number" ? `${(uEffects.cumulative_retention_rate.policy_mean * 100).toFixed(2)}%` : "—"}`}
                  />
                  <StatTile
                    label="Dropout Delta (Withdrawn)"
                    value={fmtSigned(uEffects.final_withdrawn_dropout?.mean, 2)}
                    sub={`Baseline mean: ${uEffects.final_withdrawn_dropout?.baseline_mean?.toFixed(2) ?? "—"}`}
                  />
                  <StatTile
                    label="Stop-Out Delta (Paused)"
                    value={fmtSigned(uEffects.final_paused_stop_out?.mean, 2)}
                    sub={`Baseline mean: ${uEffects.final_paused_stop_out?.baseline_mean?.toFixed(2) ?? "—"}`}
                  />
                  <StatTile
                    label="Net Revenue Delta"
                    value={fmtSigned(
                      typeof uEffects.total_net_tuition_revenue?.mean === "number"
                        ? uEffects.total_net_tuition_revenue.mean / 1_000_000
                        : null,
                      2,
                      "M TL",
                    )}
                    sub={`${activeUniversity.comparison?.replications ?? 1} CRN replications`}
                  />
                </div>
              ) : null}

              {activeUniversity.comparison ? (
                <RetentionTrajectoryChart
                  baseline={activeUniversity.comparison.baseline_trajectory}
                  policy={activeUniversity.comparison.policy_trajectory}
                />
              ) : null}
            </section>
          ) : null}

          {sweepData ? (
            <section className="card stack">
              <TuitionSweepChart rows={sweepData.rows} />
            </section>
          ) : null}
        </div>
      )}

      {placementRuns.length > 0 || universityRuns.length > 0 ? (
        <section className="card stack">
          <h3>Persisted Local Run History (SQLite)</h3>
          <div className="grid-2">
            <div>
              <h4 className="small muted">Placement Runs ({placementRuns.length})</h4>
              <ul className="stack small">
                {placementRuns.slice(0, 5).map((r) => (
                  <li key={r.run_id} className="row" style={{ justifyContent: "space-between" }}>
                    <span className="mono">{r.run_id}</span>
                    <button
                      type="button"
                      className="button small"
                      disabled={inspectingId === r.run_id}
                      onClick={async () => {
                        setErrorMsg(null);
                        setInspectingId(r.run_id);
                        try {
                          const detail = await v2<PlacementRunResponse>(`/placement/runs/${r.run_id}`);
                          setActivePlacement(detail);
                          setTab("placement");
                        } catch (err) {
                          setErrorMsg(formatErr(err));
                        } finally {
                          setInspectingId(null);
                        }
                      }}
                    >
                      {inspectingId === r.run_id ? "Loading…" : "Inspect"}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="small muted">Multi-Semester Policy Runs ({universityRuns.length})</h4>
              <ul className="stack small">
                {universityRuns.slice(0, 5).map((r) => (
                  <li key={r.run_id} className="row" style={{ justifyContent: "space-between" }}>
                    <span className="mono">{r.run_id}</span>
                    <button
                      type="button"
                      className="button small"
                      disabled={inspectingId === r.run_id}
                      onClick={async () => {
                        setErrorMsg(null);
                        setInspectingId(r.run_id);
                        try {
                          const detail = await v2<UniversityRunResponse>(`/university/runs/${r.run_id}`);
                          setActiveUniversity(detail);
                          setTab("multiterm");
                        } catch (err) {
                          setErrorMsg(formatErr(err));
                        } finally {
                          setInspectingId(null);
                        }
                      }}
                    >
                      {inspectingId === r.run_id ? "Loading…" : "Inspect"}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      ) : null}
        </>
      ) : null}
    </div>
  );
}

export default function UniversityPage() {
  return (
    <>
      <PageHeader title="University Decision & Placement Simulator">
        Counterfactual ÖSYM-style placement (general quotas) and multi-semester retention simulation with Common Random Numbers.
      </PageHeader>
      <Suspense fallback={<div className="card">Loading university simulation studio…</div>}>
        <UniversitySimulatorWorkspace />
      </Suspense>
    </>
  );
}
