"use client";

import { useEffect, useRef, useState } from "react";
import { englishLabel } from "@/lib/university/labels";
import { defaultProgramState, type ProgramUrlState } from "@/lib/university/programs";
import { MISSING_VALUE, type FacetValue, type ProgramFacets } from "@/lib/university/types";
import { Icon } from "../Icon";
import { ActiveFilters, FilterMenu } from "./common";

type ListKey = "score_types" | "scholarships" | "university_keys" | "university_types" | "teaching_languages";

/**
 * Filter toolbar above the program table. Filters combine with AND across fields and OR within a field. Options come
 * from the snapshot itself; fields the snapshot has no data for are not offered. Values (and so the URL) are the exact
 * source labels; scholarship, institution-type and language labels are only displayed in English.
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
  const reset = () => { setText(""); applied.current = ""; onChange({ ...defaultProgramState(latestYear), sort: state.sort, direction: state.direction, size: state.size }); };
  const hasTypes = (facets?.university_types ?? []).some((f) => f.value !== MISSING_VALUE);
  const hasLanguages = (facets?.teaching_languages ?? []).some((f) => f.value !== MISSING_VALUE);

  const labelOf = (options: FacetValue[] | undefined, value: string, translate: boolean) => {
    const o = options?.find((x) => x.value === value);
    if (!o) return value;
    return translate && value !== MISSING_VALUE ? englishLabel(o.label) : o.label;
  };
  const chips: { key: string; label: string; onRemove: () => void }[] = [];
  if (state.search) chips.push({ key: "q", label: `Search: “${state.search}”`, onRemove: () => { setText(""); applied.current = ""; set({ search: "" }); } });
  const groups: [ListKey, string, FacetValue[] | undefined, boolean][] = [
    ["score_types", "Score type", facets?.score_types, false], ["scholarships", "Scholarship", facets?.scholarships, true],
    ["university_types", "Institution type", facets?.university_types, true], ["university_keys", "University", facets?.universities, false],
    ["teaching_languages", "Language", facets?.teaching_languages, true],
  ];
  for (const [key, title, options, translate] of groups) {
    for (const v of state[key]) chips.push({ key: `${key}:${v}`, label: `${title}: ${labelOf(options, v, translate)}`, onRemove: () => toggle(key, v) });
  }

  return (
    <section className="card filter-toolbar" aria-label="Program filters">
      <div className="toolbar-grid">
        <form className="field toolbar-field toolbar-search" role="search" onSubmit={(e) => { e.preventDefault(); applied.current = text; onChange({ ...state, search: text, page: 0 }); }}>
          <label className="toolbar-label" htmlFor="program-search">Search university or program</label>
          <div className="search-input">
            <Icon name="search" size={14} />
            <input id="program-search" type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Name or program code, e.g. Hukuk or 001010101"
              aria-describedby="program-search-hint" />
          </div>
          <span className="visually-hidden" id="program-search-hint">Matches university, program, faculty or code as written in the source (program names are in Turkish); ignores case and Turkish accents.</span>
        </form>
        <div className="field toolbar-field">
          <label className="toolbar-label" htmlFor="program-year">Admission year</label>
          <select id="program-year" value={state.year === null ? "all" : String(state.year)} onChange={(e) => set({ year: e.target.value === "all" ? null : Number(e.target.value) })}>
            {[...(facets?.years ?? [])].reverse().map((y) => <option key={y} value={y}>{y}{y === latestYear ? " (latest)" : ""}</option>)}
            <option value="all">All years</option>
          </select>
        </div>
        {facets ? (
          <>
            <FilterMenu id="score" label="Score type" options={facets.score_types} selected={state.score_types} onToggle={(v) => toggle("score_types", v)}
              onClear={() => set({ score_types: [] })} hint="Official ÖSYM codes, as the registry writes them." />
            <FilterMenu id="scholarship" label="Scholarship" options={facets.scholarships} selected={state.scholarships} onToggle={(v) => toggle("scholarships", v)}
              onClear={() => set({ scholarships: [] })} display={englishLabel} hint="English labels; hover an option for the source label." />
            {hasTypes ? <FilterMenu id="type" label="Institution type" options={facets.university_types} selected={state.university_types}
              onToggle={(v) => toggle("university_types", v)} onClear={() => set({ university_types: [] })} display={englishLabel} /> : null}
            <FilterMenu id="university" label="University" options={facets.universities} selected={state.university_keys} onToggle={(v) => toggle("university_keys", v)}
              onClear={() => set({ university_keys: [] })} />
            {hasLanguages ? <FilterMenu id="lang" label="Teaching language" options={facets.teaching_languages} selected={state.teaching_languages}
              onToggle={(v) => toggle("teaching_languages", v)} onClear={() => set({ teaching_languages: [] })} display={englishLabel}
              hint="Not specified means the source gave no language; it is not presumed Turkish." /> : null}
          </>
        ) : null}
        <div className="toolbar-actions">
          <button type="button" className="button" onClick={reset}><Icon name="refresh" size={13} /> Reset filters</button>
        </div>
      </div>
      <ActiveFilters items={chips} onClearAll={reset} />
    </section>
  );
}
