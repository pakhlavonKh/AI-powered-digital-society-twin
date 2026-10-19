"use client";

import { api, unwrap, type Schemas } from "./api/client";
import { useApi } from "./useApi";

type ListItem = Schemas["ExperimentListItem"];
type Trial = Schemas["Trial"];

/**
 * The recorded run to feature: the last completed run in the recorded-runs list (today: run3). It is chosen by its
 * recorded state, never by name, so a newer completed run takes its place without code changes.
 */
export function featuredRun(items: ListItem[] | undefined): ListItem | undefined {
  return items?.filter((r) => r.display_state === "completed").at(-1);
}

export function useRecordedRuns() {
  return useApi("v1:experiments", (signal) => unwrap(api.GET("/api/v1/experiments", { signal })));
}

/** Saved results and trials of one recorded run. Read-only: nothing is re-run or regenerated. */
export function useRecordedRun(id: string | undefined) {
  const results = useApi(id ? `v1:results:${id}` : null, (signal) =>
    unwrap(api.GET("/api/v1/experiments/{experiment_id}/results", { params: { path: { experiment_id: id! } }, signal })));
  const trials = useApi(id ? `v1:trials:${id}` : null, (signal) =>
    unwrap(api.GET("/api/v1/experiments/{experiment_id}/trials", { params: { path: { experiment_id: id! } }, signal })));
  return { results, trials };
}

/** A persona-snapshot dimension shared by every trial (e.g. the province), or null when absent or not shared. */
export function sharedDimension(trials: Trial[] | undefined, key: string): string | null {
  const values = new Set((trials ?? []).map((t) => t.persona_snapshot?.dimensions?.[key]).filter((v): v is string => Boolean(v)));
  return values.size === 1 ? [...values][0] : null;
}

/** Facts read from the persona snapshots saved with the run (the SocietyTwin dst_* dimensions). */
export function runContext(trials: Trial[] | undefined) {
  return {
    location: sharedDimension(trials, "dst_residence_province"),
    referenceYear: sharedDimension(trials, "dst_reference_year"),
    instrument: trials?.find((t) => t.instrument?.title || t.instrument?.id)?.instrument ?? null,
  };
}

export const RUN_KIND_LABELS: Record<string, string> = {
  legacy_ab: "Survey · two-persona A/B comparison",
  fake_smoke: "Fake smoke run (wiring check)",
};

export const NOT_RECORDED = "Not recorded";
