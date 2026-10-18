"use client";

import Link from "next/link";
import { api, unwrap } from "@/lib/api/client";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";
import { fmtInt, fmtUsd } from "@/lib/format";
import { RunStateBadge } from "./StatusBadge";
import { Icon } from "./Icon";

export function RunSnapshot({ id, name, build }: { id: string; name: string; build: string | null }) {
  const result = useApi(`snapshot:${id}`, (signal) => unwrap(api.GET("/api/v1/experiments/{experiment_id}/results", {params:{path:{experiment_id:id}},signal})));
  const r=result.data;
  return <section className="card run-snapshot"><div className="snapshot-intro"><span className="eyebrow"><Icon name="experiment" size={16}/> Featured recorded experiment</span><h2>{name}</h2><p className="small muted">{r?.model ?? "Recorded results"} · {r?.trial_summaries.length ?? "—"} personas</p><div className="row"><RunStateBadge state={r?.display_state ?? "completed"}/><Link href={withBuild(`/historical/results/${encodeURIComponent(id)}`,build)} className="button primary small">View results <Icon name="arrow" size={14}/></Link></div></div><div className="snapshot-chart"><h3>Recorded answer comparison</h3>{r ? <><div className="answer-bar-row"><span>Different values</span><div><i style={{width:`${r.comparison_rows.length ? (r.differing_values_recomputed ?? 0)/r.comparison_rows.length*100 : 0}%`}}/></div><b>{fmtInt(r.differing_values_recomputed)}</b></div><div className="answer-bar-row"><span>Same values</span><div><i style={{width:`${r.comparison_rows.length ? (r.comparison_rows.length-(r.differing_values_recomputed ?? 0))/r.comparison_rows.length*100 : 0}%`}}/></div><b>{r.comparison_rows.length-(r.differing_values_recomputed ?? 0)}</b></div><p className="small muted">{r.comparison_rows.length} questions · {r.usage?.cost_usd != null ? `${fmtUsd(r.usage.cost_usd)} estimated cost` : "Cost not recorded"}<br/>A comparison of these recorded responses only.</p></> : <p className="muted">{result.error ? "Comparison unavailable" : "Loading saved comparison…"}</p>}</div></section>;
}
