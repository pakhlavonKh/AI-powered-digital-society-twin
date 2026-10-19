"use client";

import Link from "next/link";
import type { Schemas } from "@/lib/api/client";
import { fmtInt } from "@/lib/format";
import { NOT_RECORDED, runContext, useRecordedRun } from "@/lib/recordedRuns";
import { Icon } from "./Icon";
import { Badge, RunStateBadge } from "./StatusBadge";

/**
 * Dashboard card for a recorded (historical) run. Every value is read from the saved run folder through the API;
 * it is labelled as recorded so it is never mistaken for a run made in this session.
 */
export function RunSnapshot({ run, href, resultsHref }: { run: Schemas["ExperimentListItem"]; href: string; resultsHref: string }) {
  const { results, trials } = useRecordedRun(run.experiment_id);
  const r = results.data;
  const ctx = runContext(trials.data?.trials);
  const compared = r?.comparison_rows.length ?? 0;
  const saved = r?.trial_summaries.filter((t) => t.answers !== null).length;
  const pending = results.loading && !r ? "…" : NOT_RECORDED;
  return (
    <section className="card featured-run stack" aria-labelledby="featured-h">
      <div className="card-head" style={{ marginBottom: 0 }}>
        <span className="eyebrow"><Icon name="archive" size={15} /> Featured experiment</span>
        <Badge tone="neutral" glyph="⧉">Historical / Recorded</Badge>
      </div>
      <div>
        <h2 id="featured-h">Historical {ctx.location ? `${ctx.location} ` : ""}{run.name}</h2>
        <p className="small muted" style={{ margin: 0 }}>Recorded MatrAIx proof of concept. Saved output only; nothing is re-run here.</p>
      </div>
      <dl className="facts">
        <div><dt>Status</dt><dd><RunStateBadge state={run.display_state} /></dd></div>
        <div><dt>Personas</dt><dd>{r ? `${saved} of ${r.trial_summaries.length} with saved answers` : pending}</dd></div>
        <div><dt>Location</dt><dd>{ctx.location ?? (trials.loading ? "…" : NOT_RECORDED)}</dd></div>
        <div><dt>Synthetic population</dt><dd>{ctx.referenceYear ? `${ctx.referenceYear} reference year` : trials.loading ? "…" : NOT_RECORDED}</dd></div>
        <div><dt>Model</dt><dd><code>{run.model ?? NOT_RECORDED}</code></dd></div>
        <div><dt>Recorded results</dt><dd>{r && compared ? `${fmtInt(r.differing_values_recomputed)} of ${compared} answers differ` : r ? "No comparison recorded" : pending}</dd></div>
      </dl>
      {results.error ? <p className="small muted" role="status">Saved results could not be loaded: {results.error.message}</p> : null}
      <p className="small muted" style={{ margin: 0 }}>One recorded response per persona; differences describe these responses only.</p>
      <div className="row">
        <Link className="button primary small" href={href}>View {run.name} <Icon name="arrow" size={13} /></Link>
        <Link className="small" href={resultsHref}>Full run evidence</Link>
      </div>
    </section>
  );
}
