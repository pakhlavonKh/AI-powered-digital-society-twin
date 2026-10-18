"use client";

import { useCapabilities } from "@/components/national/common";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { Badge } from "@/components/StatusBadge";

export default function SettingsPage() {
  const caps = useCapabilities();
  return (
    <>
      <PageHeader title="Settings">Read-only view of this installation: execution backends, limits and the rules the generator follows. Configuration is set by environment variables on the API server (docs/research-workbench.md).</PageHeader>
      {caps.error ? <ErrorState error={caps.error} onRetry={caps.reload} /> : null}
      {caps.loading && !caps.data ? <Loading what="settings" /> : null}
      {caps.data ? (
        <>
          <section className="card" aria-labelledby="b-h"><h2 id="b-h">Execution</h2>
            <div className="table-wrap"><table><caption>Backends</caption><thead><tr><th>Backend</th><th>Available</th><th>Reasons</th></tr></thead>
              <tbody>{Object.entries(caps.data.backends).map(([k, b]) => <tr key={k}><th>{k.replace("_", " ")}</th>
                <td>{b.available ? <Badge tone="good" glyph="✓">Yes</Badge> : <Badge tone="neutral">No</Badge>}</td><td className="small">{[...b.reasons, b.note].filter(Boolean).join(" ")}</td></tr>)}</tbody></table></div>
            <dl className="kv" style={{ marginTop: 12 }}>
              <dt>Provider keys present (booleans only)</dt><dd>{Object.entries(caps.data.provider_key_present).map(([k, v]) => `${k}: ${v ? "yes" : "no"}`).join(" · ")}</dd>
              <dt>Maximum active personas per run</dt><dd>{caps.data.max_agents_per_run}</dd>
              <dt>Price table</dt><dd>{caps.data.price_table_configured ? "Configured" : "Not configured — provider cost is reported as unknown"}</dd>
              <dt>Generator</dt><dd>{caps.data.generator_version}</dd>
            </dl>
          </section>
          <section className="card" aria-labelledby="ev-h"><h2 id="ev-h">Evidence levels</h2>
            <dl className="kv">{Object.entries(caps.data.evidence_levels).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt><code>{k}</code></dt><dd className="small">{v}</dd></div>)}</dl></section>
          <section className="card" aria-labelledby="dep-h"><h2 id="dep-h">Dependency model</h2>
            <div className="table-wrap"><table><caption>Edges</caption><thead><tr><th>From</th><th>To</th><th>Basis</th></tr></thead>
              <tbody>{caps.data.dependency_model.edges.map((e, i) => <tr key={i}><td>{e.from}</td><td>{e.to}</td><td className="small">{e.basis}</td></tr>)}</tbody></table></div>
            <dl className="kv" style={{ marginTop: 12 }}>{Object.entries(caps.data.dependency_model.methods).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt><code>{k}</code></dt><dd className="small">{v}</dd></div>)}</dl>
            <h3 style={{ marginTop: 12 }}>Not modelled</h3>
            <ul className="small">{Object.entries(caps.data.dependency_model.not_modelled).map(([k, v]) => <li key={k}><code>{k}</code>: {v}</li>)}</ul></section>
          <section className="card" aria-labelledby="ru-h"><h2 id="ru-h">Constraint rules</h2>
            <ul className="small">{caps.data.constraint_rules.map((r) => <li key={r.rule_id}><code>{r.rule_id}</code> ({r.kind}): {r.description} <span className="muted">{r.justification}</span></li>)}</ul></section>
          <section className="card" aria-labelledby="vo-h"><h2 id="vo-h">Vocabularies</h2>
            {Object.values(caps.data.vocabularies).map((v) => (
              <details key={v.attribute}><summary>{v.attribute} ({v.categories.length})</summary><div className="details-body">
                <p className="small muted">{v.note}</p>
                <ul className="small">{v.categories.map((c) => <li key={c.code}><code>{c.code}</code> — {c.label_en}{c.label_tr ? ` (${c.label_tr})` : ""}</li>)}</ul></div></details>))}
          </section>
        </>
      ) : null}
    </>
  );
}
