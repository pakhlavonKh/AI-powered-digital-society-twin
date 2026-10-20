"use client";

import Link from "next/link";
import { useState } from "react";
import type { ApiError } from "@/lib/api/client";
import { toApiError } from "@/lib/api/client";
import { v2, type Capabilities, type ControlsStatus, type FieldEvidence } from "@/lib/api/v2";
import { fmtInt } from "@/lib/format";
import { usePopulation, withPop } from "@/lib/population";
import { useApi } from "@/lib/useApi";
import { ErrorState, Loading, UnavailableState } from "../States";
import { Badge } from "../StatusBadge";

export function useCapabilities() {
  return useApi("v2:capabilities", (signal) => v2<Capabilities>("/capabilities", { signal }));
}

/** Label for a category code using the API's vocabularies (source labels stay visible in tooltips). */
export function useLabels() {
  const caps = useCapabilities();
  return (field: string, code: string | null | undefined): string => {
    if (code === null || code === undefined || code === "unavailable") return "Not available";
    if (code === "not_applicable") return "Not applicable";
    if (field === "age_group") return code === "90+" ? "90+" : code.replace("-", "–");
    const cat = caps.data?.vocabularies[field]?.categories.find((c) => c.code === code);
    return cat?.label_en ?? code;
  };
}

const EVIDENCE_TONE: Record<string, "good" | "info" | "warn" | "neutral" | "crit"> = {
  DIRECT_SOURCE: "good", CONDITIONAL_SOURCE: "good", MARGINAL_INFERENCE: "warn", RULE_CONSTRAINED: "info",
  DERIVED: "info", ASSUMED: "warn", CONTEXTUAL: "neutral", UNAVAILABLE: "neutral",
};

export function EvidenceBadge({ evidence }: { evidence: FieldEvidence | undefined }) {
  if (!evidence?.evidence) return <span className="muted">–</span>;
  const tip = [evidence.method_text ?? evidence.method, ...(evidence.limitations ?? []), evidence.reason].filter(Boolean).join(" ");
  return <Badge tone={EVIDENCE_TONE[evidence.evidence] ?? "neutral"} title={tip}>{evidence.evidence.replace("_", " ").toLowerCase()}</Badge>;
}

export function BuildControlsButton({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <div className="stack">
      <div><button type="button" className="button primary" disabled={busy} onClick={async () => {
        setBusy(true); setError(null);
        try { await v2("/controls/build", { method: "POST", body: {} }); onDone(); } catch (e) { setError(toApiError(e)); } finally { setBusy(false); }
      }}>{busy ? "Building control tables…" : "Build control tables"}</button></div>
      {error ? <ErrorState error={error} /> : null}
    </div>
  );
}

export function GenerateForm({ onDone, compact = false }: { onDone: (populationId: string) => void; compact?: boolean }) {
  const geo = useApi("v2:geography", (signal) => v2<{ provinces: { province_code: string; province_name: string; has_population_controls: boolean }[] }>(
    "/geography/provinces", { signal }));
  const [size, setSize] = useState(10000);
  const [seed, setSeed] = useState(42);
  const [province, setProvince] = useState("");
  const [floor, setFloor] = useState(0);
  const [year, setYear] = useState(2025);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const covered = geo.data?.provinces.filter((p) => p.has_population_controls) ?? [];
  return (
    <form className="stack" onSubmit={async (e) => {
      e.preventDefault(); setBusy(true); setError(null);
      try {
        const out = await v2<{ population: { population_id: string } }>("/populations", { body: {
          synthetic_size: size, seed, reference_year: year, province_codes: province ? [province] : null, min_records_per_province: floor } });
        onDone(out.population.population_id);
      } catch (err) { setError(toApiError(err)); } finally { setBusy(false); }
    }}>
      <div className="form-grid">
        <div className="field"><label htmlFor="gen-size">Synthetic records</label>
          <input id="gen-size" type="number" min={1} max={1000000} value={size} onChange={(e) => setSize(Number(e.target.value))} />
          <span className="field-hint">10,000 and 100,000 are the benchmark sizes; up to 1,000,000.</span></div>
        <div className="field"><label htmlFor="gen-seed">Seed</label>
          <input id="gen-seed" type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></div>
        <div className="field"><label htmlFor="gen-scope">Scope</label>
          <select id="gen-scope" value={province} onChange={(e) => setProvince(e.target.value)}>
            <option value="">Türkiye (every province with source data: {covered.length})</option>
            {covered.map((p) => <option key={p.province_code} value={p.province_code}>{p.province_name} only</option>)}
          </select></div>
        {!compact ? <>
          <div className="field"><label htmlFor="gen-year">Reference year</label>
            <input id="gen-year" type="number" min={1990} max={2100} value={year} onChange={(e) => setYear(Number(e.target.value))} />
            <span className="field-hint">Sources may have their own (earlier) years; each is recorded.</span></div>
          <div className="field"><label htmlFor="gen-floor">Minimum records per province</label>
            <input id="gen-floor" type="number" min={0} value={floor} onChange={(e) => setFloor(Number(e.target.value))} />
            <span className="field-hint">Oversamples small provinces; weights correct for it.</span></div>
        </> : null}
      </div>
      <div><button type="submit" className="button primary" disabled={busy || covered.length === 0}>{busy ? "Generating and validating…" : "Generate population"}</button></div>
      {error ? <ErrorState error={error} /> : null}
    </form>
  );
}

/** Renders children only when controls are built and a population is selected; otherwise the right empty state. */
export function PopulationGate({ children, what = "this page" }: { children: (populationId: string) => React.ReactNode; what?: string }) {
  const { population, populationId, loading, error, reload, missingId, select } = usePopulation();
  const controls = useApi("v2:controls", (signal) => v2<ControlsStatus>("/controls", { signal }));
  if (loading && !population) return <Loading what="populations" />;
  if (error) return <ErrorState error={error} onRetry={reload} what="populations" />;
  if (missingId) return <UnavailableState title={`Population ${missingId} does not exist.`}>Choose another population above; nothing else was substituted.</UnavailableState>;
  if (populationId) return <>{children(populationId)}</>;
  if (controls.loading && !controls.data) return <Loading what="control tables" />;
  if (controls.data && controls.data.status !== "built") {
    return (
      <section className="card stack" aria-labelledby="gate-h">
        <h2 id="gate-h">Control tables have not been built</h2>
        <p className="small muted">{controls.data.detail} The generator only reads standard control tables normalised from the official sources found
          in this checkout (see <Link href="/data-sources">Data Sources</Link>).</p>
        <BuildControlsButton onDone={() => { controls.reload(); reload(); }} />
      </section>
    );
  }
  return (
    <section className="card stack" aria-labelledby="gate-h">
      <h2 id="gate-h">Population has not been generated</h2>
      <p className="small muted">Generate a synthetic population to use {what}. Records are fictional residents calibrated to official aggregate statistics.</p>
      <GenerateForm onDone={(id) => { reload(); select(id); }} />
    </section>
  );
}

export function NumberCell({ value }: { value: number | null | undefined }) {
  return <td className="num">{fmtInt(value)}</td>;
}

export function popLink(path: string, pop: string | null, extra?: Record<string, string | undefined>) {
  return withPop(path, pop, extra);
}
