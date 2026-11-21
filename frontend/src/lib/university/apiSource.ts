/**
 * Placeholder for the real registry / candidate / placement API.
 *
 * No such endpoint exists: frontend/openapi.json (the FastAPI snapshot) has no university, candidate or placement
 * paths, and the registry branch (feature/university-sqlite) exposes only a Python API. This adapter therefore never
 * guesses a URL. Every call fails with an explicit 501 "pending backend integration" error that the UI renders as
 * such. When endpoints are agreed, implement these methods with the typed client (src/lib/api/v2.ts style), map the
 * responses into ./types, and switch UNIVERSITY_DATA_SOURCE in ./config.ts.
 */
import { ApiError } from "../api/client";
import type { UniversityDataSource } from "./source";
import type { UniversityCapabilities } from "./types";

const DETAIL = "No university registry, candidate or placement endpoint exists in the SocietyTwin API yet (frontend/openapi.json has none).";

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
    queryCandidates: () => pending("Synthetic candidates"),
    getCandidate: () => pending("Candidate details"),
    listRuns: () => pending("Simulation runs"),
    getRun: () => pending("Simulation run"),
    submitScenario: () => pending("Scenario execution"),
  };
}
