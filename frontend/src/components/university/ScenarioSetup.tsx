"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toApiError } from "@/lib/api/client";
import { useUniversitySource } from "@/lib/university/context";
import { cohortId as fixtureCohortId } from "@/lib/university/fixtures/candidates";
import { defaultScenario, hasBlocking, presetSupport, PRESETS, serializeScenario, validateScenario } from "@/lib/university/scenario";
import type { CohortManifest, Finding, PresetId, RegistryCatalogue, RegistrySnapshot, ScenarioConfig, UniversityCapabilities } from "@/lib/university/types";
import { compareText } from "@/lib/university/util";
import { fmtInt } from "@/lib/format";
import { Badge } from "../StatusBadge";
import { ValidationList } from "./common";
import { SimulationStatus, type ExecutionState } from "./SimulationStatus";

function fieldErrors(findings: Finding[], field: string): Finding[] {
  return findings.filter((f) => f.blocking && f.field === field);
}

function FieldError({ id, findings }: { id: string; findings: Finding[] }) {
  if (!findings.length) return null;
  return <span className="field-error" id={id}>{findings.map((f) => f.message).join(" ")}</span>;
}

/** Number input that keeps the raw text, so an invalid entry is reported instead of silently becoming 0. */
function NumberField({ id, label, value, onChange, hint, errors, min, max, step }: {
  id: string; label: string; value: number; onChange: (v: number) => void; hint?: string; errors: Finding[]; min?: number; max?: number; step?: number;
}) {
  const [text, setText] = useState(String(value));
  // Follow external changes (presets) without overwriting text the user is still typing.
  useEffect(() => { setText((t) => (Number.isNaN(value) || (t.trim() !== "" && Number(t) === value) ? t : String(value))); }, [value]);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="number" value={text} min={min} max={max} step={step ?? 1} aria-invalid={errors.length ? true : undefined}
        aria-describedby={[hint ? `${id}-hint` : null, errors.length ? `${id}-err` : null].filter(Boolean).join(" ") || undefined}
        onChange={(e) => { setText(e.target.value); onChange(e.target.value.trim() === "" ? Number.NaN : Number(e.target.value)); }} />
      {hint ? <span className="field-hint" id={`${id}-hint`}>{hint}</span> : null}
      <FieldError id={`${id}-err`} findings={errors} />
    </div>
  );
}

