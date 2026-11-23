"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { StatTile } from "@/components/StatTile";
import { Badge } from "@/components/StatusBadge";
import {
  RetentionTrajectoryChart,
  TuitionSweepChart,
} from "@/components/university/UniversityCharts";
import {
  v2,
  type PlacementProgramsCatalog,
  type PlacementRunResponse,
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

function UniversitySimulatorWorkspace() {
  const searchParams = useSearchParams();
  const initialScenario = searchParams.get("scenario") ?? "";
  const { population } = usePopulation();

  const [tab, setTab] = useState<"placement" | "multiterm">("placement");
  const [catalog, setCatalog] = useState<PlacementProgramsCatalog | null>(null);
  const [placementRuns, setPlacementRuns] = useState<PlacementRunResponse[]>([]);
  const [universityRuns, setUniversityRuns] = useState<UniversityRunResponse[]>([]);

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

  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadInitial() {
      try {
        const [cat, pList, uList] = await Promise.all([
          v2<PlacementProgramsCatalog>("/placement/programs"),
          v2<{ items: PlacementRunResponse[] }>("/placement/runs"),
          v2<{ items: UniversityRunResponse[] }>("/university/runs"),
        ]);
        if (cancelled) return;
        setCatalog(cat);
        setPlacementRuns(pList.items);
        setUniversityRuns(uList.items);
        if (pList.items.length > 0) {
          const detail = await v2<PlacementRunResponse>(`/placement/runs/${pList.items[0].run_id}`);
          if (!cancelled) setActivePlacement(detail);
        }
        if (uList.items.length > 0) {
          const detail = await v2<UniversityRunResponse>(`/university/runs/${uList.items[0].run_id}`);
          if (!cancelled) setActiveUniversity(detail);
        }
      } catch (err) {
        if (!cancelled) setErrorMsg(err instanceof Error ? err.message : "Failed to load university workspace.");
      }
    }
    loadInitial();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRunPlacement = async () => {
    setErrorMsg(null);
    setRunningPlacement(true);
    try {
      const res = await v2<PlacementRunResponse>("/placement/runs", {
        method: "POST",
        body: {
          scenario_id: initialScenario || null,
          population_id: useTuikCohort && population ? population.population_id : null,
          cohort_size: placeSize,
          seed: 42,
          compare_baseline: true,
          intervention: {
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
      setErrorMsg(err instanceof Error ? err.message : "Placement run failed.");
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
          scenario_id: initialScenario || null,
          placement_run_id: chosenPlacementId || null,
          cohort_size: uniSize,
          semester_count: uniSemesters,
          replications: uniReplications,
          seed: 42,
          compare_baseline: true,
          intervention: {
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
      setErrorMsg(err instanceof Error ? err.message : "University multi-semester run failed.");
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
      setErrorMsg(err instanceof Error ? err.message : "Tuition sensitivity sweep failed.");
    } finally {
      setRunningSweep(false);
    }
  };

  const handleHandoffToMultiTerm = async (placementRunId: string) => {
    setLinkedPlacementId(placementRunId);
    setTab("multiterm");
    await handleRunUniversity(placementRunId);
  };

  const disclaimerText =
    activeUniversity?.disclaimer ??
    activePlacement?.disclaimer ??
    catalog?.disclaimer ??
    "HYPOTHETICAL / UNCALIBRATED PROTOTYPE: Uses synthetic cohorts, general quotas, and uncalibrated default coefficients. Does not claim exact official ÖSYM placement reproduction.";

  const pMetrics = activePlacement?.result?.placement_result?.aggregate_metrics as Record<string, number | null> | undefined;
  const pComp = activePlacement?.result?.comparison;
  const uEffects = activeUniversity?.comparison?.policy_effects;

  return (
    <div className="stack">
      <Notice tone="warn" title="Hypothetical / Uncalibrated Prototype (osym_verified = false):">
        {disclaimerText}
      </Notice>

      {errorMsg ? (
        <Notice tone="crit" title="Simulation error:">
          {errorMsg}
        </Notice>
      ) : null}

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
                <input
                  type="number"
                  min={20}
                  max={2000}
                  value={placeSize}
                  onChange={(e) => setPlaceSize(Number(e.target.value) || 200)}
                />
              </label>
              <label className="stack">
                <span className="small muted">Quota Change % (UNI-005)</span>
                <input
                  type="number"
                  min={-90}
                  max={200}
                  value={placeQuotaPct}
                  onChange={(e) => setPlaceQuotaPct(Number(e.target.value))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Engineering Rank Baraj (≤)</span>
                <input
                  type="number"
                  min={10000}
                  max={1000000}
                  step={10000}
                  value={placeBarajEng}
                  onChange={(e) => setPlaceBarajEng(Number(e.target.value) || 300000)}
                />
              </label>
              <label className="stack">
                <span className="small muted">Tuition Change % (UNI-001)</span>
                <input
                  type="number"
                  min={-100}
                  max={300}
                  value={placeTuitionPct}
                  onChange={(e) => setPlaceTuitionPct(Number(e.target.value))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Need-Based Aid % (UNI-002)</span>
                <input
                  type="number"
                  min={-100}
                  max={500}
                  value={placeAidPct}
                  onChange={(e) => setPlaceAidPct(Number(e.target.value))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Installment Count (UNI-006)</span>
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={placeInstallments}
                  onChange={(e) => setPlaceInstallments(Math.max(1, Number(e.target.value) || 1))}
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
                  value={fmtInt(pMetrics?.placed_count ?? 0)}
                  sub={`Rate: ${(((pMetrics?.placement_rate as number) ?? 0) * 100).toFixed(1)}%`}
                />
                <StatTile
                  label="1st-Choice Placement"
                  value={`${(((pMetrics?.first_choice_rate as number) ?? 0) * 100).toFixed(1)}%`}
                  sub={`${fmtInt(pMetrics?.first_choice_count ?? 0)} first-choice matches`}
                />
                <StatTile
                  label="Seat Utilization"
                  value={`${(((pMetrics?.seat_utilization_rate as number) ?? 0) * 100).toFixed(1)}%`}
                  sub={`${fmtInt(pMetrics?.total_filled ?? 0)} / ${fmtInt(pMetrics?.total_capacity ?? 0)} seats`}
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
                <input
                  type="number"
                  min={1}
                  max={8}
                  value={uniSemesters}
                  onChange={(e) => setUniSemesters(Math.max(1, Number(e.target.value) || 4))}
                />
              </label>
              <label className="stack">
                <span className="small muted">CRN Replications</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={uniReplications}
                  onChange={(e) => setUniReplications(Math.max(1, Number(e.target.value) || 8))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Tuition Change % (UNI-001)</span>
                <input
                  type="number"
                  min={-100}
                  max={300}
                  value={uniTuitionPct}
                  onChange={(e) => setUniTuitionPct(Number(e.target.value))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Aid Budget % (UNI-002)</span>
                <input
                  type="number"
                  min={-100}
                  max={500}
                  value={uniAidPct}
                  onChange={(e) => setUniAidPct(Number(e.target.value))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Installments (UNI-006)</span>
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={uniInstallments}
                  onChange={(e) => setUniInstallments(Math.max(1, Number(e.target.value) || 1))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Min Attendance % (UNI-003)</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={uniAttendanceMin}
                  onChange={(e) => setUniAttendanceMin(Number(e.target.value))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Grading Difficulty Shift (UNI-004)</span>
                <input
                  type="number"
                  min={-2}
                  max={2}
                  step={0.1}
                  value={uniGradingShift}
                  onChange={(e) => setUniGradingShift(Number(e.target.value))}
                />
              </label>
              <label className="stack">
                <span className="small muted">Course Seats % (UNI-005)</span>
                <input
                  type="number"
                  min={-90}
                  max={200}
                  value={uniCapacityPct}
                  onChange={(e) => setUniCapacityPct(Number(e.target.value))}
                />
              </label>
            </div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <label className="row small">
                <span>Cohort Size (when not using Placement Handoff):</span>
                <input
                  type="number"
                  min={20}
                  max={1000}
                  style={{ width: 90 }}
                  disabled={Boolean(linkedPlacementId)}
                  value={uniSize}
                  onChange={(e) => setUniSize(Number(e.target.value) || 200)}
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
                    value={fmtSigned((uEffects.cumulative_retention_rate?.mean ?? 0) * 100, 2, " pp")}
                    sub={`Policy: ${((uEffects.cumulative_retention_rate?.policy_mean ?? 0) * 100).toFixed(2)}%`}
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
                    value={fmtSigned((uEffects.total_net_tuition_revenue?.mean ?? 0) / 1_000_000, 2, "M TL")}
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
                      onClick={async () => {
                        const detail = await v2<PlacementRunResponse>(`/placement/runs/${r.run_id}`);
                        setActivePlacement(detail);
                        setTab("placement");
                      }}
                    >
                      Inspect
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
                      onClick={async () => {
                        const detail = await v2<UniversityRunResponse>(`/university/runs/${r.run_id}`);
                        setActiveUniversity(detail);
                        setTab("multiterm");
                      }}
                    >
                      Inspect
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
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
