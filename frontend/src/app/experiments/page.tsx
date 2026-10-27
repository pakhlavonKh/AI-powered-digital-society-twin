"use client";

import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { Badge, RunStateBadge } from "@/components/StatusBadge";
import { v2, type ExperimentListItem } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

export default function ExperimentsPage() {
  const pop = useLinkPop();
  const list = useApi("v2:experiments", (signal) => v2<{ items: ExperimentListItem[] }>("/experiments", { signal }));
  return (
    <>
      <PageHeader title="Experiments" actions={<Link className="button primary small" href={withPop("/experiments/new", pop)}>New experiment</Link>}>
        Saved experiment definitions and their latest runs. A definition never runs until its reviewed plan is executed explicitly.
      </PageHeader>
      {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : null}
      {list.loading && !list.data ? <Loading what="experiments" /> : null}
      {list.data && list.data.items.length === 0 ? <EmptyState title="No experiments yet.">Design one in <Link href={withPop("/experiments/new", pop)}>New Experiment</Link>.</EmptyState> : null}
      {list.data && list.data.items.length ? (
        <div className="table-wrap"><table><caption>National experiments ({list.data.items.length})</caption>
          <thead><tr><th>Title</th><th>Backend</th><th className="num">Sample</th><th>Latest run</th><th className="num">Runs</th><th>Created</th></tr></thead>
          <tbody>{list.data.items.map((e) => (
            <tr key={e.experiment_id}>
              <th>{e.title}<div className="small muted"><code>{e.experiment_id}</code></div></th>
              <td>{e.backend === "stub" ? <Badge tone="fake" glyph="◇">test stub</Badge> : <Badge tone="info">{`AI Agent · ${e.transport === "live" ? "live" : "simulated"}`}</Badge>} {e.model ? <code>{e.model}</code> : null}</td>
              <td className="num">{fmtInt(e.sample_size)}</td>
              <td>{e.latest_run ? <Link href={withPop(`/results/${e.latest_run.run_id}`, pop)}><RunStateBadge state={e.latest_run.state} /></Link> : <span className="muted">Not run</span>}</td>
              <td className="num">{e.run_count}</td><td className="small">{e.created_at}</td>
            </tr>))}</tbody></table></div>
      ) : null}
      <p className="small muted">The historical two-persona Ankara survey runs (run1–run3) are kept unchanged under <Link href="/historical/results">Historical</Link>.</p>
    </>
  );
}
