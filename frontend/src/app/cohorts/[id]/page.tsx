"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { CohortStatusBadge, FilterChips } from "@/components/CohortStatus";
import { CopyId } from "@/components/CopyId";
import { Notice, SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading } from "@/components/States";
import { KeyValues, StatTile } from "@/components/StatTile";
import { api, unwrap } from "@/lib/api/client";
import { fmtDecimal, fmtInt } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

export default function CohortDetailPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const linkBuild = params.get("build");
  const cohort = useApi(id ? `cohort:${id}` : null, (signal) =>
    unwrap(api.GET("/api/v1/cohorts/{cohort_id}", { params: { path: { cohort_id: id } }, signal })));
  const c = cohort.data;

  return (
    <>
      <PageHeader title={c?.name ? `Cohort: ${c.name}` : `Cohort ${id}`}>
        A saved manifest: the requested design and the exact realized resident IDs, tied to one build&apos;s source bytes.
      </PageHeader>
      <SyntheticNotice kind="population" />
      {cohort.loading && !c ? <Loading what="cohort" /> : null}
      {cohort.error ? <ErrorState error={cohort.error} onRetry={cohort.reload} what="cohort" /> : null}
      {c ? (
        <>
          {c.current.status !== "valid" ? (
            <Notice tone="warn" title="This cohort can no longer be used for new operations.">{c.current.detail}</Notice>
          ) : null}
          <section className="card stack" aria-labelledby="manifest-h">
            <div className="card-head"><h2 id="manifest-h">Manifest</h2><CohortStatusBadge status={c.current.status} /></div>
            <KeyValues items={[
              ["Cohort ID", <CopyId key="c" value={c.cohort_id} label="cohort ID" />],
              ["Build", <code key="b">{c.build_id}</code>],
              ["Build source SHA-256", <code key="s">{c.source_sha256}</code>],
              ["Requested filters", <FilterChips key="f" filters={c.requested.filters} />],
              ["Requested size and method", `${fmtInt(c.requested.size)} · simple random sample without replacement`],
              ["Seed", String(c.requested.seed)],
              ["Algorithm", c.sampling_algorithm_version],
              ["Frame ordering", c.frame_ordering],
              ["Created", c.created_at],
            ]} />
            <div className="tiles">
              <StatTile label="Eligible residents (M)" value={fmtInt(c.realized.eligible_count)} />
              <StatTile label="Selected (n)" value={fmtInt(c.realized.selected_count)} />
              <StatTile label="Inclusion probability" value={fmtDecimal(c.realized.inclusion_probability, 4)} />
              <StatTile label="Expansion weight" value={fmtDecimal(c.realized.synthetic_frame_expansion_weight, 2)} sub="Synthetic frame only" />
            </div>
            <p className="small muted">{c.realized.weight_scope} {c.scope_note}</p>
            <div className="row">
              <Link className="button" href={withBuild("/experiments/new", linkBuild, { cohort: c.cohort_id })}>Design an experiment draft with this cohort</Link>
              <span className="small muted">Cohort-based drafts can be saved; no verified runner executes arbitrary cohorts.</span>
            </div>
          </section>

          <div className="grid-2">
            <section className="card" aria-labelledby="ids-h">
              <h2 id="ids-h">Realized resident IDs</h2>
              <div className="table-wrap" style={{ maxHeight: 480, overflowY: "auto" }}>
                <table style={{ minWidth: 0 }}>
                  <caption>In selection order</caption>
                  <thead><tr><th scope="col" className="num">#</th><th scope="col">Resident</th></tr></thead>
                  <tbody>
                    {c.realized.record_ids.map((rid, i) => (
                      <tr key={rid}>
                        <td className="num">{i + 1}</td>
                        <td><Link href={withBuild("/personas", c.build_id, { record: rid })}>{rid}</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="card stack" aria-labelledby="counts-h">
              <h2 id="counts-h">Realized counts</h2>
              {Object.entries(c.realized.realized_counts).map(([field, counts]) => (
                <div className="table-wrap" key={field}>
                  <table style={{ minWidth: 0 }}>
                    <caption>{field}</caption>
                    <thead><tr><th scope="col">Category</th><th scope="col" className="num">Residents</th></tr></thead>
                    <tbody>
                      {Object.entries(counts).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{fmtInt(v)}</td></tr>)}
                    </tbody>
                  </table>
                </div>
              ))}
            </section>
          </div>
        </>
      ) : null}
    </>
  );
}
