"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading, UnavailableState } from "@/components/States";
import { DataKindBadge, DataQualityPanel, ProvenancePanel } from "@/components/university/common";
import { FixtureNotice, SnapshotGate } from "@/components/university/Gate";
import { PlacementCharts } from "@/components/university/PlacementCharts";
import { ResultsOverview, runProvenanceItems } from "@/components/university/ResultsOverview";
import { RunPicker } from "@/components/university/RunPicker";
import { UnplacedCandidates } from "@/components/university/UnplacedCandidates";
import { uniHref, useCatalogue, useRun, useRuns, useUniversitySource } from "@/lib/university/context";
import { runIntegrity, summarizeRun } from "@/lib/university/metrics";
import type { RegistrySnapshot } from "@/lib/university/types";
import { useApi } from "@/lib/useApi";

function Results({ snapshot }: { snapshot: RegistrySnapshot }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const source = useUniversitySource();
  const runs = useRuns();
  const runId = params.get("run") ?? runs.data?.[0]?.run_id ?? null;
  const run = useRun(runId);
  const catalogue = useCatalogue(run.data?.provenance.registry_snapshot_id ?? null);
  const cohortId = run.data?.provenance.cohort_id ?? null;
  const cohort = useApi(cohortId ? `uni:${source.id}:cohort:${cohortId}` : null, (signal) => source.getCohort(cohortId!, signal));
  const pick = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id) next.set("run", id); else next.delete("run");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  const explicit = params.get("snapshot");

  if (runs.error) return <ErrorState error={runs.error} onRetry={runs.reload} what="simulation runs" />;
  if (!runs.data) return <Loading what="simulation runs" />;
  if (runs.data.length === 0) {
    return <UnavailableState title="No simulation runs yet.">Configure and run a scenario in <Link href={uniHref("/university/scenarios", explicit)}>Scenario Setup</Link>.</UnavailableState>;
  }
  const r = run.data;
  const cat = catalogue.data;
  const scoreTypes = cohort.data ? new Map(cohort.data.candidates.map((c) => [c.candidate_id, c.score_type])) : undefined;
  const summary = r && cat ? summarizeRun(r, cat, scoreTypes) : null;
  const findings = r && cat ? runIntegrity(r, cat) : [];
  return (
    <div className="stack">
      <section className="card stack" aria-label="Run selection">
        <div className="compare-pickers">
          <RunPicker id="results-run" label="Simulation run" runs={runs.data} value={runId} onChange={pick} />
          <div className="row small" style={{ alignSelf: "end" }}>
            {r ? <><DataKindBadge kind="simulation" /><Link href={uniHref("/university/compare", explicit, { b: r.run_id })}>Compare this run</Link>
              <Link href={uniHref("/university/candidates", explicit, { run: r.run_id })}>Inspect candidates</Link></> : null}
          </div>
        </div>
        {r && r.config.registry_snapshot_id !== snapshot.snapshot_id ? <p className="notice warn small" style={{ margin: 0 }}>This run uses registry snapshot {r.config.registry_snapshot_id}, not the snapshot selected above.</p> : null}
      </section>
      {run.error ? <ErrorState error={run.error} onRetry={run.reload} what="simulation run" /> : null}
      {catalogue.error ? <ErrorState error={catalogue.error} onRetry={catalogue.reload} what="registry" /> : null}
      {cohort.error ? <ErrorState error={cohort.error} onRetry={cohort.reload} what="candidate cohort" /> : null}
      {(run.loading && !r) || (r && !cat && !catalogue.error) ? <Loading what="placement results" /> : null}
      {r && r.status !== "completed" ? <UnavailableState title={`Run ${r.run_id} is ${r.status}.`} reasons={r.error ? [r.error] : undefined}>Results appear when the run completes.</UnavailableState> : null}
      {r && r.status === "completed" && summary && cat ? (
        <div className={run.stale ? "stack is-stale" : "stack"}>
          <ResultsOverview s={summary} />
          <PlacementCharts s={summary} origin={r.origin} />
          {cohort.data ? <UnplacedCandidates run={r} cohort={cohort.data} snapshot={explicit} /> : <Loading what="unplaced candidates" />}
          <div className="grid-2">
            <ProvenancePanel title="Run provenance" origin={r.origin} items={runProvenanceItems(r)} />
            <DataQualityPanel title="Result validation" records={r.assignments.length} recordLabel="Assignments loaded" open
              incomplete={r.assignments.filter((a) => a.status !== "placed" && a.reason === null).length} incompleteNote="Non-placed candidates without a simulation reason"
              findings={findings} origin={r.origin} source={r.provenance.engine} version={r.provenance.engine_version} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function ResultsPage() {
  return (
    <>
      <PageHeader title="Placement Results">
        Outcomes of a university placement simulation run: placed and unplaced synthetic candidates, capacity use, preference satisfaction and
        breakdowns by institution, program, score type and scholarship. Simulated results, not historical admissions.
      </PageHeader>
      <FixtureNotice kind="simulation" />
      <SnapshotGate>{(snapshot) => <Results snapshot={snapshot} />}</SnapshotGate>
    </>
  );
}
