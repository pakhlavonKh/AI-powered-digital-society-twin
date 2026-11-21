/**
 * Placement summaries and scenario comparison, computed from assignment-level run output.
 *
 * Denominators:
 *   placement rate   = placed / eligible × 100, eligible = placed + unplaced. Candidates the simulation marked
 *                      ineligible (no eligible preference, no preferences) are excluded and reported separately.
 *   utilization      = occupied seats / available seats × 100, over programs with a known capacity only.
 *   first choice     = placed at preference 1 / placed.
 * Percentage-point differences (pp) and relative percentage changes (%) are always reported separately.
 */
import type { Finding, ProgramCapacity, RegistryCatalogue, SimulationRun } from "./types";
import { compareText } from "./util";

export type Breakdown = { key: string; label: string; placed: number; capacity: number | null; programs: number; unknown_capacity_programs: number };
export type ProgramBreakdown = Breakdown & { program_code: string; university: string; scholarship: string | null; score_type: string | null; base_quota: number | null };
export type ScoreTypeBreakdown = { key: string; label: string; total: number; eligible: number; placed: number };

export type RunSummary = {
  total: number;
  eligible: number;
  ineligible: number;
  placed: number;
  unplaced: number;
  /** Share in [0, 1]; null when no candidate is eligible. */
  placement_rate: number | null;
  capacity_known: number;
  programs_total: number;
  programs_unknown_capacity: number;
  occupied_seats: number;
  remaining_capacity: number;
  utilization: number | null;
  over_capacity: { program_code: string; capacity: number; placed: number }[];
  by_university: Breakdown[];
  by_program: ProgramBreakdown[];
  by_score_type: ScoreTypeBreakdown[];
  by_scholarship: Breakdown[];
  preference_rank: { position: number; count: number }[];
  first_choice_share: number | null;
  reconciles: boolean;
};

function placedByProgram(run: SimulationRun): Map<string, number> {
  const m = new Map<string, number>();
  for (const a of run.assignments) if (a.status === "placed" && a.program_code) m.set(a.program_code, (m.get(a.program_code) ?? 0) + 1);
  return m;
}

