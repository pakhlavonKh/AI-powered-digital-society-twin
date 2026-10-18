"use client";

import Link from "next/link";
import { useState } from "react";
import { api, unwrap } from "@/lib/api/client";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";
import { filtersToQuery, type AgeGroup, type MaritalStatus } from "@/lib/filters";
import { Icon } from "./Icon";
import { Badge } from "./StatusBadge";
import { ErrorState, Loading } from "./States";

function Preview({buildId,recordId,linkBuild,position}:{buildId:string;recordId:string;linkBuild:string|null;position:number}) {
 const view=useApi(`gallery:${buildId}:${recordId}`,signal=>unwrap(api.GET("/api/v1/personas/{build_id}/{record_id}",{params:{path:{build_id:buildId,record_id:recordId}},signal})));
 const v=view.data;const a=v?.source_card.attributes;const stored=!!v?.personas.length;
 return <article className="card persona-preview"><div className="persona-preview-head"><span className={`persona-avatar tone-${position%3}`}><Icon name="persona" size={35}/></span><div><h3>{recordId}</h3><Badge tone={stored?"good":"neutral"} glyph={stored?"✓":"·"}>{stored?"Synthetic persona":"Source card"}</Badge></div></div>{v?<><dl className="kv"><dt>Province</dt><dd>{v.source_card.context.province}</dd><dt>Age group</dt><dd>{a?.age_group}</dd><dt>Marital status</dt><dd>{a?.marital_status ? v.source_card.display_translations.marital_status?.[a.marital_status] ?? a.marital_status : "Not recorded"}</dd></dl><div className="card-source">{stored?"Model-visible attributes":"Population attributes"}<p style={{margin:"6px 0 0"}}>{stored?v.personas[0].prompt_visible_fields.map(f=>f.replace(/^dst_/,"").replaceAll("_"," ")).slice(0,3).join(" · "):"No persona YAML exists yet"}</p></div></>:<p className="small muted">{view.error?"Could not load resident":"Loading source card…"}</p>}<div className="row"><Link className="button small" href={withBuild('/personas',linkBuild,{record:recordId})}>View details</Link><Link className="button primary small" href={withBuild('/cohorts',linkBuild,{id:recordId})}>Add to cohort <Icon name="arrow" size={12}/></Link></div></article>;
}

export function PersonaGallery({buildId,linkBuild}:{buildId:string;linkBuild:string|null}) {
 const [age,setAge]=useState("");const [marital,setMarital]=useState("");const [page,setPage]=useState(0);
 const cats=useApi(`gallery-categories:${buildId}`,signal=>unwrap(api.GET('/api/v1/builds/{build_id}/summary',{params:{path:{build_id:buildId}},signal})));
 const query=filtersToQuery({age_groups:age?[age as AgeGroup]:undefined,marital_statuses:marital?[marital as MaritalStatus]:undefined});
 const rows=useApi(`gallery-records:${buildId}:${age}:${marital}:${page}`,signal=>unwrap(api.GET('/api/v1/builds/{build_id}/records',{params:{path:{build_id:buildId},query:{...query,limit:6,offset:page*6}},signal})));
 const ids=rows.data?.items.map(r=>r.person_id) ?? [];
 const options=(f:string)=>cats.data?.distributions.find(d=>d.field===f)?.categories??[];
 return <section className="stack" aria-label="Browse resident cards"><div className="card row" style={{padding:"12px 16px"}}><div className="field" style={{flex:1}}><label htmlFor="gallery-province">Province</label><select id="gallery-province" value={"scope"} disabled><option value="scope">Selected build geography</option></select></div><div className="field" style={{flex:1}}><label htmlFor="gallery-age">Age group</label><select id="gallery-age" value={age} onChange={e=>{setAge(e.target.value);setPage(0)}}><option value="">All</option>{options('age_group').map(c=><option key={c.value}>{c.value}</option>)}</select></div><div className="field" style={{flex:1}}><label htmlFor="gallery-marital">Marital status</label><select id="gallery-marital" value={marital} disabled={!options('marital_status').length} onChange={e=>{setMarital(e.target.value);setPage(0)}}><option value="">All</option>{options('marital_status').map(c=><option key={c.value} value={c.value}>{cats.data?.display_translations.marital_status?.[c.value]??c.value}</option>)}</select></div><button className="button small" onClick={()=>{setAge("");setMarital("");setPage(0)}} style={{alignSelf:"end"}}>Reset</button></div>{rows.error?<ErrorState error={rows.error} onRetry={rows.reload}/>:null}{rows.loading&&!rows.data?<Loading what="resident cards"/>:null}<div className="persona-grid">{ids.map((id,i)=><Preview key={id} buildId={buildId} recordId={id} linkBuild={linkBuild} position={i}/>)}</div>{rows.data?<div className="row" style={{justifyContent:"space-between"}}><span className="small muted">{rows.data.total_matching} matching residents · Profile symbols are illustrative, not personal attributes.</span><div className="row"><button className="button small" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Previous cards</button><button className="button small" disabled={(page+1)*6>=rows.data.total_matching} onClick={()=>setPage(p=>p+1)}>Next cards</button></div></div>:null}</section>;
}
