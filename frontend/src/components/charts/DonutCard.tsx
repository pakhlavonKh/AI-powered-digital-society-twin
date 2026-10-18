"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { useState } from "react";
import { fmtInt, fmtPct } from "@/lib/format";
const COLORS=["#2e7eff","#ed7698","#f1b75c","#25bdd6","#7d85d5"];
export function DonutCard({title,rows,total}:{title:string;rows:{category:string;label:string;count:number;share:number|null}[];total:number}) {
 const [table,setTable]=useState(false);
 return <figure className="chart-figure donut-card"><figcaption><span className="chart-title">{title}</span><button type="button" className="button small" aria-pressed={table} onClick={()=>setTable(!table)}>{table?"Show chart":"Show table"}</button></figcaption>{table?<div className="table-wrap"><table><caption>{title}; matching residents</caption><thead><tr><th>Category</th><th>Count</th><th>Share</th></tr></thead><tbody>{rows.map((r)=><tr key={r.category}><th>{r.label}</th><td>{fmtInt(r.count)}</td><td>{fmtPct(r.share)}</td></tr>)}</tbody></table></div>:<div className="donut-layout"><div className="donut-plot" role="img" aria-label={`${title}: ${rows.map(r=>`${r.label} ${r.count}`).join(', ')}; ${total} residents total.`}><ResponsiveContainer width="100%" height={220} minWidth={0} initialDimension={{width:220,height:220}}><PieChart><Pie data={rows} dataKey="count" nameKey="label" innerRadius="64%" outerRadius="85%" paddingAngle={1} stroke="none" isAnimationActive={false}>{rows.map((r,i)=><Cell key={r.category} fill={COLORS[i%COLORS.length]}/>)}</Pie><Tooltip contentStyle={{background:'#14232f',border:'1px solid #344b61',borderRadius:6,color:'#f2f6fc'}} itemStyle={{color:'#f2f6fc'}}/></PieChart></ResponsiveContainer><div className="donut-center"><strong>{fmtInt(total)}</strong><span>residents</span></div></div><div className="donut-legend">{rows.map((r,i)=><div key={r.category}><i style={{background:COLORS[i%COLORS.length]}}/><span>{r.label}</span><b>{fmtPct(r.share)}</b></div>)}</div></div>}</figure>;
}
