"use client";

import { useEffect, useRef, useState } from "react";
import { defaultProgramState, type ProgramUrlState } from "@/lib/university/programs";
import { MISSING_VALUE, type FacetValue, type ProgramFacets } from "@/lib/university/types";
import { fmtInt } from "@/lib/format";

type ListKey = "score_types" | "scholarships" | "university_keys" | "university_types" | "teaching_languages";

function CheckGroup({ legend, field, options, selected, onToggle, hint }: {
  legend: string; field: string; options: FacetValue[]; selected: string[]; onToggle: (v: string) => void; hint?: string;
}) {
  return (
    <fieldset>
      <legend>{legend}{selected.length ? ` (${selected.length})` : ""}</legend>
      <div className="checks">
        {options.map((o) => (
          <label className="check" key={o.value}>
            <input type="checkbox" name={field} value={o.value} checked={selected.includes(o.value)} onChange={() => onToggle(o.value)} />
            <span className={o.value === MISSING_VALUE ? "missing" : undefined}>{o.label}</span> <span className="muted small">({fmtInt(o.count)})</span>
          </label>
        ))}
      </div>
      {hint ? <p className="field-hint" style={{ margin: "4px 0 0" }}>{hint}</p> : null}
    </fieldset>
  );
}

/**
 * Filters combine with AND across fields and OR within a field. Options come from the snapshot itself; fields the
 * snapshot has no data for are not offered (and say so).
 */
export function ProgramFilters({ state, facets, onChange, latestYear }: {
  state: ProgramUrlState; facets: ProgramFacets | undefined; onChange: (s: ProgramUrlState) => void; latestYear: number | null;
}) {
  const [text, setText] = useState(state.search);
  const applied = useRef(state.search);
  useEffect(() => { setText(state.search); applied.current = state.search; }, [state.search]);
  useEffect(() => {
    if (text === applied.current) return;
    const t = setTimeout(() => { applied.current = text; onChange({ ...state, search: text, page: 0 }); }, 300);
    return () => clearTimeout(t);
  }, [text, state, onChange]);

  const set = (patch: Partial<ProgramUrlState>) => onChange({ ...state, ...patch, page: 0 });
  const toggle = (key: ListKey, value: string) => {
    const current = new Set(state[key]);
    if (current.has(value)) current.delete(value); else current.add(value);
    set({ [key]: [...current] } as Partial<ProgramUrlState>);
  };
  const hasTypes = (facets?.university_types ?? []).some((f) => f.value !== MISSING_VALUE);
  const hasLanguages = (facets?.teaching_languages ?? []).some((f) => f.value !== MISSING_VALUE);
  return (
    <section className="card filters2" aria-label="Program filters">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Filters</h2>
        <button type="button" className="button small" onClick={() => { setText(""); applied.current = ""; onChange({ ...defaultProgramState(latestYear), sort: state.sort, direction: state.direction }); }}>Reset filters</button>
      </div>
      <form className="field" role="search" onSubmit={(e) => { e.preventDefault(); applied.current = text; onChange({ ...state, search: text, page: 0 }); }}>
        <label htmlFor="program-search">Search university or program</label>
        <input id="program-search" type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Hukuk, mühendislik, 001010101"
          aria-describedby="program-search-hint" />
        <span className="field-hint" id="program-search-hint">Matches university, program, faculty or code; ignores case and Turkish accents.</span>
      </form>
      <div className="field">
        <label htmlFor="program-year">Admission year</label>
        <select id="program-year" value={state.year === null ? "all" : String(state.year)} onChange={(e) => set({ year: e.target.value === "all" ? null : Number(e.target.value) })}>
          {[...(facets?.years ?? [])].reverse().map((y) => <option key={y} value={y}>{y}{y === latestYear ? " (latest)" : ""}</option>)}
          <option value="all">All years</option>
        </select>
        <span className="field-hint">Rows are program × year; a program with no row for a year is not shown for it (absence is not zero).</span>
      </div>
      {facets ? (
        <>
          <CheckGroup legend="Score type" field="score" options={facets.score_types} selected={state.score_types} onToggle={(v) => toggle("score_types", v)}
            hint="Labels exactly as the registry source writes them." />
          <CheckGroup legend="Scholarship" field="scholarship" options={facets.scholarships} selected={state.scholarships} onToggle={(v) => toggle("scholarships", v)} />
          <CheckGroup legend="Institution" field="university" options={facets.universities} selected={state.university_keys} onToggle={(v) => toggle("university_keys", v)} />
          {hasTypes ? <CheckGroup legend="Institution type" field="type" options={facets.university_types} selected={state.university_types} onToggle={(v) => toggle("university_types", v)} /> : null}
          {hasLanguages ? <CheckGroup legend="Teaching language" field="lang" options={facets.teaching_languages} selected={state.teaching_languages}
            onToggle={(v) => toggle("teaching_languages", v)} hint="Not specified means the source gave no language; it is not presumed Turkish." /> : null}
          {facets.cities.length === 0 ? <p className="field-hint" style={{ margin: 0 }}>City filter not offered: the registry records no cities (the importer infers none).</p> : null}
        </>
      ) : null}
    </section>
  );
}