export function summarizeRun(run: SimulationRun, catalogue: RegistryCatalogue, candidateScoreTypes?: Map<string, string | null>): RunSummary {
  const total = run.assignments.length;
  let placed = 0;
  let unplaced = 0;
  let ineligible = 0;
  const ranks = new Map<number, number>();
  for (const a of run.assignments) {
    if (a.status === "placed") {
      placed += 1;
      if (a.preference_position !== null) ranks.set(a.preference_position, (ranks.get(a.preference_position) ?? 0) + 1);
    } else if (a.status === "unplaced") unplaced += 1;
    else ineligible += 1;
  }
  const eligible = placed + unplaced;
  const occupied = placedByProgram(run);
  const programs = new Map(catalogue.programs.map((p) => [p.program_code, p]));
  const unis = new Map(catalogue.universities.map((u) => [u.university_id, u]));

  let capacityKnown = 0;
  let remaining = 0;
  let occupiedKnown = 0;
  const over: RunSummary["over_capacity"] = [];
  const byProgram: ProgramBreakdown[] = [];
  const caps = new Map<string, ProgramCapacity>(run.capacities.map((c) => [c.program_code, c]));
  // Programs that received placements but are missing from the capacity list still count (and are flagged).
  for (const code of occupied.keys()) if (!caps.has(code)) caps.set(code, { program_code: code, base_quota: null, capacity: null, placed: occupied.get(code) ?? 0 });
  for (const c of caps.values()) {
    const n = occupied.get(c.program_code) ?? 0;
    const p = programs.get(c.program_code);
    const u = p ? unis.get(p.university_id) : undefined;
    if (c.capacity !== null) {
      capacityKnown += c.capacity;
      occupiedKnown += n;
      remaining += Math.max(0, c.capacity - n);
      if (n > c.capacity) over.push({ program_code: c.program_code, capacity: c.capacity, placed: n });
    }
    byProgram.push({
      key: c.program_code, program_code: c.program_code, label: p ? `${p.name_original} · ${p.scholarship_original ?? "scholarship missing"}` : `Unknown program ${c.program_code}`,
      university: u?.name_original ?? "Unknown university", scholarship: p?.scholarship_original ?? null, score_type: p?.score_type ?? null,
      placed: n, capacity: c.capacity, base_quota: c.base_quota, programs: 1, unknown_capacity_programs: c.capacity === null ? 1 : 0,
    });
  }
  byProgram.sort((a, b) => compareText(a.university, b.university) || compareText(a.label, b.label) || (a.program_code < b.program_code ? -1 : 1));

  const group = (keyOf: (p: ProgramBreakdown) => string, labelOf: (p: ProgramBreakdown) => string): Breakdown[] => {
    const m = new Map<string, Breakdown>();
    for (const p of byProgram) {
      const key = keyOf(p);
      const g = m.get(key) ?? { key, label: labelOf(p), placed: 0, capacity: 0, programs: 0, unknown_capacity_programs: 0 };
      g.placed += p.placed;
      g.programs += 1;
      if (p.capacity === null) g.unknown_capacity_programs += 1;
      else g.capacity = (g.capacity ?? 0) + p.capacity;
      m.set(key, g);
    }
    // Known capacity only; a group whose every program lacks a capacity has no known capacity at all (not zero).
    for (const g of m.values()) if (g.unknown_capacity_programs === g.programs) g.capacity = null;
    return [...m.values()].sort((a, b) => compareText(a.label, b.label));
  };

  const types = new Map<string, ScoreTypeBreakdown>();
  for (const a of run.assignments) {
    const t = candidateScoreTypes?.get(a.candidate_id) ?? null;
    const key = t ?? "__missing__";
    const g = types.get(key) ?? { key, label: t ?? "Missing", total: 0, eligible: 0, placed: 0 };
    g.total += 1;
    if (a.status !== "ineligible") g.eligible += 1;
    if (a.status === "placed") g.placed += 1;
    types.set(key, g);
  }
  const positions = [...ranks.keys()].sort((a, b) => a - b);
  const maxPos = positions[positions.length - 1] ?? 0;
  const sumByProgram = byProgram.reduce((s, p) => s + p.placed, 0);
  return {
    total, eligible, ineligible, placed, unplaced,
    placement_rate: eligible > 0 ? placed / eligible : null,
    capacity_known: capacityKnown, programs_total: caps.size, programs_unknown_capacity: [...caps.values()].filter((c) => c.capacity === null).length,
    occupied_seats: sumByProgram, remaining_capacity: remaining, utilization: capacityKnown > 0 ? occupiedKnown / capacityKnown : null,
    over_capacity: over,
    by_university: group((p) => p.university, (p) => p.university),
    by_program: byProgram,
    by_score_type: [...types.values()].sort((a, b) => (a.key === "__missing__" ? 1 : b.key === "__missing__" ? -1 : compareText(a.label, b.label))),
    by_scholarship: group((p) => p.scholarship ?? "__missing__", (p) => p.scholarship ?? "Missing from source"),
    preference_rank: Array.from({ length: maxPos }, (_, i) => ({ position: i + 1, count: ranks.get(i + 1) ?? 0 })),
    first_choice_share: placed > 0 ? (ranks.get(1) ?? 0) / placed : null,
    reconciles: placed + unplaced + ineligible === total && sumByProgram === placed,
  };
}

/** Result-integrity checks. Exceeded capacity and unreconciled totals are errors and are never hidden. */
export function runIntegrity(run: SimulationRun, catalogue: RegistryCatalogue): Finding[] {
  const out: Finding[] = [...run.findings];
  const summary = summarizeRun(run, catalogue);
  const record = `Run ${run.run_id}`;
  for (const o of summary.over_capacity) {
    out.push({ code: "over_capacity", severity: "error", origin: "frontend_check", blocking: false, record: `Program ${o.program_code}`,
      message: `${o.placed} placements exceed the scenario capacity of ${o.capacity}. The count is shown unchanged.` });
  }
  if (!summary.reconciles) {
    out.push({ code: "totals_do_not_reconcile", severity: "error", origin: "frontend_check", blocking: false, record,
      message: "Placed + unplaced + ineligible does not equal the candidate total, or program placements do not sum to the placed count." });
  }
  const codes = new Set(catalogue.programs.map((p) => p.program_code));
  const unknown = run.assignments.filter((a) => a.status === "placed" && a.program_code !== null && !codes.has(a.program_code));
  if (unknown.length) {
    out.push({ code: "invalid_preference_reference", severity: "error", origin: "frontend_check", blocking: false, record,
      message: `${unknown.length} placement(s) reference program codes that are not in the registry snapshot.` });
  }
  const p = run.provenance;
  const missing = [
    !p.engine && "engine", p.simulation_seed === null || p.simulation_seed === undefined ? "simulation seed" : null,
    !p.registry_snapshot_id && "registry snapshot", !p.cohort_id && "cohort", !p.config_hash && "configuration hash",
  ].filter(Boolean);
  if (missing.length) {
    out.push({ code: "missing_provenance", severity: "warning", origin: "frontend_check", blocking: false, record,
      message: `Simulation provenance is incomplete: ${missing.join(", ")} not recorded.` });
  }
  if (p.engine_version === null) {
    out.push({ code: "missing_provenance", severity: "info", origin: "frontend_check", blocking: false, record, message: "The simulation engine version was not recorded." });
  }
  return out;
}

