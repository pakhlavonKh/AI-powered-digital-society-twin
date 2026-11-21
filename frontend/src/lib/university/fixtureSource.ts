/**
 * Fixture implementation of UniversityDataSource. Everything is deterministic and synthetic; every object it returns
 * carries origin "fixture". Fixture runs are recomputed from their configuration (seeded), so only configurations
 * are kept in sessionStorage, never results.
 */
import { ApiError } from "../api/client";
import { candidateDetail, candidateRows, queryCandidateRows } from "./candidates";
import { allocateFixture, FIXTURE_ENGINE, FIXTURE_ENGINE_VERSION } from "./fixtures/allocator";
import { buildCohort, cohortId, DEFAULT_COHORT, FIXTURE_COHORT_GENERATOR, MAX_FIXTURE_COHORT, parseCohortId } from "./fixtures/candidates";
import { buildRegistryFixture } from "./fixtures/registry";
import { queryProgramRows } from "./programs";
import { defaultScenario, hasBlocking, scenarioFingerprint, validateScenario } from "./scenario";
import type { SubmitResult, UniversityDataSource } from "./source";
import type { CohortManifest, RunListItem, ScenarioConfig, SimulationRun, UniversityCapabilities } from "./types";

const STORAGE_KEY = "societytwin.university.fixtureRuns.v1";
const BUILTIN_CREATED = "2026-11-21T00:00:00Z";

export const FIXTURE_CAPABILITIES: UniversityCapabilities = {
  origin: "fixture",
  registry: { available: true, detail: "Synthetic fixture shaped like the university SQLite registry (schema v1). No registry API exists yet." },
  candidates: { available: true, detail: "Synthetic fixture cohort mirroring candidate-development-v1, with artificial preferences." },
  execution: { mode: "fixture_preview", detail: "Fixture previews run an illustrative allocation in the browser. No placement engine or API exists yet." },
  supported_presets: ["baseline", "quota_increase", "quota_decrease", "custom"],
  unsupported_presets: [
    { preset: "scholarship_change", reason: "no simulation mechanism changes scholarship availability; the registry stores scholarship labels only" },
    { preset: "preference_change", reason: "no preference model exists; preferences come from the cohort handoff" },
  ],
  limits: { max_cohort_size: MAX_FIXTURE_COHORT, quota_adjustment_pct: [-90, 200] },
};

type Stored = { config: ScenarioConfig; created_at: string };

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" && window.sessionStorage ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function later<T>(make: () => T): Promise<T> {
  return Promise.resolve().then(make);
}

function notFound(what: string): ApiError {
  return new ApiError(404, "not_found", `${what} was not found.`);
}

export function builtinConfigs(): { config: ScenarioConfig; created_at: string }[] {
  const catalogue = buildRegistryFixture();
  const cohort = { cohort_id: cohortId(DEFAULT_COHORT.seed, DEFAULT_COHORT.size), generator_version: FIXTURE_COHORT_GENERATOR, ...DEFAULT_COHORT };
  const base = defaultScenario(catalogue, cohort);
  return [
    { config: { ...base, name: "Scenario A — Baseline (fixture)", preset: "baseline", quota_adjustment_pct: 0 }, created_at: BUILTIN_CREATED },
    { config: { ...base, name: "Scenario B — Quotas +20% (fixture)", preset: "quota_increase", quota_adjustment_pct: 20 }, created_at: BUILTIN_CREATED },
    { config: { ...base, name: "Scenario C — Quotas −30% (fixture)", preset: "quota_decrease", quota_adjustment_pct: -30 }, created_at: BUILTIN_CREATED },
  ];
}

export function fixtureRunId(config: ScenarioConfig): string {
  return `fx-${scenarioFingerprint(config)}`;
}

export function computeFixtureRun(config: ScenarioConfig, kind: SimulationRun["kind"], createdAt: string): SimulationRun {
  const catalogue = buildRegistryFixture();
  const cohort = buildCohort(config.cohort.seed, config.cohort.size);
  const { assignments, capacities, findings } = allocateFixture(config, catalogue, cohort.candidates, cohort.preferences);
  const hash = scenarioFingerprint(config);
  return {
    run_id: `fx-${hash}`, status: "completed", origin: "fixture", kind, config, assignments, capacities, findings, error: null,
    provenance: {
      engine: FIXTURE_ENGINE, engine_version: FIXTURE_ENGINE_VERSION, simulation_seed: config.seed, registry_snapshot_id: config.registry_snapshot_id,
      cohort_id: cohort.manifest.cohort_id, cohort_generator_version: cohort.manifest.generator_version, cohort_seed: config.cohort.seed,
      cohort_size: config.cohort.size, config_hash: hash, created_at: createdAt,
    },
  };
}

function listItem(run: SimulationRun): RunListItem {
  return { run_id: run.run_id, status: run.status, origin: run.origin, kind: run.kind, name: run.config.name, preset: run.config.preset,
    admission_year: run.config.admission_year, cohort_id: run.provenance.cohort_id, cohort_size: run.config.cohort.size, created_at: run.provenance.created_at };
}

