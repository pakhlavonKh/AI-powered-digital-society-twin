/**
 * Which data source the University Simulation dashboard uses.
 *
 * "fixture": deterministic synthetic registry, cohort and illustrative fixture runs, computed in the browser.
 * "api":     the registry/placement API adapter. It currently reports "pending backend integration" for every call,
 *            because no endpoint exists yet (see apiSource.ts).
 *
 * This is a source constant rather than an environment variable on purpose: the workbench keeps environment values out
 * of the client bundle (next.config.ts, scripts/check_bundle.sh).
 */
export type UniversitySourceMode = "fixture" | "api";

export const UNIVERSITY_DATA_SOURCE: UniversitySourceMode = "fixture";