export function ScenarioSetup({ catalogue, snapshots, caps, cohortBase, initialPreset }: {
  catalogue: RegistryCatalogue; snapshots: RegistrySnapshot[]; caps: UniversityCapabilities; cohortBase: CohortManifest; initialPreset?: PresetId | null;
}) {
  const source = useUniversitySource();
  const baseCohort = { cohort_id: cohortBase.cohort_id, generator_version: cohortBase.generator_version, seed: cohortBase.configuration.seed, size: cohortBase.configuration.size };
  const [config, setConfig] = useState<ScenarioConfig>(() => {
    const c = defaultScenario(catalogue, baseCohort);
    const preset = PRESETS.find((p) => p.id === initialPreset && presetSupport(p.id, caps).supported);
    return preset ? { ...c, ...preset.patch, preset: preset.id } : c;
  });
  const [exec, setExec] = useState<ExecutionState>({ phase: "idle" });
  const inFlight = useRef(false);
  const [override, setOverride] = useState<{ code: string; value: string }>({ code: "", value: "" });

  const set = (patch: Partial<ScenarioConfig>) => {
    setConfig((c) => {
      const next = { ...c, ...patch };
      if (patch.cohort && caps.origin === "fixture") next.cohort = { ...next.cohort, cohort_id: fixtureCohortId(next.cohort.seed, next.cohort.size) };
      return next;
    });
  };
  const findings = useMemo(() => validateScenario(config, catalogue, caps, cohortBase.registry_snapshot),
    [config, catalogue, caps, cohortBase.registry_snapshot]);
  const blocked = hasBlocking(findings);
  const fixture = caps.execution.mode === "fixture_preview";

  const universities = [...catalogue.universities].sort((a, b) => compareText(a.name_original, b.name_original));
  const includedKeys = config.included_university_keys ?? universities.map((u) => u.university_key);
  const includedIds = new Set(universities.filter((u) => includedKeys.includes(u.university_key)).map((u) => u.university_id));
  const yearRows = new Map(catalogue.admissions.filter((a) => a.admission_year === config.admission_year).map((a) => [a.program_id, a]));
  const overridable = catalogue.programs.filter((p) => includedIds.has(p.university_id) && yearRows.has(p.program_id) && config.program_quota_overrides[p.program_code] === undefined);
  const uniName = new Map(catalogue.universities.map((u) => [u.university_id, u.name_original]));
  const programLabel = (code: string) => {
    const p = catalogue.programs.find((x) => x.program_code === code);
    return p ? `${p.name_original} · ${p.scholarship_original ?? "?"} · ${uniName.get(p.university_id) ?? "?"} (${code})` : code;
  };
  const toggleUni = (key: string) => {
    const next = includedKeys.includes(key) ? includedKeys.filter((k) => k !== key) : [...includedKeys, key];
    set({ included_university_keys: next.length === universities.length ? null : next });
  };

  const submit = async () => {
    if (inFlight.current || blocked) return; // prevents duplicate submissions from double clicks
    inFlight.current = true;
    setExec({ phase: "submitting" });
    try {
      const out = await source.submitScenario(config);
      setExec({ phase: "submitted", run: out.run, duplicateOf: out.duplicate_of });
    } catch (e) {
      setExec({ phase: "error", error: toApiError(e) });
    } finally {
      inFlight.current = false;
    }
  };
  const refresh = async () => {
    if (exec.phase !== "submitted") return;
    try {
      const run = await source.getRun(exec.run.run_id);
      setExec({ phase: "submitted", run, duplicateOf: exec.duplicateOf });
    } catch (e) {
      setExec({ phase: "error", error: toApiError(e) });
    }
  };
  const runStatus = exec.phase === "submitted" ? exec.run.status : null;
  useEffect(() => {
    if (runStatus !== "pending" && runStatus !== "running") return;
    const t = setTimeout(refresh, 2000);
    return () => clearTimeout(t);
  }, [exec]); // re-armed after each status refresh while the run is pending or running

  return (
    <div className="stack">
      <section className="card stack" aria-labelledby="presets-h">
        <div className="card-head"><h2 id="presets-h">Scenario presets</h2><span className="small muted">Choosing a preset fills the form; you can still edit it.</span></div>
        <div className="preset-grid">
          {PRESETS.map((p) => {
            const support = presetSupport(p.id, caps);
            return (
              <button key={p.id} type="button" className="preset-card" aria-pressed={config.preset === p.id} disabled={!support.supported}
                aria-describedby={`preset-${p.id}-note`} onClick={() => set({ ...p.patch, preset: p.id })}>
                <span className="preset-letter">Scenario {p.letter}</span>
                <strong>{p.title}</strong>
                <span className="small">{p.description}</span>
                <span id={`preset-${p.id}-note`}>
                  {support.supported
                    ? <Badge tone={fixture ? "fake" : "good"} glyph={fixture ? "◇" : "✓"}>{fixture ? "Fixture preview only" : "Executable"}</Badge>
                    : <><Badge tone="neutral" glyph="–">Not supported</Badge> <span className="small">{support.reason}</span></>}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <form className="card stack" aria-labelledby="config-h" onSubmit={(e) => { e.preventDefault(); void submit(); }} noValidate>
        <div className="card-head"><h2 id="config-h">Configuration</h2><span className="small muted">Preset: {PRESETS.find((p) => p.id === config.preset)?.title ?? "Custom"}</span></div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="sc-name">Scenario name</label>
            <input id="sc-name" type="text" value={config.name} maxLength={200} onChange={(e) => set({ name: e.target.value })}
              aria-invalid={fieldErrors(findings, "name").length ? true : undefined} aria-describedby={fieldErrors(findings, "name").length ? "sc-name-err" : undefined} />
            <FieldError id="sc-name-err" findings={fieldErrors(findings, "name")} />
          </div>
          <div className="field">
            <label htmlFor="sc-dataset">University/program dataset</label>
            <select id="sc-dataset" value={config.registry_snapshot_id} onChange={(e) => set({ registry_snapshot_id: e.target.value })}
              aria-invalid={fieldErrors(findings, "registry_snapshot_id").length ? true : undefined}>
              {snapshots.map((s) => <option key={s.snapshot_id} value={s.snapshot_id}>{s.snapshot_id} ({s.origin})</option>)}
            </select>
            <FieldError id="sc-dataset-err" findings={fieldErrors(findings, "registry_snapshot_id")} />
          </div>
          <div className="field">
            <label htmlFor="sc-year">Admission year</label>
            <select id="sc-year" value={config.admission_year} onChange={(e) => set({ admission_year: Number(e.target.value), program_quota_overrides: {} })}
              aria-invalid={fieldErrors(findings, "admission_year").length ? true : undefined}>
              {[...catalogue.snapshot.admission_years].reverse().map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="field-hint">Capacities start from this year&apos;s reported quotas. Changing the year clears overrides.</span>
          </div>
          <div className="field">
            <label htmlFor="sc-cohort">Synthetic candidate cohort</label>
            <input id="sc-cohort" type="text" value={config.cohort.cohort_id} readOnly aria-describedby="sc-cohort-hint" />
            <span className="field-hint" id="sc-cohort-hint">{config.cohort.generator_version}; set by the cohort seed and candidate count.</span>
          </div>
          <NumberField id="sc-size" label="Candidate count" value={config.cohort.size} min={1} max={caps.limits.max_cohort_size}
            onChange={(v) => set({ cohort: { ...config.cohort, size: v } })} errors={fieldErrors(findings, "cohort.size")}
            hint={`1 to ${fmtInt(caps.limits.max_cohort_size)}. The same seed with more candidates extends the cohort.`} />
          <NumberField id="sc-cohort-seed" label="Cohort seed" value={config.cohort.seed} min={0} onChange={(v) => set({ cohort: { ...config.cohort, seed: v } })}
            errors={fieldErrors(findings, "cohort.seed")} hint="Runs with different cohort seeds cannot be compared candidate by candidate." />
          <NumberField id="sc-seed" label="Simulation random seed" value={config.seed} min={0} onChange={(v) => set({ seed: v })} errors={fieldErrors(findings, "seed")}
            hint="Breaks ties between equal achievement values." />
          <NumberField id="sc-quota" label="Program quota adjustment (%)" value={config.quota_adjustment_pct} min={caps.limits.quota_adjustment_pct[0]} max={caps.limits.quota_adjustment_pct[1]}
            onChange={(v) => set({ quota_adjustment_pct: v })} errors={fieldErrors(findings, "quota_adjustment_pct")}
            hint={`Applied to every included program's reported quota, rounded to whole seats (${caps.limits.quota_adjustment_pct[0]}% to +${caps.limits.quota_adjustment_pct[1]}%).`} />
        </div>

        <fieldset aria-describedby="sc-inst-hint">
          <legend>Selected institutions ({includedKeys.length} of {universities.length})</legend>
          <div className="institution-checks">
            {universities.map((u) => (
              <label className="check" key={u.university_key}>
                <input type="checkbox" checked={includedKeys.includes(u.university_key)} onChange={() => toggleUni(u.university_key)} />
                {u.name_original}
              </label>
            ))}
          </div>
          <span className="field-hint" id="sc-inst-hint">Preferences for programs at excluded institutions are skipped by the simulation.</span>
          <FieldError id="sc-inst-err" findings={fieldErrors(findings, "included_university_keys")} />
        </fieldset>

        <fieldset>
          <legend>Program capacity overrides ({Object.keys(config.program_quota_overrides).length})</legend>
          {Object.entries(config.program_quota_overrides).length ? (
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: "0 0 8px" }}>
              {Object.entries(config.program_quota_overrides).sort(([a], [b]) => (a < b ? -1 : 1)).map(([code, value]) => {
                const errs = fieldErrors(findings, `override.${code}`);
                return (
                  <li key={code} className="override-row">
                    <span className="small">{programLabel(code)} · reported {fmtInt(yearRows.get(catalogue.programs.find((p) => p.program_code === code)?.program_id ?? -1)?.quota ?? null)}{errs.length ? <><br /><FieldError id={`ov-${code}-err`} findings={errs} /></> : null}</span>
                    <input type="number" aria-label={`Capacity for ${programLabel(code)}`} value={Number.isNaN(value) ? "" : value} min={0}
                      aria-invalid={errs.length ? true : undefined}
                      onChange={(e) => set({ program_quota_overrides: { ...config.program_quota_overrides, [code]: e.target.value === "" ? Number.NaN : Number(e.target.value) } })} />
                    <button type="button" className="button small" onClick={() => { const next = { ...config.program_quota_overrides }; delete next[code]; set({ program_quota_overrides: next }); }}>Remove</button>
                  </li>
                );
              })}
            </ul>
          ) : <p className="small muted" style={{ margin: "0 0 8px" }}>No overrides: every included program uses its adjusted reported quota.</p>}
          <div className="override-row">
            <select aria-label="Program to override" value={override.code} onChange={(e) => setOverride({ ...override, code: e.target.value })}>
              <option value="">Choose a program…</option>
              {overridable.map((p) => <option key={p.program_code} value={p.program_code}>{programLabel(p.program_code)}</option>)}
            </select>
            <input type="number" aria-label="New capacity" min={0} placeholder="Seats" value={override.value} onChange={(e) => setOverride({ ...override, value: e.target.value })} />
            <button type="button" className="button small" disabled={!override.code || override.value === ""}
              onClick={() => { set({ program_quota_overrides: { ...config.program_quota_overrides, [override.code]: Number(override.value) } }); setOverride({ code: "", value: "" }); }}>Add override</button>
          </div>
        </fieldset>

        <div className="notice small" role="note">
          <strong>Not configurable here.</strong> Scholarship availability and candidate preference distributions have no simulation mechanism yet, so they are not offered as controls.
          Eligibility, ties and allocation rules belong to the placement engine.
        </div>

        <ValidationList findings={findings} title="Scenario validation" empty="The scenario is valid." />

        <details>
          <summary>Serialized scenario (request body)</summary>
          <div className="details-body"><pre className="prompt" aria-label="Serialized scenario JSON">{JSON.stringify(JSON.parse(serializeScenario(config)), null, 2)}</pre></div>
        </details>

        <div className="wizard-actions">
          <span className="small muted">{blocked ? "Fix the blocking errors above to run." : fixture ? "Demo mode: fixture preview only. No backend simulation will run." : "Runs through the placement API."}</span>
          <button type="submit" className="button primary" disabled={blocked || exec.phase === "submitting"}>
            {exec.phase === "submitting" ? "Running…" : fixture ? "Run fixture preview" : "Run simulation"}
          </button>
        </div>
      </form>

      <section className="card stack" aria-labelledby="status-h">
        <h2 id="status-h">Execution status</h2>
        <SimulationStatus state={exec} snapshot={config.registry_snapshot_id} onRetry={() => void submit()} onRefresh={() => void refresh()} />
        {exec.phase === "submitted" && serializeScenario(exec.run.config) !== serializeScenario(config)
          ? <p className="notice warn small" style={{ margin: 0 }}>The form has changed since this run. Run again to see results for the current configuration.</p> : null}
      </section>
    </div>
  );
}