export function createFixtureSource(opts: { persist?: boolean } = {}): UniversityDataSource {
  const persist = opts.persist ?? true;
  const runs = new Map<string, SimulationRun>();
  let session: Stored[] | null = null;

  const loadSession = (): Stored[] => {
    if (session) return session;
    session = [];
    const s = persist ? storage() : null;
    if (s) {
      try {
        const parsed = JSON.parse(s.getItem(STORAGE_KEY) ?? "[]") as Stored[];
        if (Array.isArray(parsed)) session = parsed.filter((x) => x && typeof x === "object" && x.config && typeof x.created_at === "string");
      } catch {
        session = [];
      }
    }
    return session;
  };
  const saveSession = () => {
    const s = persist ? storage() : null;
    if (s && session) {
      try { s.setItem(STORAGE_KEY, JSON.stringify(session)); } catch { /* storage full or blocked: runs stay in memory */ }
    }
  };
  const runFor = (config: ScenarioConfig, kind: SimulationRun["kind"], createdAt: string): SimulationRun => {
    const id = fixtureRunId(config);
    const hit = runs.get(id);
    if (hit) return hit;
    const run = computeFixtureRun(config, kind, createdAt);
    runs.set(id, run);
    return run;
  };
  const allStored = () => [
    ...builtinConfigs().map((s) => ({ ...s, kind: "builtin_fixture" as const })),
    ...loadSession().map((s) => ({ ...s, kind: "session_fixture" as const })),
  ];
  const findRun = (runId: string): SimulationRun => {
    const stored = allStored().find((s) => fixtureRunId(s.config) === runId);
    if (!stored) throw notFound(`Run ${runId}`);
    return runFor(stored.config, stored.kind, stored.created_at);
  };
  const cohortOf = (id: string) => {
    const parsed = parseCohortId(id);
    if (!parsed) throw notFound(`Cohort ${id}`);
    return buildCohort(parsed.seed, parsed.size);
  };

  return {
    id: "fixture",
    origin: "fixture",
    capabilities: () => later(() => FIXTURE_CAPABILITIES),
    listSnapshots: () => later(() => [buildRegistryFixture().snapshot]),
    getCatalogue: (snapshotId) => later(() => {
      const c = buildRegistryFixture();
      if (c.snapshot.snapshot_id !== snapshotId) throw notFound(`Registry snapshot ${snapshotId}`);
      return c;
    }),
    queryPrograms: (query) => later(() => {
      const c = buildRegistryFixture();
      if (c.snapshot.snapshot_id !== query.snapshot_id) throw notFound(`Registry snapshot ${query.snapshot_id}`);
      return queryProgramRows(c, query);
    }),
    getProgram: (snapshotId, programCode) => later(() => {
      const c = buildRegistryFixture();
      if (c.snapshot.snapshot_id !== snapshotId) throw notFound(`Registry snapshot ${snapshotId}`);
      const program = c.programs.find((p) => p.program_code === programCode);
      if (!program) throw notFound(`Program ${programCode}`);
      const university = c.universities.find((u) => u.university_id === program.university_id);
      if (!university) throw new ApiError(409, "missing_university", `Program ${programCode} references no known university.`);
      return {
        snapshot: c.snapshot, program, university,
        admissions: c.admissions.filter((a) => a.program_id === program.program_id).sort((a, b) => a.admission_year - b.admission_year),
        tuition: c.tuition.filter((t) => t.program_id === program.program_id).sort((a, b) => a.academic_year_start - b.academic_year_start),
        issues: c.issues.filter((i) => i.program_id === program.program_id),
      };
    }),
    listCohorts: () => later(() => {
      const seen = new Map<string, CohortManifest>();
      const add = (seed: number, size: number) => {
        const id = cohortId(seed, size);
        if (!seen.has(id)) seen.set(id, buildCohort(seed, size).manifest);
      };
      add(DEFAULT_COHORT.seed, DEFAULT_COHORT.size);
      for (const s of allStored()) add(s.config.cohort.seed, s.config.cohort.size);
      return [...seen.values()];
    }),
    getCohort: (id) => later(() => cohortOf(id)),
    queryCandidates: (query) => later(() => {
      const cohort = cohortOf(query.cohort_id);
      const run = query.run_id ? findRun(query.run_id) : null;
      if (run && run.provenance.cohort_id !== cohort.manifest.cohort_id) {
        throw new ApiError(409, "cohort_mismatch", `Run ${run.run_id} used cohort ${run.provenance.cohort_id}, not ${cohort.manifest.cohort_id}.`);
      }
      return queryCandidateRows(candidateRows(cohort, buildRegistryFixture(), run), query, cohort);
    }),
    getCandidate: (cohortIdValue, candidateId, runId) => later(() => {
      const cohort = cohortOf(cohortIdValue);
      const run = runId ? findRun(runId) : null;
      const detail = candidateDetail(cohort, buildRegistryFixture(), run && run.provenance.cohort_id === cohort.manifest.cohort_id ? run : null, candidateId);
      if (!detail) throw notFound(`Candidate ${candidateId} in ${cohortIdValue}`);
      return detail;
    }),
    listRuns: () => later(() => allStored().map((s) => listItem(runFor(s.config, s.kind, s.created_at)))),
    getRun: (runId) => later(() => findRun(runId)),
    submitScenario: (config) => later((): SubmitResult => {
      const findings = validateScenario(config, buildRegistryFixture(), FIXTURE_CAPABILITIES, buildRegistryFixture().snapshot.snapshot_id);
      if (hasBlocking(findings)) {
        throw new ApiError(422, "invalid_scenario", "The scenario did not validate.", { reasons: findings.filter((f) => f.blocking).map((f) => f.message) });
      }
      const id = fixtureRunId(config);
      const existing = allStored().find((s) => fixtureRunId(s.config) === id);
      if (existing) return { run: runFor(existing.config, existing.kind, existing.created_at), duplicate_of: id };
      const stored: Stored = { config: JSON.parse(JSON.stringify(config)) as ScenarioConfig, created_at: new Date().toISOString() };
      loadSession().push(stored);
      saveSession();
      return { run: runFor(stored.config, "session_fixture", stored.created_at), duplicate_of: null };
    }),
  };
}
