"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { OriginBadge, RunStateBadge } from "@/components/StatusBadge";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

function RunTable({ items, caption, linkBuild }: { items: Schemas["ExperimentListItem"][]; caption: string; linkBuild: string | null }) {
  if (!items.length) return <EmptyState title="None." />;
  return (
    <div className="table-wrap">
      <table>
        <caption>{caption}</caption>
        <thead><tr><th scope="col">Run</th><th scope="col">Origin</th><th scope="col">State</th><th scope="col">Model</th><th scope="col" className="num">Trials</th><th scope="col" className="num">Differing values</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.experiment_id}>
              <th scope="row">
                <Link href={withBuild(`/results/${encodeURIComponent(r.experiment_id)}`, linkBuild)}>{r.name}</Link>
                <div className="small muted"><code>{r.experiment_id}</code></div>
              </th>
              <td><OriginBadge origin={r.origin} /></td>
              <td><RunStateBadge state={r.display_state} /><div className="small muted">{r.display_state_reason}</div></td>
              <td><code>{r.model ?? "–"}</code></td>
              <td className="num">{r.trial_count}</td>
              <td className="num">{r.differing_values ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ResultsPage() {
  const params = useSearchParams();
  const linkBuild = params.get("build");
  const runs = useApi("experiments", (signal) => unwrap(api.GET("/api/v1/experiments", { signal })));
  const items = runs.data?.items ?? [];
  const imported = items.filter((i) => i.origin === "imported" && i.evidence_kind !== "fake");
  const fake = items.filter((i) => i.evidence_kind === "fake" || i.kind === "fake_smoke");
  const managed = items.filter((i) => i.origin === "managed");

  return (
    <>
      <PageHeader title="Results">
        Recorded run folders imported read-only, and runs managed by this workbench. States come from the files present, not from folder names.
      </PageHeader>
      <SyntheticNotice kind="responses" />
      {runs.loading && !runs.data ? <Loading what="results" /> : null}
      {runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} /> : null}
      {runs.data ? (
        <>
          <section className="card stack" aria-labelledby="live-h">
            <h2 id="live-h">Recorded A/B runs and live attempts</h2>
            <p className="small muted">Imported historical evidence. Nothing here was re-run; viewing it is not reproduction.</p>
            <RunTable items={imported} caption="Imported run folders" linkBuild={linkBuild} />
          </section>
          <section className="card stack" aria-labelledby="fake-h">
            <h2 id="fake-h">Fake smoke runs</h2>
            <Notice tone="info" title="Wiring checks, not model behaviour.">These runs use a deterministic fake transport and make zero provider calls; their answers say nothing about personas.</Notice>
            <RunTable items={fake} caption="Smoke runs" linkBuild={linkBuild} />
          </section>
          <section className="card stack" aria-labelledby="managed-h">
            <h2 id="managed-h">Managed experiments</h2>
            <RunTable items={managed} caption="Drafts and runs created in this workbench" linkBuild={linkBuild} />
          </section>
        </>
      ) : null}
    </>
  );
}
