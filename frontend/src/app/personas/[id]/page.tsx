"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { EvidenceBadge, PopulationGate } from "@/components/national/common";
import { Notice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";
import { v2, type PersonaAttribute, type RecordDetail } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { useLinkPop, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";

const GROUPS: [string, string[]][] = [
  ["Identity and province", ["province_name", "reference_year"]],
  ["Demographics", ["age_group", "age", "sex", "marital_status"]],
  ["Household", ["household_size_class", "household_type", "urbanicity"]],
  ["Socioeconomic", ["education_level", "labour_status"]],
];
const STATUS_TEXT: Record<PersonaAttribute["status"], string> = { visible: "Model-visible", hidden: "Hidden from model", unavailable: "Not available", not_applicable: "Not applicable" };

function Detail({ populationId, syntheticId }: { populationId: string; syntheticId: string }) {
  const pop = useLinkPop();
  const d = useApi(`v2:rec:${populationId}:${syntheticId}`, (signal) => v2<RecordDetail>(`/populations/${populationId}/records/${syntheticId}`, { signal }));
  if (d.error) return <ErrorState error={d.error} onRetry={d.reload} what="persona" />;
  if (!d.data) return <Loading what="persona" />;
  const { persona, record } = d.data;
  const byField = new Map(persona.attributes.map((a) => [a.field, a]));
  return (
    <div className="stack">
      <Notice tone="info" title="This is a fictional synthetic resident generated from aggregate statistics.">{persona.kind_label} No real person, record or address is represented.</Notice>
      <div className="row">
        {persona.eligibility.adult ? <Badge tone="good" glyph="✓">Adult: eligible for adult tasks</Badge> : <Badge tone="warn" glyph="!">Under 18: excluded from adult tasks</Badge>}
        <Badge tone="neutral" glyph="#">{persona.persona_id}</Badge>
        <span className="small muted">Weight {record.population_weight.toFixed(1)} residents represented</span>
      </div>
      <div className="grid-2">
        <section className="card" aria-labelledby="attrs-h">
          <h2 id="attrs-h">Available synthetic attributes</h2>
          {GROUPS.map(([title, fields]) => (
            <div key={title} className="table-wrap" style={{ marginBottom: 12 }}>
              <table className="attr-table"><caption>{title}</caption><thead><tr><th>Attribute</th><th>Value</th><th>Model</th><th>Evidence</th><th>Source year</th></tr></thead>
                <tbody>{fields.map((f) => byField.get(f)).filter(Boolean).map((a) => (
                  <tr key={a!.field}><th>{a!.label}</th><td>{a!.display}</td>
                    <td className={`status-${a!.status}`} title={a!.reason ?? undefined}>{STATUS_TEXT[a!.status]}</td>
                    <td><EvidenceBadge evidence={a!.evidence} /></td><td>{a!.evidence.source_year ?? "–"}</td></tr>))}</tbody></table>
            </div>
          ))}
          <p className="small muted">Socioeconomic status, income, employment status and district are not modelled: no person-level source is loaded.</p>
        </section>
        <section className="stack">
          <section className="card" aria-labelledby="mv-h">
            <h2 id="mv-h">Model-visible attributes</h2>
            <dl className="kv">{Object.entries(persona.model_visible).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{byField.get(k)?.label ?? k}</dt><dd>{v}</dd></div>)}</dl>
            <details style={{ marginTop: 12 }}><summary>Persona card exactly as a model would receive it</summary>
              <div className="details-body"><pre className="prompt">{persona.persona_card}</pre><span className="small muted">sha256 {persona.persona_card_sha256.slice(0, 16)}…</span></div></details>
          </section>
          <section className="card" aria-labelledby="hid-h">
            <h2 id="hid-h">Hidden from the model</h2>
            <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{persona.hidden.map((h) => <li key={h.field}><code>{h.field}</code>: {h.reason}</li>)}</ul>
          </section>
          <section className="card" aria-labelledby="lim-h">
            <h2 id="lim-h">Evidence limitations</h2>
            {persona.limitations.length ? <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{persona.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
              : <p className="small muted">None recorded for the model-visible fields.</p>}
          </section>
          <section className="card" aria-labelledby="prov-h">
            <h2 id="prov-h">Source provenance</h2>
            <dl className="kv">
              <dt>Synthetic ID</dt><dd><code>{persona.synthetic_id}</code></dd>
              <dt>Population</dt><dd><code>{persona.population_id}</code> · seed {persona.provenance.generation_seed} · {persona.provenance.generator_version}</dd>
              <dt>Reference year</dt><dd>{persona.provenance.reference_year}</dd>
              <dt>Source years</dt><dd>{Object.entries(persona.provenance.source_years).map(([f, y]) => `${f}: ${y}`).join(" · ") || "–"}</dd>
              <dt>Sources</dt><dd>{persona.provenance.source_ids.map((s) => <code key={s} style={{ marginRight: 6 }}>{s}</code>)} <Link href={withPop("/data-sources", pop)}>details</Link></dd>
              <dt>Template</dt><dd>{persona.template_version}</dd>
              <dt>Represents</dt><dd>{fmtInt(persona.population_weight)} residents (sampling weight)</dd>
            </dl>
          </section>
        </section>
      </div>
    </div>
  );
}

export default function PersonaDetailPage() {
  const { id } = useParams<{ id: string }>();
  const syntheticId = decodeURIComponent(id);
  return (
    <>
      <PageHeader title={`Persona ${syntheticId}`}>Every attribute with its evidence level, source year and whether a model would see it.</PageHeader>
      <PopulationGate what="persona details">{(pid) => <Detail populationId={pid} syntheticId={syntheticId} />}</PopulationGate>
    </>
  );
}
