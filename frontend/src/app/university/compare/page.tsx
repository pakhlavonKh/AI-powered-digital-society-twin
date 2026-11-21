"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading, UnavailableState } from "@/components/States";
import { ProvenancePanel, ValidationList } from "@/components/university/common";
import { FixtureNotice, SnapshotGate } from "@/components/university/Gate";
import { runProvenanceItems } from "@/components/university/ResultsOverview";
import { RunPicker } from "@/components/university/RunPicker";
import { ScenarioComparison } from "@/components/university/ScenarioComparison";
import { uniHref, useCatalogue, useRun, useRuns, useUniversitySource } from "@/lib/university/context";
import { runCompatibility } from "@/lib/university/metrics";
import { hasBlocking } from "@/lib/university/scenario";
import { useApi } from "@/lib/useApi";

/** URL: `a` (reference run, default the first run) and `b` (modified run, default the second). */
function Compare() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const source = useUniversitySource();
  const runs = useRuns();
  const list = runs.data ?? [];
  const aId = params.get("a") ?? list[0]?.run_id ?? null;
  const bId = params.get("b") ?? list.find((r) => r.run_id !== aId)?.run_id ?? null;
  const runA = useRun(aId);
  const runB = useRun(bId);
  const catalogue = useCatalogue(runA.data?.provenance.registry_snapshot_id ?? null);
  const cohortId = runA.data?.provenance.cohort_id ?? null;
  const cohort = useApi(cohortId ? `uni:${source.id}:cohort:${cohortId}` : null, (signal) => source.getCohort(cohortId!, signal));
  const explicit = params.get("snapshot");
  const pick = (key: "a" | "b", id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set(key, id); else next.delete(key);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  if (runs.error) return <ErrorState error={runs.error} onRetry={runs.reload} what="simulation runs" />;
  if (!runs.data) return <Loading what="simulation runs" />;
  if (list.length < 2) {
    return <UnavailableState title="At least two runs are needed for a comparison.">Run another scenario in <Link href={uniHref("/university/scenarios", explicit)}>Scenario Setup</Link>.</UnavailableState>;
  }
  const a = runA.data;
  const b = runB.data;
  const findings = a && b ? runCompatibility(a, b) : [];
  const blocked = hasBlocking(findings);
  const scoreTypes = cohort.data ? new Map(cohort.data.candidates.map((c) => [c.candidate_id, c.score_type])) : undefined;
  return (
    <div className="stack">
      <section className="card stack" aria-label="Runs to compare">
        <div className="compare-pickers">
          <RunPicker id="compare-a" label="Scenario A (reference)" runs={list} value={aId} onChange={(id) => pick("a", id)} />
          <RunPicker id="compare-b" label="Scenario B (modified)" runs={list} value={bId} onChange={(id) => pick("b", id)} />
        </div>
        {a && b ? <ValidationList findings={findings} title="Compatibility" empty="The runs are compatible: same registry snapshot, admission year, cohort and engine." /> : null}
      </section>
      {runA.error ? <ErrorState error={runA.error} onRetry={runA.reload} what="scenario A" /> : null}
      {runB.error ? <ErrorState error={runB.error} onRetry={runB.reload} what="scenario B" /> : null}
      {catalogue.error ? <ErrorState error={catalogue.error} onRetry={catalogue.reload} what="registry" /> : null}
      {(!a || !b || !catalogue.data) && !runA.error && !runB.error && !catalogue.error ? <Loading what="runs to compare" /> : null}
      {a && b && blocked ? (
        <UnavailableState title="These runs cannot be compared." reasons={findings.filter((f) => f.blocking).map((f) => f.message)}>
          Choose two completed runs that share a registry snapshot, admission year and candidate cohort.
        </UnavailableState>
      ) : null}
      {a && b && !blocked && catalogue.data ? <ScenarioComparison runA={a} runB={b} catalogue={catalogue.data} scoreTypes={scoreTypes} snapshot={explicit} /> : null}
      {a && b ? (
        <div className="grid-2">
          <ProvenancePanel title="Scenario A provenance" origin={a.origin} items={runProvenanceItems(a)} />
          <ProvenancePanel title="Scenario B provenance" origin={b.origin} items={runProvenanceItems(b)} />
        </div>
      ) : null}
    </div>
  );
}

export default function ComparePage() {
  return (
    <>
      <PageHeader title="Scenario Comparison">
        Compare two compatible simulation runs: placement rate (in percentage points and relative change), unplaced candidates, institution and program
        capacity use, preference satisfaction and candidate-level outcome changes. Every difference is Scenario B − Scenario A.
      </PageHeader>
      <FixtureNotice kind="simulation" />
      <SnapshotGate>{() => <Compare />}</SnapshotGate>
    </>
  );
}
