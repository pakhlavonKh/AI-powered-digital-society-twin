"use client";

import { useSearchParams } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { useApi } from "../useApi";
import { createPendingApiSource } from "./apiSource";
import { UNIVERSITY_DATA_SOURCE, type UniversitySourceMode } from "./config";
import { createFixtureSource } from "./fixtureSource";
import { createLocalPreviewSource, localPreviewRequested } from "./localPreviewSource";
import type { UniversityDataSource } from "./source";

let defaultSource: UniversityDataSource | null = null;

/** The configured source, created once per browser session. */
export function getDefaultUniversitySource(): UniversityDataSource {
  if (!defaultSource) {
    const mode = UNIVERSITY_DATA_SOURCE as UniversitySourceMode;
    defaultSource = mode === "api" ? createPendingApiSource() : createFixtureSource();
  }
  return defaultSource;
}

const SourceContext = createContext<UniversityDataSource | null>(null);

/** Optional: inject a different source (tests, or a future API adapter). Without it the configured source is used. */
export function UniversitySourceProvider({ source, children }: { source: UniversityDataSource; children: ReactNode }) {
  return <SourceContext.Provider value={source}>{children}</SourceContext.Provider>;
}

const localSources = new Map<string, UniversityDataSource>();

/**
 * The injected source, else the opt-in local preview (`?source=local-preview`, development builds only), else the
 * configured source. Logos resolve from each record's official_university_code whichever source supplies it.
 */
export function useUniversitySource(): UniversityDataSource {
  const injected = useContext(SourceContext);
  const params = useSearchParams();
  if (injected) return injected;
  if (localPreviewRequested(params)) {
    const scope = params.get("scope") === "logos" ? "logos" : "all";
    if (!localSources.has(scope)) localSources.set(scope, createLocalPreviewSource(scope));
    return localSources.get(scope)!;
  }
  return getDefaultUniversitySource();
}

export function useUniversityCapabilities() {
  const source = useUniversitySource();
  return useApi(`uni:${source.id}:caps`, (signal) => source.capabilities(signal));
}

/**
 * The registry snapshot in use: `?snapshot=` when given, otherwise the newest snapshot. A requested snapshot that does
 * not exist is reported as missing; nothing else is substituted.
 */
export function useSelectedSnapshot() {
  const source = useUniversitySource();
  const params = useSearchParams();
  const requested = params.get("snapshot");
  const list = useApi(`uni:${source.id}:snapshots`, (signal) => source.listSnapshots(signal));
  const snapshots = list.data ?? [];
  const byId = requested ? snapshots.find((s) => s.snapshot_id === requested) ?? null : null;
  const fallback = !requested ? [...snapshots].sort((a, b) => (a.imported_at < b.imported_at ? 1 : -1))[0] ?? null : null;
  const snapshot = requested ? byId : fallback;
  return {
    snapshot, snapshotId: snapshot?.snapshot_id ?? null, snapshots, requested,
    missingId: requested && list.data && !byId ? requested : null,
    loading: list.loading, error: list.error, reload: list.reload,
  };
}

export function useCatalogue(snapshotId: string | null) {
  const source = useUniversitySource();
  return useApi(snapshotId ? `uni:${source.id}:catalogue:${snapshotId}` : null, (signal) => source.getCatalogue(snapshotId!, signal));
}

export function useRuns(nonce = 0) {
  const source = useUniversitySource();
  return useApi(`uni:${source.id}:runs:${nonce}`, (signal) => source.listRuns(signal));
}

export function useRun(runId: string | null) {
  const source = useUniversitySource();
  return useApi(runId ? `uni:${source.id}:run:${runId}` : null, (signal) => source.getRun(runId!, signal));
}

/** Same-origin link within the dashboard that keeps an explicitly chosen snapshot. */
export function uniHref(path: string, snapshot: string | null, extra?: Record<string, string | null | undefined>): string {
  const [base, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  if (snapshot) params.set("snapshot", snapshot);
  for (const [k, v] of Object.entries(extra ?? {})) {
    if (v === undefined || v === null || v === "") params.delete(k);
    else params.set(k, v);
  }
  const s = params.toString();
  return s ? `${base}?${s}` : base;
}
