"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { PopulationGate } from "@/components/national/common";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";
import { v2, type Cohort, type SamplePersonas } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

const CARD_FIELDS: [string, string][] = [["province_name", "Province"], ["age_group", "Age group"], ["sex", "Sex"], ["marital_status", "Marital status"],
  ["education_level", "Education"], ["labour_status", "Labour status"]];

function SamplePicker({ value, onChange }: { value: string | null; onChange: (id: string) => void }) {
  const cohorts = useApi("v2:cohorts", (signal) => v2<{ items: Cohort[] }>("/cohorts", { signal }));
  const options = cohorts.data?.items.flatMap((c) => c.samples.map((s) => ({ id: s.sample_id, label: `${c.name} · ${s.config.method} · n=${s.selected} · seed ${s.config.seed}` }))) ?? [];
  if (cohorts.data && options.length === 0) return <EmptyState title="No cohort samples yet.">Draw a seeded sample on the <Link href="/cohorts">Cohorts</Link> page; its members become personas here.</EmptyState>;
  return (
    <div className="field"><label htmlFor="sample-pick">Cohort sample</label>
      <select id="sample-pick" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a sample…</option>
        {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select></div>
  );
}

function Personas() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const pop = useLinkPop();
  const sampleId = params.get("sample");
  const [page, setPage] = useState(0);
  const data = useApi(sampleId ? `v2:sp:${sampleId}:${page}` : null, (signal) => v2<SamplePersonas>(`/samples/${sampleId}/personas`, { query: { offset: page * 24, limit: 24 }, signal }));
  return (
    <div className="stack">
      <section className="card"><SamplePicker value={sampleId} onChange={(id) => { setPage(0); const n = new URLSearchParams(params.toString()); n.set("sample", id); router.replace(`${pathname}?${n}`); }} /></section>
      <Notice tone="info" title="Synthetic record ≠ persona ≠ AI agent.">A <strong>synthetic record</strong> is a row of the population. A <strong>persona</strong> is a
        template-based view of one record (the attributes a model may see). An <strong>AI agent</strong> exists only while an experiment runs the persona. Nothing here calls a model.</Notice>
      {data.error ? <ErrorState error={data.error} onRetry={data.reload} /> : null}
      {sampleId && data.loading && !data.data ? <Loading what="personas" /> : null}
      {data.data ? (
        <>
          <p className="small muted">{fmtInt(data.data.total)} personas in this sample · template {data.data.template_version}</p>
          <div className="persona-cards">
            {data.data.items.map((p) => (
              <article className="card persona-card2" key={p.synthetic_id}>
                <div className="row" style={{ justifyContent: "space-between" }}><h3>{p.synthetic_id}</h3>
                  {p.eligibility.adult ? <Badge tone="good" glyph="✓">Adult</Badge> : <Badge tone="warn" glyph="!">Under 18</Badge>}</div>
                <dl className="kv">{CARD_FIELDS.map(([f, l]) => <div key={f} style={{ display: "contents" }}><dt>{l}</dt><dd>{p.attributes[f] ?? "Not available"}</dd></div>)}
                  <dt>SES</dt><dd className="muted">Not modelled</dd>
                  <dt>Model sees</dt><dd>{Object.keys(p.model_visible).length} fields</dd></dl>
                <div className="row">
                  <Link className="button small" href={withPop(`/personas/${p.synthetic_id}`, pop)}>View details</Link>
                  <Link className="button small" href={withPop("/experiments/new", pop)}>Run in experiment</Link>
                </div>
              </article>
            ))}
          </div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="button small" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
            <button type="button" className="button small" disabled={(page + 1) * 24 >= data.data.total} onClick={() => setPage((p) => p + 1)}>Next</button>
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function PersonasPage() {
  return (
    <>
      <PageHeader title="Persona Explorer">Personas built from the members of a cohort sample. Each card is a fictional synthetic resident generated from aggregate statistics.</PageHeader>
      <SyntheticNotice kind="population" />
      <PopulationGate what="personas">{() => <Personas />}</PopulationGate>
    </>
  );
}
