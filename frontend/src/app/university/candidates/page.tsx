"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { CandidateExplorer } from "@/components/university/CandidateExplorer";
import { FixtureNotice, SnapshotGate } from "@/components/university/Gate";
import { candidateStateFromParams, candidateStateToParams, type CandidateUrlState } from "@/lib/university/candidates";
import { useRuns, useUniversitySource } from "@/lib/university/context";
import type { RegistrySnapshot } from "@/lib/university/types";
import { useApi } from "@/lib/useApi";

/**
 * URL: `run` (absent = first run, `none` = no run), `cohort` (used only without a run), `candidate` (detail),
 * plus the filter parameters in candidateStateToParams.
 */
function Explorer({ snapshot }: { snapshot: RegistrySnapshot }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const source = useUniversitySource();
  const runs = useRuns();
  const cohorts = useApi(`uni:${source.id}:cohorts`, (signal) => source.listCohorts(signal));
  if (runs.error) return <ErrorState error={runs.error} onRetry={runs.reload} what="simulation runs" />;
  if (cohorts.error) return <ErrorState error={cohorts.error} onRetry={cohorts.reload} what="cohorts" />;
  if (!runs.data || !cohorts.data) return <Loading what="cohorts and runs" />;

  const runParam = params.get("run");
  const runId = runParam === "none" ? null : runParam ?? runs.data[0]?.run_id ?? null;
  const run = runs.data.find((r) => r.run_id === runId);
  const cohortId = run?.cohort_id ?? params.get("cohort") ?? cohorts.data[0]?.cohort_id ?? "";
  const replace = (mutate: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(params.toString());
    mutate(next);
    router.replace(`${pathname}${next.toString() ? `?${next.toString()}` : ""}`, { scroll: false });
  };
  return (
    <CandidateExplorer snapshot={snapshot} cohorts={cohorts.data} runs={runs.data} cohortId={cohortId} runId={run ? run.run_id : null}
      state={candidateStateFromParams(params)} selected={params.get("candidate")}
      onChange={(s: CandidateUrlState) => replace((p) => { const n = candidateStateToParams(s, p); for (const k of [...p.keys()]) p.delete(k); n.forEach((v, k) => p.append(k, v)); })}
      onRun={(id) => replace((p) => { p.set("run", id ?? "none"); p.delete("page"); if (!id) p.set("cohort", cohortId); else p.delete("cohort"); })}
      onCohort={(id) => replace((p) => { p.set("cohort", id); p.set("run", "none"); p.delete("page"); p.delete("candidate"); })}
      onSelect={(id) => replace((p) => { if (id) p.set("candidate", id); else p.delete("candidate"); })} />
  );
}

export default function CandidatesPage() {
  return (
    <>
      <PageHeader title="Synthetic Candidate Explorer">
        Fictional applicants used by the placement simulation: score type, synthetic achievement proxy and ranked program preferences, with placement
        outcomes from a selected simulation run. Not real students.
      </PageHeader>
      <FixtureNotice kind="candidates" />
      <SnapshotGate>{(snapshot) => <Explorer snapshot={snapshot} />}</SnapshotGate>
    </>
  );
}
