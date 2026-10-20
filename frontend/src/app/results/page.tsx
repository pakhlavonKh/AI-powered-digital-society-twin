"use client";

import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { Badge, RunStateBadge } from "@/components/StatusBadge";
import { api, unwrap } from "@/lib/api/client";
import { v2, type RunView } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

export default function ResultsPage() {
  const pop = useLinkPop();
  const runs = useApi("v2:runs", (signal) => v2<{ items: RunView[] }>("/runs", { signal }));
  const historical = useApi("v1:experiments", (signal) => unwrap(api.GET("/api/v1/experiments", { signal })));
  const imported = historical.data?.items.filter((i) => i.origin === "imported") ?? [];
  return (
    <>
      <PageHeader title="Results">Structured responses of national experiment runs, and the historical Ankara runs (read-only evidence).</PageHeader>
      <section className="card" aria-labelledby="nat-h">
        <h2 id="nat-h">National experiment runs</h2>
        {runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} /> : null}
        {runs.loading && !runs.data ? <Loading what="runs" /> : null}
        {runs.data && runs.data.items.length === 0 ? <EmptyState title="No experiment results yet." /> : null}
        {runs.data && runs.data.items.length ? (
          <div className="table-wrap"><table><caption>{runs.data.items.length} runs</caption>
            <thead><tr><th>Run</th><th>State</th><th>Backend</th><th className="num">Personas</th><th className="num">Valid responses</th><th className="num">Provider calls</th><th>Finished</th></tr></thead>
            <tbody>{runs.data.items.map((r) => (
              <tr key={r.run_id}>
                <th><Link href={withPop(`/results/${r.run_id}`, pop)}>{r.title ?? r.run_id}</Link><div className="small muted"><code>{r.run_id}</code>{r.kind === "replay" ? ` · replay of ${r.replay_of}` : ""}</div></th>
                <td><RunStateBadge state={r.state} /></td>
                <td>{r.backend === "stub" ? <Badge tone="fake" glyph="◇">stub — not model output</Badge> : r.backend ?? "–"}</td>
                <td className="num">{fmtInt(r.personas)}</td><td className="num">{fmtInt(r.valid_responses)} / {fmtInt(r.final_responses)}</td>
                <td className="num">{fmtInt(r.provider_calls)}</td><td className="small">{r.finished_at ?? "–"}</td>
              </tr>))}</tbody></table></div>
        ) : null}
      </section>
      <section className="card" aria-labelledby="hist-h">
        <div className="card-head"><h2 id="hist-h">Historical Ankara runs</h2><Link href="/historical/results">Open historical results</Link></div>
        {historical.error ? <ErrorState error={historical.error} /> : null}
        {imported.length ? (
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{imported.map((i) => (
            <li key={i.experiment_id}><Link href={`/historical/results/${encodeURIComponent(i.experiment_id)}`}>{i.name}</Link> · <RunStateBadge state={i.display_state} /> · <code>{i.model ?? "–"}</code></li>))}</ul>
        ) : <p className="small muted">No imported run folders found in this checkout.</p>}
      </section>
    </>
  );
}
