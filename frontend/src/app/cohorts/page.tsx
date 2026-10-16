"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CohortStatusBadge, FilterChips } from "@/components/CohortStatus";
import { FilterControls } from "@/components/FilterControls";
import { SyntheticNotice } from "@/components/Notices";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState, Loading, UnavailableState } from "@/components/States";
import { StatTile } from "@/components/StatTile";
import { api, toApiError, unwrap, type ApiError } from "@/lib/api/client";
import { useBuild } from "@/lib/build";
import { filtersToBody, type Filters } from "@/lib/filters";
import { fmtDecimal, fmtInt } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { withBuild } from "@/lib/urls";

function randomSeed(): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0];
}

export default function CohortsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const linkBuild = params.get("build");
  const { build, missingBuildId } = useBuild();
  const buildId = build?.availability.status === "available" ? build.build_id : null;
  const [filters, setFilters] = useState<Filters>({});
  const [size, setSize] = useState("10");
  const [seed, setSeed] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | undefined>();

  useEffect(() => setSeed(String(randomSeed())), []);
  useEffect(() => setFilters({}), [buildId]);

  const cats = useApi(buildId ? `cats:${buildId}` : null, (signal) =>
    unwrap(api.GET("/api/v1/builds/{build_id}/summary", { params: { path: { build_id: buildId! } }, signal })));
  const body = filtersToBody(filters);
  const preview = useApi(buildId ? `preview:${buildId}:${JSON.stringify(body)}` : null, (signal) =>
    unwrap(api.POST("/api/v1/cohorts/preview", { body: { build_id: buildId!, filters: body }, signal })));
  const caps = useApi("capabilities", (signal) => unwrap(api.GET("/api/v1/capabilities", { signal })));
  const cohorts = useApi("cohorts", (signal) => unwrap(api.GET("/api/v1/cohorts", { signal })));

  const categories = {
    age_group: cats.data?.distributions.find((d) => d.field === "age_group")?.categories.map((c) => c.value) ?? [],
    gender: cats.data?.distributions.find((d) => d.field === "gender")?.categories.map((c) => c.value) ?? [],
    marital_status: cats.data?.distributions.find((d) => d.field === "marital_status")?.categories.map((c) => c.value) ?? [],
  };
  const eligible = preview.data?.eligible_count ?? 0;
  const n = Number(size);
  const seedNumber = Number(seed);
  const sizeProblem = !Number.isInteger(n) || n < 1 ? "Enter a whole number of at least 1."
    : preview.data && n > eligible ? `Only ${fmtInt(eligible)} residents match; sampling is without replacement.` : null;
  const seedProblem = seed === "" || !Number.isInteger(seedNumber) || seedNumber < 0 ? "Enter a whole-number seed of 0 or more." : null;
  const canSave = Boolean(preview.data && preview.data.can_persist && !sizeProblem && !seedProblem && !preview.loading && !saving);

  async function save() {
    if (!preview.data || !buildId) return;
    setSaving(true);
    setSaveError(undefined);
    try {
      const created = await unwrap(api.POST("/api/v1/cohorts", {
        body: { build_id: buildId, source_sha256: preview.data.source_sha256, filters: body, size: n, sampling: "simple_random",
                 seed: seedNumber, name: name.trim() || null },
      }));
      router.push(withBuild(`/cohorts/${created.cohort_id}`, linkBuild));
    } catch (err) {
      setSaveError(toApiError(err));
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader title="Cohorts">
        Draw a reproducible sample from the loaded synthetic build: filter, check the matching count, then save a seeded simple random
        sample. The saved manifest keeps the requested filters and the exact realized resident IDs.
      </PageHeader>
      <SyntheticNotice kind="population" />
      {missingBuildId ? <UnavailableState title={`Build ${missingBuildId} is not registered.`}>Choose a registered build above.</UnavailableState> : null}
      {build && !buildId ? <UnavailableState title="The selected build's source has changed; new cohorts cannot be drawn from it." /> : null}

      {buildId ? (
        <section className="card stack" aria-labelledby="new-h">
          <h2 id="new-h">New cohort</h2>
          <FilterControls filters={filters} onChange={setFilters} categories={categories} availableFields={build?.available_fields ?? []}
            disabled={!cats.data} idSearch />
          {preview.error ? <ErrorState error={preview.error} onRetry={preview.reload} what="preview" /> : null}
          {preview.data ? (
            <div className={preview.loading ? "is-stale" : ""} aria-live="polite" aria-busy={preview.loading}>
              <div className="tiles">
                <StatTile label="Eligible residents (M)" value={fmtInt(preview.data.eligible_count)} sub={`of ${fmtInt(preview.data.total_records)} in this build`} />
                <StatTile label="Inclusion probability (n/M)" value={preview.data.eligible_count && !sizeProblem ? fmtDecimal(n / preview.data.eligible_count, 4) : "–"}
                  sub="Each eligible resident, without replacement" />
                <StatTile label="Expansion weight (M/n)" value={preview.data.eligible_count && !sizeProblem ? fmtDecimal(preview.data.eligible_count / n, 2) : "–"}
                  sub="Relative to this synthetic frame only" />
              </div>
              {!preview.data.can_persist ? <EmptyState title="No residents match.">An empty preview can be inspected, but a saved cohort must be nonempty.</EmptyState> : null}
            </div>
          ) : preview.loading ? <Loading what="matching count" /> : null}

          <div className="grid-3">
            <div className="field">
              <label htmlFor="size">Sample size (n)</label>
              <input id="size" type="number" min={1} step={1} value={size} onChange={(e) => setSize(e.target.value)} aria-describedby="size-hint" aria-invalid={Boolean(sizeProblem)} />
              <span className="field-hint" id="size-hint">{sizeProblem ?? "Without replacement; cannot exceed the eligible count."}</span>
            </div>
            <div className="field">
              <label htmlFor="seed">Seed</label>
              <div className="row">
                <input id="seed" type="number" min={0} step={1} value={seed} onChange={(e) => setSeed(e.target.value)} aria-invalid={Boolean(seedProblem)} style={{ flex: "1 1 120px" }} />
                <button type="button" className="button small" onClick={() => setSeed(String(randomSeed()))}>New seed</button>
              </div>
              <span className="field-hint">{seedProblem ?? "Recorded in the manifest. Same build, filters, size and seed give the same IDs."}</span>
            </div>
            <div className="field">
              <label htmlFor="cohort-name">Name (optional)</label>
              <input id="cohort-name" type="text" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          </div>
          <fieldset>
            <legend>Sampling method</legend>
            <label className="check"><input type="radio" name="sampling" checked readOnly /> Simple random sample without replacement</label>
            <label className="check" style={{ opacity: 0.7 }}>
              <input type="radio" name="sampling" disabled aria-describedby="strat-reason" /> Stratified sample
            </label>
            <p className="field-hint" id="strat-reason">
              Stratified sampling is unavailable: {caps.data?.modes.stratified_sampling.reasons[0] ?? "no tested design is implemented."}
            </p>
          </fieldset>
          {saveError ? <ErrorState error={saveError} what="saving the cohort" /> : null}
          <div className="row">
            <button type="button" className="button primary" onClick={save} disabled={!canSave}>{saving ? "Saving…" : "Save cohort"}</button>
            <span className="small muted">Saving draws the sample on the server from the previewed bytes; a changed source is rejected.</span>
          </div>
        </section>
      ) : null}

      <section className="card stack" aria-labelledby="saved-h">
        <h2 id="saved-h">Saved cohorts</h2>
        {cohorts.loading && !cohorts.data ? <Loading what="cohorts" /> : null}
        {cohorts.error ? <ErrorState error={cohorts.error} onRetry={cohorts.reload} /> : null}
        {cohorts.data && cohorts.data.items.length === 0 ? <EmptyState title="No cohorts saved yet." /> : null}
        {cohorts.data && cohorts.data.items.length > 0 ? (
          <div className="table-wrap">
            <table>
              <caption>Saved cohort manifests (newest first)</caption>
              <thead><tr><th scope="col">Cohort</th><th scope="col">Filters</th><th scope="col" className="num">n / M</th><th scope="col" className="num">Seed</th><th scope="col">Build</th><th scope="col">Status</th><th scope="col">Created</th></tr></thead>
              <tbody>
                {cohorts.data.items.map((c) => (
                  <tr key={c.cohort_id}>
                    <th scope="row"><Link href={withBuild(`/cohorts/${c.cohort_id}`, linkBuild)}>{c.name || c.cohort_id}</Link>{c.name ? <div className="small muted"><code>{c.cohort_id}</code></div> : null}</th>
                    <td><FilterChips filters={c.requested.filters} /></td>
                    <td className="num">{fmtInt(c.realized.selected_count)} / {fmtInt(c.realized.eligible_count)}</td>
                    <td className="num">{c.requested.seed}</td>
                    <td><code>{c.build_id}</code></td>
                    <td><CohortStatusBadge status={c.current.status} /></td>
                    <td className="small">{c.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </>
  );
}
