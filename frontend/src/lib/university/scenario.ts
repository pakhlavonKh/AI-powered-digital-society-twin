/**
 * Scenario configuration: presets, validation and serialization. The configuration shape is a PROVISIONAL frontend
 * contract (no placement API exists); see docs/university-simulation-ui.md. Only parameters a simulation can act on
 * are exposed. Scholarship-availability and preference-model changes have no mechanism anywhere in the repository,
 * so those presets are listed but cannot run.
 */
import type { Finding, PresetId, RegistryCatalogue, ScenarioConfig, UniversityCapabilities } from "./types";
import { canonicalJson, fnv1a } from "./util";

export const SCENARIO_CONTRACT_VERSION = "university-scenario-ui-v1";
export const MAX_SEED = Number.MAX_SAFE_INTEGER;
export const MAX_QUOTA_OVERRIDE = 10000;
export const NAME_MAX = 80;

export type PresetSpec = {
  id: PresetId;
  letter: string;
  title: string;
  description: string;
  /** Applied on top of the current configuration when the preset is chosen. */
  patch: Partial<Pick<ScenarioConfig, "quota_adjustment_pct" | "name">>;
};

export const PRESETS: PresetSpec[] = [
  { id: "baseline", letter: "A", title: "Baseline", description: "Unchanged reported quotas and candidate preferences.",
    patch: { quota_adjustment_pct: 0, name: "Scenario A — Baseline" } },
  { id: "quota_increase", letter: "B", title: "Increased program quotas", description: "Raise every included program's quota by a configurable percentage.",
    patch: { quota_adjustment_pct: 20, name: "Scenario B — Quotas +20%" } },
  { id: "quota_decrease", letter: "C", title: "Reduced program quotas", description: "Lower quotas to study competition and unplaced candidates.",
    patch: { quota_adjustment_pct: -30, name: "Scenario C — Quotas −30%" } },
  { id: "scholarship_change", letter: "D", title: "Scholarship availability change", description: "Change scholarship-related availability or eligibility.", patch: {} },
  { id: "preference_change", letter: "E", title: "Candidate preference change", description: "Compare outcomes under a different preference distribution.", patch: {} },
];

export function presetSupport(preset: PresetId, caps: UniversityCapabilities | undefined): { supported: boolean; reason: string | null } {
  if (preset === "custom") return { supported: caps?.execution.mode !== "unavailable", reason: null };
  const unsupported = caps?.unsupported_presets.find((p) => p.preset === preset);
  if (unsupported) return { supported: false, reason: unsupported.reason };
  if (caps && !caps.supported_presets.includes(preset)) return { supported: false, reason: "Not supported by the active data source." };
  return { supported: true, reason: null };
}

export function defaultScenario(catalogue: RegistryCatalogue, cohort: { cohort_id: string; generator_version: string; seed: number; size: number }): ScenarioConfig {
  const years = catalogue.snapshot.admission_years;
  const year = years.includes(2025) ? 2025 : years[years.length - 1] ?? new Date().getFullYear();
  return {
    name: "Scenario A — Baseline", preset: "baseline", admission_year: year, registry_snapshot_id: catalogue.snapshot.snapshot_id,
    cohort: { ...cohort }, seed: 7, quota_adjustment_pct: 0, program_quota_overrides: {}, included_university_keys: null,
  };
}

const err = (code: string, message: string, field?: string): Finding => ({ code, severity: "error", origin: "scenario_validation", blocking: true, message, field });
const warn = (code: string, message: string, field?: string, detail?: string): Finding => ({ code, severity: "warning", origin: "scenario_validation", blocking: false, message, field, detail });
const info = (code: string, message: string, field?: string): Finding => ({ code, severity: "info", origin: "scenario_validation", blocking: false, message, field });

