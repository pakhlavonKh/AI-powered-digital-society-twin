/**
 * ILLUSTRATIVE FIXTURE ALLOCATION — NOT THE SOCIETYTWIN PLACEMENT ENGINE AND NOT ÖSYM RULES.
 *
 * The placement engine (eligibility, score-type restrictions, quotas, ties, allocation rounds) is owned by the
 * placement workstream and does not exist yet. The dashboard still needs internally consistent demonstration
 * results, so fixture previews are produced by this deliberately simple procedure:
 *
 *   1. candidates are ordered by the synthetic achievement proxy (descending), ties by a seeded hash of the ID;
 *   2. each candidate takes the first preference that is a known program, included in the scenario, has a
 *      score type matching the candidate's (after folding SÖZ→SOZ, DİL→DIL), has a known capacity and a free seat.
 *
 * Every result it produces is labelled as a fixture. It must never be wired up as the real engine; replace it by
 * calling the placement API once one exists.
 */
import type { Assignment, Candidate, Finding, Preference, PreferenceOutcome, ProgramCapacity, RegistryCatalogue, ScenarioConfig } from "../types";
import { fnv1a, scoreTypeKey } from "../util";

export const FIXTURE_ENGINE = "frontend-fixture-allocator";
export const FIXTURE_ENGINE_VERSION = "illustrative-v1";

export const REASONS: Record<string, string> = {
  no_preferences: "The candidate has no preferences in the handoff.",
  no_eligible_preference: "No preference passed the fixture rule (known program, included in the scenario, matching score type, known capacity).",
  eligible_preferences_full: "Every eligible preference was already full when this candidate's turn came (fixture order: achievement proxy).",
  no_achievement: "The candidate has no achievement value, so the fixture order cannot place them.",
};

export function scenarioCapacities(config: ScenarioConfig, registry: RegistryCatalogue): ProgramCapacity[] {
  const included = includedUniversityIds(config, registry);
  const byProgram = new Map(registry.admissions.filter((a) => a.admission_year === config.admission_year).map((a) => [a.program_id, a]));
  return registry.programs
    .filter((p) => included.has(p.university_id) && byProgram.has(p.program_id))
    .map((p) => {
      const base = byProgram.get(p.program_id)?.quota ?? null;
      const override = config.program_quota_overrides[p.program_code];
      const capacity = override !== undefined ? override : base === null ? null : Math.max(0, Math.round(base * (1 + config.quota_adjustment_pct / 100)));
      return { program_code: p.program_code, base_quota: base, capacity, placed: 0 };
    });
}

export function includedUniversityIds(config: ScenarioConfig, registry: RegistryCatalogue): Set<number> {
  const keys = config.included_university_keys;
  return new Set(registry.universities.filter((u) => keys === null || keys.includes(u.university_key)).map((u) => u.university_id));
}

export function allocateFixture(
  config: ScenarioConfig,
  registry: RegistryCatalogue,
  candidates: Candidate[],
  preferences: Preference[],
): { assignments: Assignment[]; capacities: ProgramCapacity[]; findings: Finding[] } {
  const capacities = scenarioCapacities(config, registry);
  const capByCode = new Map(capacities.map((c) => [c.program_code, c]));
  const programByCode = new Map(registry.programs.map((p) => [p.program_code, p]));
  const prefsByCandidate = new Map<string, Preference[]>();
  for (const p of preferences) {
    const list = prefsByCandidate.get(p.candidate_id) ?? [];
    list.push(p);
    prefsByCandidate.set(p.candidate_id, list);
  }
  const tie = (id: string) => fnv1a(`${config.seed}:${id}`);
  const order = [...candidates].sort((a, b) => {
    const av = a.achievement?.value ?? -1;
    const bv = b.achievement?.value ?? -1;
    if (av !== bv) return bv - av;
    const ta = tie(a.candidate_id);
    const tb = tie(b.candidate_id);
    return ta < tb ? -1 : ta > tb ? 1 : a.candidate_id < b.candidate_id ? -1 : 1;
  });
  const byId = new Map<string, Assignment>();
  for (const c of order) {
    const prefs = [...(prefsByCandidate.get(c.candidate_id) ?? [])].sort((a, b) => a.position - b.position);
    if (c.achievement === null) {
      byId.set(c.candidate_id, { candidate_id: c.candidate_id, status: "ineligible", program_code: null, preference_position: null,
        reason_code: "no_achievement", reason: REASONS.no_achievement, evaluated: null });
      continue;
    }
    if (prefs.length === 0) {
      byId.set(c.candidate_id, { candidate_id: c.candidate_id, status: "ineligible", program_code: null, preference_position: null,
        reason_code: "no_preferences", reason: REASONS.no_preferences, evaluated: [] });
      continue;
    }
    const evaluated: { position: number; program_code: string; outcome: PreferenceOutcome }[] = [];
    let assigned: Preference | null = null;
    let sawFull = false;
    for (const pref of prefs) {
      if (assigned) { evaluated.push({ position: pref.position, program_code: pref.program_id, outcome: "not_reached" }); continue; }
      const program = programByCode.get(pref.program_id);
      let outcome: PreferenceOutcome;
      const cap = capByCode.get(pref.program_id);
      if (!program) outcome = "invalid_reference";
      else if (!cap) outcome = "excluded_by_scenario";
      else if (scoreTypeKey(program.score_type) === null || scoreTypeKey(program.score_type) !== scoreTypeKey(c.score_type)) outcome = "ineligible_score_type";
      else if (cap.capacity === null) outcome = "capacity_unknown";
      else if (cap.placed >= cap.capacity) { outcome = "full"; sawFull = true; }
      else { outcome = "assigned"; cap.placed += 1; assigned = pref; }
      evaluated.push({ position: pref.position, program_code: pref.program_id, outcome });
    }
    byId.set(c.candidate_id, assigned
      ? { candidate_id: c.candidate_id, status: "placed", program_code: assigned.program_id, preference_position: assigned.position, reason_code: null, reason: null, evaluated }
      : sawFull
        ? { candidate_id: c.candidate_id, status: "unplaced", program_code: null, preference_position: null, reason_code: "eligible_preferences_full", reason: REASONS.eligible_preferences_full, evaluated }
        : { candidate_id: c.candidate_id, status: "ineligible", program_code: null, preference_position: null, reason_code: "no_eligible_preference", reason: REASONS.no_eligible_preference, evaluated });
  }
  const assignments = candidates.map((c) => byId.get(c.candidate_id)!);
  const findings: Finding[] = [{
    code: "fixture_allocation", severity: "info", origin: "simulation", blocking: false,
    message: "Illustrative fixture allocation computed in this browser: strict achievement-proxy order, first available eligible preference. Not the SocietyTwin placement engine and not ÖSYM rules.",
  }];
  const unknown = capacities.filter((c) => c.capacity === null);
  if (unknown.length) {
    findings.push({ code: "capacity_unknown", severity: "warning", origin: "simulation", blocking: false,
      message: `${unknown.length} included program(s) have no reported quota for ${config.admission_year}; they received no placements.`,
      detail: unknown.map((c) => c.program_code).join(", ") });
  }
  return { assignments, capacities, findings };
}
