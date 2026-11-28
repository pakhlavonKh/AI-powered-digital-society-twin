"use client";

import { useSelectedSnapshot, useUniversityCapabilities } from "@/lib/university/context";
import type { RegistrySnapshot } from "@/lib/university/types";
import { ErrorState, Loading, UnavailableState } from "../States";

const TEXT = {
  registry: "Synthetic institutions, programs, quotas, ranks and fees generated for UI exploration (fixture:university-ui-v1). Live workbook queries are exposed separately at /api/v2/university-registry/*.",
  candidates: "Fictional synthetic applicants and artificial preference lists. Not real students, not YKS scores or ranks, and not a behavioural model.",
  simulation: "This explorer uses an illustrative browser-side fixture allocation. Live counterfactual placement and multi-semester simulations are available in the University Placement Studio (/university).",
};

/** Always shown while fixture data is in use, so fixture output is never mistaken for real data. */
export function FixtureNotice({ kind }: { kind: keyof typeof TEXT }) {
  const caps = useUniversityCapabilities();
  if (caps.data?.origin === "local_preview") {
    return (
      <p className="notice warn" role="note">
        <strong>Local preview. </strong>Real ÖSYM 2025 Table 4 records (undergraduate, general quota) read from git-ignored files on this machine, in a
        development build only. Not committed or published; ÖSYM reuse permission is pending. Candidates and simulations are not part of this preview.
      </p>
    );
  }
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
