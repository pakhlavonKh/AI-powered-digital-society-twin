"use client";

import { useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { FixtureNotice, SnapshotGate } from "@/components/university/Gate";
import { ProgramExplorer } from "@/components/university/ProgramExplorer";
import { programStateFromParams, programStateToParams, type ProgramUrlState } from "@/lib/university/programs";
import type { RegistrySnapshot } from "@/lib/university/types";
import { useUrlParams } from "@/lib/university/urlState";

function Explorer({ snapshot }: { snapshot: RegistrySnapshot }) {
  const { params, update } = useUrlParams();
  const latest = snapshot.admission_years[snapshot.admission_years.length - 1] ?? null;
  const state = programStateFromParams(params, latest);
  const onChange = useCallback((s: ProgramUrlState) => update((p) => {
    const next = programStateToParams(s, latest, p);
    for (const k of [...p.keys()]) p.delete(k);
    next.forEach((v, k) => p.append(k, v));
  }), [latest, update]);
  const onSelect = (code: string | null) => update((p) => { if (code) p.set("program", code); else p.delete("program"); });
  return <ProgramExplorer snapshot={snapshot} state={state} onChange={onChange} selected={params.get("program")} onSelect={onSelect} />;
}

export default function ProgramsPage() {
  return (
    <>
      <PageHeader title="Programs">
        Explore university programs and admission details across Türkiye: reported quotas, placed counts and admission ranks by admission year.
        These are registry observations, not simulation results; filters live in the URL, so a view can be shared.
      </PageHeader>
      <FixtureNotice kind="registry" />
      <SnapshotGate>{(snapshot) => <Explorer snapshot={snapshot} />}</SnapshotGate>
    </>
  );
}
