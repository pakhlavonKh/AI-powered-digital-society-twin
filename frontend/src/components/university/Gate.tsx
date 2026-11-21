"use client";

import { useSelectedSnapshot, useUniversityCapabilities } from "@/lib/university/context";
import type { RegistrySnapshot } from "@/lib/university/types";
import { ErrorState, Loading, UnavailableState } from "../States";

const TEXT = {
  registry: "Synthetic institutions, programs, quotas, ranks and fees generated for UI development, shaped like the university SQLite registry. Not imported from the source workbook; no registry API exists yet.",
  candidates: "Fictional synthetic applicants and artificial preference lists. Not real students, not YKS scores or ranks, and not a behavioural model.",
  simulation: "Results come from an illustrative fixture allocation computed in your browser. No placement engine or API has run. Not a forecast or an official outcome.",
};

/** Always shown while fixture data is in use, so fixture output is never mistaken for real data. */
export function FixtureNotice({ kind }: { kind: keyof typeof TEXT }) {
  const caps = useUniversityCapabilities();
  if (caps.data && caps.data.origin !== "fixture") return null;
  return (
    <p className="notice synthetic" role="note">
      <strong>{kind === "simulation" ? "Fixture simulation. " : kind === "candidates" ? "Synthetic candidates. " : "Fixture data. "}</strong>{TEXT[kind]}
    </p>
  );
}

/** Renders children only for a resolved registry snapshot; otherwise loading, error or missing-snapshot states. */
export function SnapshotGate({ children }: { children: (snapshot: RegistrySnapshot) => React.ReactNode }) {
  const { snapshot, loading, error, reload, missingId } = useSelectedSnapshot();
  if (error) return <ErrorState error={error} onRetry={reload} what="registry snapshots" />;
  if (loading && !snapshot) return <Loading what="registry snapshots" />;
  if (missingId) return <UnavailableState title={`Registry snapshot ${missingId} does not exist.`}>Choose another snapshot above; nothing else was substituted.</UnavailableState>;
  if (!snapshot) return <UnavailableState title="No registry snapshot is available." reasons={["Import a registry workbook, or use the fixture data source."]} />;
  return <>{children(snapshot)}</>;
}
