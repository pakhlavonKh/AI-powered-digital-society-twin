"use client";

import Link from "next/link";
import { useState } from "react";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";
import { AnswerCell } from "./AnswerCell";

export function PersonaComparison({recordId,evidence,linkBuild}:{recordId:string;evidence:Schemas["PersonaView"]["historical_prompt_evidence"];linkBuild:string|null}) {
 const runs=[...new Map(evidence.filter(e=>e.display_state==='completed').map(e=>[e.experiment_id,e])).values()];
 const [selected,setSelected]=useState("");const id=selected||runs.at(-1)?.experiment_id;
 const result=useApi(id?`persona-comparison:${id}`:null,signal=>unwrap(api.GET('/api/v1/experiments/{experiment_id}/results',{params:{path:{experiment_id:id!}},signal})));
 const r=result.data;const other=r?.trial_summaries.find(t=>t.persona_id!==recordId);
 return <section className="card stack persona-comparison"><div className="card-head"><h3>Compare recorded answers</h3></div>{runs.length?<><div className="field"><label htmlFor="comparison-run">Recorded experiment</label><select id="comparison-run" value={id} onChange={e=>setSelected(e.target.value)}>{runs.map(e=><option key={e.experiment_id} value={e.experiment_id}>{e.experiment_id.replace(/^imp_/,"")}</option>)}</select></div>{r?<><p className="small muted">{recordId} compared with {other?.persona_id??"the other recorded persona"}. One saved response each.</p><div className="row"><strong className="small">{r.differing_values_recomputed} / {r.comparison_rows.length} different values</strong><Link className="small" href={withBuild(`/historical/results/${id}`,linkBuild)}>Full comparison ↗</Link></div><div className="table-wrap"><table><caption>Saved answers; no new model calls</caption><thead><tr><th>Question</th><th>Persona A</th><th>Persona B</th></tr></thead><tbody>{r.comparison_rows.map(row=><tr key={row.question_id}><th>{row.prompt??row.question_id}</th><td><AnswerCell answer={row.answer_a}/></td><td><AnswerCell answer={row.answer_b}/></td></tr>)}</tbody></table></div></>:<p className="small muted">{result.error?"Comparison unavailable.":"Loading saved comparison…"}</p>}</>:<p className="small muted">No completed A/B comparison is recorded for this resident. New answers are never invented for the preview.</p>}</section>;
}
