/**
 * Data-access contract for the University Simulation dashboard. Components depend only on this interface, so the
 * fixture adapter can be replaced by a registry/placement API adapter without changing UI code.
 */
import type {
  CandidateDetail,
  CandidatePage,
  CandidateQuery,
  Cohort,
  CohortManifest,
  DataOrigin,
  ProgramDetail,
  ProgramPage,
  ProgramQuery,
  RegistryCatalogue,
  RegistrySnapshot,
  RunListItem,
  ScenarioConfig,
  SimulationRun,
  UniversityCapabilities,
} from "./types";

export type SubmitResult = {
  run: SimulationRun;
  /** Set when an identical configuration (same fingerprint) already had a run; no new run was created. */
  duplicate_of: string | null;
};

export interface UniversityDataSource {
  readonly id: string;
  readonly origin: DataOrigin;
  capabilities(signal?: AbortSignal): Promise<UniversityCapabilities>;
  listSnapshots(signal?: AbortSignal): Promise<RegistrySnapshot[]>;
  /** Every registry table for one snapshot (used for labels, scenario setup and result breakdowns). */
  getCatalogue(snapshotId: string, signal?: AbortSignal): Promise<RegistryCatalogue>;
  queryPrograms(query: ProgramQuery, signal?: AbortSignal): Promise<ProgramPage>;
  getProgram(snapshotId: string, programCode: string, signal?: AbortSignal): Promise<ProgramDetail>;
  listCohorts(signal?: AbortSignal): Promise<CohortManifest[]>;
  /** The whole cohort handoff (candidates and preferences), used for cohort-wide quality checks and score types. */
  getCohort(cohortId: string, signal?: AbortSignal): Promise<Cohort>;
  queryCandidates(query: CandidateQuery, signal?: AbortSignal): Promise<CandidatePage>;
  getCandidate(cohortId: string, candidateId: string, runId: string | null, signal?: AbortSignal): Promise<CandidateDetail>;
  listRuns(signal?: AbortSignal): Promise<RunListItem[]>;
  getRun(runId: string, signal?: AbortSignal): Promise<SimulationRun>;
  submitScenario(config: ScenarioConfig, signal?: AbortSignal): Promise<SubmitResult>;
}