// ---------------------------------------------------------------- comparison

/** Blocking findings mean the runs must not be compared; warnings qualify the comparison. */
export function runCompatibility(a: SimulationRun, b: SimulationRun): Finding[] {
  const out: Finding[] = [];
  const e = (code: string, message: string): Finding => ({ code, severity: "error", origin: "scenario_validation", blocking: true, message });
  const w = (code: string, message: string): Finding => ({ code, severity: "warning", origin: "scenario_validation", blocking: false, message });
  if (a.status !== "completed" || b.status !== "completed") out.push(e("run_not_completed", "Both runs must be completed before they can be compared."));
  if (a.run_id === b.run_id) out.push(w("same_run", "Scenario A and Scenario B are the same run; every difference is zero."));
  if (a.origin !== b.origin) out.push(e("origin_mismatch", `Cannot compare a ${a.origin} run with a ${b.origin} run.`));
  if (a.provenance.registry_snapshot_id !== b.provenance.registry_snapshot_id) {
    out.push(e("dataset_mismatch", `The runs use different registry snapshots (${a.provenance.registry_snapshot_id} vs ${b.provenance.registry_snapshot_id}).`));
  }
  if (a.config.admission_year !== b.config.admission_year) {
    out.push(e("year_mismatch", `The runs use different admission years (${a.config.admission_year} vs ${b.config.admission_year}).`));
  }
  if (a.provenance.cohort_generator_version !== b.provenance.cohort_generator_version || a.provenance.cohort_seed !== b.provenance.cohort_seed) {
    out.push(e("cohort_mismatch", "The runs use different candidate cohorts (generator or seed differ). Candidate IDs are cohort-local, so outcomes cannot be matched."));
  } else if (a.provenance.cohort_size !== b.provenance.cohort_size) {
    out.push(w("cohort_size_mismatch", `Cohort sizes differ (${a.provenance.cohort_size} vs ${b.provenance.cohort_size}). Candidate-level changes cover shared IDs only; aggregate rates have different denominators.`));
  }
  if (a.provenance.engine !== b.provenance.engine || a.provenance.engine_version !== b.provenance.engine_version) {
    out.push(w("engine_mismatch", "The runs were produced by different simulation engines or versions."));
  }
  if (a.config.seed !== b.config.seed) out.push(w("seed_mismatch", "The runs use different simulation seeds, so tie-breaking may differ."));
  const ka = a.config.included_university_keys === null ? "all" : [...a.config.included_university_keys].sort().join(",");
  const kb = b.config.included_university_keys === null ? "all" : [...b.config.included_university_keys].sort().join(",");
  if (ka !== kb) out.push(w("institutions_mismatch", "The runs include different institutions; institution-level differences partly reflect that choice."));
  return out;
}

export type TransitionKind = "same_program" | "moved_program" | "newly_placed" | "newly_not_placed" | "both_not_placed" | "eligibility_changed";
export const TRANSITION_LABELS: Record<TransitionKind, string> = {
  same_program: "Same program in both",
  moved_program: "Placed in both, different program",
  newly_placed: "Not placed in A, placed in B",
  newly_not_placed: "Placed in A, not placed in B",
  both_not_placed: "Not placed in either",
  eligibility_changed: "Eligibility changed (not placed in either)",
};

export type CandidateChange = { candidate_id: string; kind: TransitionKind; a_program: string | null; b_program: string | null; a_status: string; b_status: string };

export type RunComparison = {
  a: RunSummary;
  b: RunSummary;
  placement_rate_pp: number | null;
  placement_rate_rel_pct: number | null;
  placed_diff: number;
  unplaced_diff: number;
  ineligible_diff: number;
  eligible_diff: number;
  capacity_diff: number;
  utilization_pp: number | null;
  first_choice_pp: number | null;
  universities: { key: string; label: string; a: number; b: number; diff: number; rel_pct: number | null; a_capacity: number | null; b_capacity: number | null }[];
  programs: { program_code: string; label: string; university: string; a_capacity: number | null; b_capacity: number | null; a_placed: number; b_placed: number;
    diff: number; a_util: number | null; b_util: number | null; util_pp: number | null }[];
  preference_rank: { position: number; a: number; b: number; diff: number }[];
  candidates: { matched: number; only_a: number; only_b: number; transitions: Record<TransitionKind, number>; changed: CandidateChange[] };
};

