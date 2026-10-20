"use client";

import Link from "next/link";
import type { Capabilities, Overview, ValidationReport } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { withPop } from "@/lib/population";
import { Badge, RunStateBadge } from "../StatusBadge";
import type { Tone } from "../status";

type Stage = { name: string; status: React.ReactNode; detail: React.ReactNode; href: string };

function state(tone: Tone, glyph: string, label: string) {
  return <Badge tone={tone} glyph={glyph}>{label}</Badge>;
}

/**
 * The national pipeline from source tables to results. Each status is read from API state (control store, populations,
 * cohorts, experiments, runs, backends, validation report); a stage is never shown as working because its page exists.
 */
export function PipelineStatus({ overview: o, caps, validation, recordedCompleted, pop }: {
  overview: Overview; caps: Capabilities | undefined; validation: ValidationReport | undefined; recordedCompleted: number | null; pop: string | null;
}) {
  const hasPop = o.populations.length > 0;
  const newest = o.populations.find((p) => p.population_id === o.default_population_id) ?? o.populations[0];
  const backends = caps ? (["stub", "matraix_fake", "matraix_live"] as const).filter((k) => caps.backends[k].available) : [];
  const backendNames = { stub: "stub (offline)", matraix_fake: "MatrAIx fake transport", matraix_live: "MatrAIx live provider" };
  const latest = o.latest_run;
  const stages: Stage[] = [
    {
      name: "Data", href: "/data-sources",
      status: o.controls.status === "built" ? state("good", "✓", "Loaded") : o.controls.status === "not_built" ? state("warn", "!", "Not built") : state("crit", "×", o.controls.status),
      detail: o.controls.status === "built"
        ? `${o.provinces_with_population_controls} / ${o.province_count} provinces · ${o.controls.tables.length} control tables`
        : "Build the control tables from the official sources.",
    },
    {
      name: "Synthetic population", href: "/population",
      status: hasPop ? state("good", "✓", "Generated") : state("neutral", "·", "Not generated"),
      detail: newest ? `${o.populations.length} saved · newest ${fmtInt(newest.synthetic_size)} records` : "Needs control tables first.",
    },
    {
      name: "Cohorts", href: "/cohorts",
      status: o.saved_cohorts > 0 ? state("good", "✓", `${fmtInt(o.saved_cohorts)} saved`) : hasPop ? state("info", "○", "Ready") : state("neutral", "·", "Needs a population"),
      detail: o.saved_cohorts > 0 ? "Filter and seeded-sample definitions" : hasPop ? "No cohort saved yet" : "Generate a population first.",
    },
    {
      name: "Personas", href: "/personas",
      status: hasPop ? state("info", "○", "Built on demand") : state("neutral", "·", "Needs a population"),
      detail: hasPop ? `From any synthetic record · ${fmtInt(o.personas_used_in_completed_runs)} used in completed runs` : "Generate a population first.",
    },
    {
      name: "Experiments", href: "/experiments",
      status: o.experiments > 0 ? state("good", "✓", `${fmtInt(o.experiments)} saved`) : backends.length ? state("info", "○", "Ready") : state("neutral", "·", caps ? "No backend" : "Checking…"),
      detail: caps ? `Backends available: ${backends.map((k) => backendNames[k]).join(", ") || "none"}` : "Reading execution backends…",
    },
    {
      name: "Results", href: latest ? `/results/${latest.run_id}` : "/results",
      status: latest ? <span className="row" style={{ gap: 4 }}><RunStateBadge state={latest.state} />{latest.backend === "stub" ? <Badge tone="fake" glyph="◇">Stub</Badge> : null}</span>
        : state("neutral", "·", "None yet"),
      detail: latest ? `${fmtInt(latest.valid_responses)} valid of ${fmtInt(latest.final_responses)} responses · ${latest.backend_label ?? "backend unknown"}`
        : recordedCompleted ? `No national run yet · ${recordedCompleted} completed historical run${recordedCompleted === 1 ? "" : "s"} recorded` : "No national run yet",
    },
  ];
  const violations = validation?.constraint_violations;
  const tables = validation ? validation.provinces.reduce((n, p) => n + p.tables.length, 0) : 0;
  const notImposed = validation?.calibration?.reduce((n, c) => n + (c.margins_not_calibrated?.length ?? 0), 0) ?? 0;
  return (
    <section className="card stack" aria-labelledby="pipeline-h">
      <div className="card-head" style={{ marginBottom: 0 }}>
        <h2 id="pipeline-h">Pipeline status</h2>
        <span className="small muted">National architecture: {o.province_count} provinces · Source data loaded: {o.provinces_with_population_controls} / {o.province_count}</span>
      </div>
      <ol className="pipeline">
        {stages.map((s, i) => (
          <li key={s.name}>
            <span className="pipe-step" aria-hidden="true">{i + 1}</span>
            <Link className="pipe-name" href={withPop(s.href, pop)} aria-label={`${s.name} stage`}>{s.name}</Link>
            <span>{s.status}</span>
            <span className="small muted">{s.detail}</span>
          </li>
        ))}
      </ol>
      <div className="pipeline-foot row small">
        <span className="pipe-name">Research checks</span>
        {validation ? (
          <span className="row" style={{ gap: 6 }}>
            {violations === 0 ? state("good", "✓", "Validation report available") : state("warn", "!", `${fmtInt(violations)} constraint violations`)}
            <span className="muted">{tables} source-table fit checks · {fmtInt(violations)} constraint violations{notImposed ? ` · ${fmtInt(notImposed)} calibration margins not imposed (small provinces)` : ""} · not a behavioural validation</span>
          </span>
        ) : <span className="muted">{hasPop ? "Reading the validation report…" : "Validation runs once a population exists."}</span>}
        <Link href={withPop("/validation", pop)}>Validation</Link>
        <Link href={withPop("/data-sources", pop)}>Data sources</Link>
      </div>
    </section>
  );
}