/** Errors (blocking) prevent running; warnings stay visible but allow it. Messages say how to fix the problem. */
export function validateScenario(c: ScenarioConfig, catalogue: RegistryCatalogue | undefined, caps: UniversityCapabilities | undefined,
  cohortSnapshot: string | null = null): Finding[] {
  const out: Finding[] = [];
  const name = c.name.trim();
  if (name === "") out.push(err("name_required", "Enter a scenario name.", "name"));
  else if (name.length > NAME_MAX) out.push(err("name_too_long", `Shorten the scenario name to ${NAME_MAX} characters or fewer.`, "name"));

  const support = presetSupport(c.preset, caps);
  if (!support.supported) out.push(err("preset_unsupported", `This scenario type cannot run: ${support.reason ?? "not supported"}. Choose a supported preset.`, "preset"));
  if (caps && caps.execution.mode === "unavailable") out.push(err("execution_unavailable", `No simulation can run: ${caps.execution.detail}`));

  if (!catalogue) {
    out.push(err("dataset_unavailable", "The registry dataset is not loaded, so the scenario cannot be checked. Retry loading the registry.", "registry_snapshot_id"));
    return out;
  }
  if (catalogue.snapshot.snapshot_id !== c.registry_snapshot_id) {
    out.push(err("dataset_unavailable", `Registry snapshot ${c.registry_snapshot_id} is not available. Choose an available snapshot.`, "registry_snapshot_id"));
  }
  if (!catalogue.snapshot.admission_years.includes(c.admission_year)) {
    out.push(err("year_unsupported", `Admission year ${c.admission_year} has no registry rows. Choose one of ${catalogue.snapshot.admission_years.join(", ")}.`, "admission_year"));
  }
  const maxCohort = caps?.limits.max_cohort_size ?? Infinity;
  if (!Number.isInteger(c.cohort.size) || c.cohort.size < 1) out.push(err("cohort_size_invalid", "Candidate count must be a whole number of at least 1.", "cohort.size"));
  else if (c.cohort.size > maxCohort) out.push(err("cohort_size_too_large", `Candidate count must be at most ${maxCohort.toLocaleString("en-GB")} for this data source.`, "cohort.size"));
  if (!Number.isSafeInteger(c.cohort.seed) || c.cohort.seed < 0) out.push(err("cohort_seed_invalid", `Cohort seed must be a whole number from 0 to ${MAX_SEED}.`, "cohort.seed"));
  if (!Number.isSafeInteger(c.seed) || c.seed < 0) out.push(err("seed_invalid", `Simulation seed must be a whole number from 0 to ${MAX_SEED}.`, "seed"));

  const [lo, hi] = caps?.limits.quota_adjustment_pct ?? [-90, 200];
  if (!Number.isFinite(c.quota_adjustment_pct) || c.quota_adjustment_pct < lo || c.quota_adjustment_pct > hi) {
    out.push(err("quota_adjustment_out_of_range", `Quota adjustment must be between ${lo}% and +${hi}%.`, "quota_adjustment_pct"));
  } else if (c.quota_adjustment_pct <= -50) {
    out.push(info("quota_large_cut", `Quotas are cut by ${Math.abs(c.quota_adjustment_pct)}%; expect many unplaced candidates.`, "quota_adjustment_pct"));
  }
  if ((c.preset === "quota_increase" && c.quota_adjustment_pct <= 0) || (c.preset === "quota_decrease" && c.quota_adjustment_pct >= 0)) {
    out.push(warn("preset_mismatch", "The quota adjustment does not match the chosen preset's direction.", "quota_adjustment_pct"));
  }

  const keys = new Set(catalogue.universities.map((u) => u.university_key));
  if (c.included_university_keys !== null) {
    if (c.included_university_keys.length === 0) out.push(err("no_institutions", "Select at least one institution.", "included_university_keys"));
    for (const k of c.included_university_keys) if (!keys.has(k)) out.push(err("unknown_institution", `Institution ${k} is not in the snapshot. Remove it.`, "included_university_keys"));
  }
  const includedIds = new Set(catalogue.universities.filter((u) => c.included_university_keys === null || c.included_university_keys.includes(u.university_key)).map((u) => u.university_id));
  const yearRows = new Map(catalogue.admissions.filter((a) => a.admission_year === c.admission_year).map((a) => [a.program_id, a]));
  const programByCode = new Map(catalogue.programs.map((p) => [p.program_code, p]));
  for (const [code, value] of Object.entries(c.program_quota_overrides)) {
    const p = programByCode.get(code);
    if (!p) { out.push(err("override_unknown_program", `Program ${code} is not in the snapshot. Remove the override.`, `override.${code}`)); continue; }
    if (!includedIds.has(p.university_id)) out.push(err("override_excluded_program", `Program ${code} belongs to an institution that is not selected. Remove the override or include the institution.`, `override.${code}`));
    if (!yearRows.has(p.program_id)) out.push(err("override_no_admission_row", `Program ${code} has no ${c.admission_year} admission row, so its capacity cannot be set for that year.`, `override.${code}`));
    if (!Number.isInteger(value) || value < 0 || value > MAX_QUOTA_OVERRIDE) out.push(err("override_invalid", `Capacity for program ${code} must be a whole number from 0 to ${MAX_QUOTA_OVERRIDE}.`, `override.${code}`));
    else if (yearRows.get(p.program_id)?.quota === null) out.push(warn("override_replaces_missing_quota", `Program ${code} has no reported quota; the override (${value}) is a scenario assumption, not source data.`, `override.${code}`));
  }

  const included = catalogue.programs.filter((p) => includedIds.has(p.university_id));
  const offered = included.filter((p) => yearRows.has(p.program_id));
  const missingQuota = offered.filter((p) => yearRows.get(p.program_id)?.quota === null && c.program_quota_overrides[p.program_code] === undefined);
  if (missingQuota.length) {
    out.push(warn("missing_quota", `${missingQuota.length} included program(s) have no reported ${c.admission_year} quota and will receive no placements.`, undefined,
      missingQuota.map((p) => p.program_code).join(", ")));
  }
  const notOffered = included.length - offered.length;
  if (notOffered > 0) out.push(info("not_offered", `${notOffered} included program(s) have no ${c.admission_year} admission row and are left out (absence is not zero capacity).`));
  if (offered.length === 0 && c.included_university_keys?.length !== 0) out.push(err("no_programs", `No included program has a ${c.admission_year} admission row. Choose another year or institution.`));
  if (cohortSnapshot !== null && cohortSnapshot !== c.registry_snapshot_id) {
    out.push(err("cohort_snapshot_mismatch", `The candidate cohort's preferences reference snapshot ${cohortSnapshot}, not ${c.registry_snapshot_id}. Use a matching cohort.`, "cohort"));
  }
  if (caps?.execution.mode === "fixture_preview") {
    out.push(info("fixture_mode", "Demo mode: this runs the illustrative fixture allocation in your browser. No backend simulation is executed."));
  }
  return out;
}

export function hasBlocking(findings: Finding[]): boolean {
  return findings.some((f) => f.blocking);
}

/** Canonical request body for a future scenario API: sorted keys, trimmed name, sorted institution keys. */
export function serializeScenario(c: ScenarioConfig): string {
  return canonicalJson({
    contract_version: SCENARIO_CONTRACT_VERSION,
    ...c,
    name: c.name.trim(),
    included_university_keys: c.included_university_keys === null ? null : [...c.included_university_keys].sort(),
  });
}

/** Fingerprint of everything that affects results (name and preset label do not), used to prevent duplicate submissions. */
export function scenarioFingerprint(c: ScenarioConfig): string {
  const parsed = JSON.parse(serializeScenario(c)) as Record<string, unknown>;
  delete parsed.name;
  delete parsed.preset;
  return fnv1a(canonicalJson(parsed));
}