const pp = (a: number | null, b: number | null) => (a === null || b === null ? null : (b - a) * 100);
const rel = (a: number | null, b: number | null) => (a === null || b === null || a === 0 ? null : ((b - a) / a) * 100);
const util = (placed: number, cap: number | null) => (cap === null || cap === 0 ? null : placed / cap);

export function compareRuns(runA: SimulationRun, runB: SimulationRun, catalogue: RegistryCatalogue, scoreTypes?: Map<string, string | null>): RunComparison {
  const a = summarizeRun(runA, catalogue, scoreTypes);
  const b = summarizeRun(runB, catalogue, scoreTypes);
  const uniKeys = [...new Set([...a.by_university.map((u) => u.key), ...b.by_university.map((u) => u.key)])].sort(compareText);
  const universities = uniKeys.map((key) => {
    const ua = a.by_university.find((u) => u.key === key);
    const ub = b.by_university.find((u) => u.key === key);
    const av = ua?.placed ?? 0;
    const bv = ub?.placed ?? 0;
    return { key, label: ua?.label ?? ub?.label ?? key, a: av, b: bv, diff: bv - av, rel_pct: rel(av, bv),
      a_capacity: ua?.capacity ?? null, b_capacity: ub?.capacity ?? null };
  });
  const codes = [...new Set([...a.by_program.map((p) => p.program_code), ...b.by_program.map((p) => p.program_code)])];
  const programs = codes.map((code) => {
    const pa = a.by_program.find((p) => p.program_code === code);
    const pb = b.by_program.find((p) => p.program_code === code);
    const au = pa ? util(pa.placed, pa.capacity) : null;
    const bu = pb ? util(pb.placed, pb.capacity) : null;
    return { program_code: code, label: (pa ?? pb)!.label, university: (pa ?? pb)!.university, a_capacity: pa?.capacity ?? null, b_capacity: pb?.capacity ?? null,
      a_placed: pa?.placed ?? 0, b_placed: pb?.placed ?? 0, diff: (pb?.placed ?? 0) - (pa?.placed ?? 0), a_util: au, b_util: bu, util_pp: pp(au, bu) };
  }).sort((x, y) => compareText(x.university, y.university) || compareText(x.label, y.label));
  const maxPos = Math.max(a.preference_rank.length, b.preference_rank.length);
  const preference_rank = Array.from({ length: maxPos }, (_, i) => {
    const av = a.preference_rank[i]?.count ?? 0;
    const bv = b.preference_rank[i]?.count ?? 0;
    return { position: i + 1, a: av, b: bv, diff: bv - av };
  });

  const byA = new Map(runA.assignments.map((x) => [x.candidate_id, x]));
  const byB = new Map(runB.assignments.map((x) => [x.candidate_id, x]));
  const transitions: Record<TransitionKind, number> = { same_program: 0, moved_program: 0, newly_placed: 0, newly_not_placed: 0, both_not_placed: 0, eligibility_changed: 0 };
  const changed: CandidateChange[] = [];
  let matched = 0;
  for (const [id, xa] of byA) {
    const xb = byB.get(id);
    if (!xb) continue;
    matched += 1;
    let kind: TransitionKind;
    if (xa.status === "placed" && xb.status === "placed") kind = xa.program_code === xb.program_code ? "same_program" : "moved_program";
    else if (xa.status === "placed") kind = "newly_not_placed";
    else if (xb.status === "placed") kind = "newly_placed";
    else kind = xa.status === xb.status ? "both_not_placed" : "eligibility_changed";
    transitions[kind] += 1;
    if (kind !== "same_program" && kind !== "both_not_placed") {
      changed.push({ candidate_id: id, kind, a_program: xa.program_code, b_program: xb.program_code, a_status: xa.status, b_status: xb.status });
    }
  }
  changed.sort((x, y) => (x.candidate_id < y.candidate_id ? -1 : 1));
  return {
    a, b,
    placement_rate_pp: pp(a.placement_rate, b.placement_rate),
    placement_rate_rel_pct: rel(a.placement_rate, b.placement_rate),
    placed_diff: b.placed - a.placed, unplaced_diff: b.unplaced - a.unplaced, ineligible_diff: b.ineligible - a.ineligible, eligible_diff: b.eligible - a.eligible,
    capacity_diff: b.capacity_known - a.capacity_known, utilization_pp: pp(a.utilization, b.utilization), first_choice_pp: pp(a.first_choice_share, b.first_choice_share),
    universities, programs, preference_rank,
    candidates: { matched, only_a: runA.assignments.length - matched, only_b: runB.assignments.length - matched, transitions, changed },
  };
}
