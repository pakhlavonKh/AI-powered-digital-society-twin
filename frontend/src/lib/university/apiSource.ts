/**
 * Placeholder adapter for wiring the /university/* explorer to /api/v2/university-registry/* and /api/v2/placement/*.
 *
 * Read-only SQLite registry endpoints (/api/v2/university-registry/*) and placement endpoints (/api/v2/placement/*)
 * exist in the FastAPI backend, while this UI explorer still reads from fixtureSource.ts (UNIVERSITY_DATA_SOURCE = "fixture").
 * Keeping this explicit 501 adapter prevents accidental unmapped fetches until the schemas are unified.
 */
import { ApiError } from "../api/client";
import type { UniversityDataSource } from "./source";
import type { UniversityCapabilities } from "./types";

const DETAIL = "The /university/* explorer adapter is not yet mapped to /api/v2/university-registry/* and /api/v2/placement/* (use UI fixtures or the live /university Placement Studio).";

function pending(what: string): Promise<never> {
  return Promise.reject(new ApiError(501, "pending_backend_integration", `${what}: pending backend integration.`, { reasons: [DETAIL] }));
}

export function createPendingApiSource(): UniversityDataSource {
  const caps: UniversityCapabilities = {
    origin: "api",
    registry: { available: false, detail: DETAIL },
    candidates: { available: false, detail: DETAIL },
    execution: { mode: "unavailable", detail: "No placement engine or scenario execution endpoint exists." },
    supported_presets: [],
    unsupported_presets: [
      { preset: "baseline", reason: "no placement API" }, { preset: "quota_increase", reason: "no placement API" },
      { preset: "quota_decrease", reason: "no placement API" }, { preset: "scholarship_change", reason: "no placement API" },
      { preset: "preference_change", reason: "no placement API" },
    ],
    limits: { max_cohort_size: 0, quota_adjustment_pct: [-90, 200] },
  };
  return {
    id: "api-pending",
    origin: "api",
    capabilities: () => Promise.resolve(caps),
    listSnapshots: () => pending("Registry snapshots"),
    getCatalogue: () => pending("Registry catalogue"),
    queryPrograms: () => pending("Program registry"),
    getProgram: () => pending("Program details"),
    listCohorts: () => pending("Candidate cohorts"),
    getCohort: () => pending("Candidate cohort"),
    queryCandidates: () => pending("Synthetic candidates"),
    getCandidate: () => pending("Candidate details"),
    listRuns: () => pending("Simulation runs"),
    getRun: () => pending("Simulation run"),
    submitScenario: () => pending("Scenario execution"),
  };
}
