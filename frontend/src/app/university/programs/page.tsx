"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { FixtureNotice, SnapshotGate } from "@/components/university/Gate";
import { ProgramExplorer } from "@/components/university/ProgramExplorer";
import { programStateFromParams, programStateToParams, type ProgramUrlState } from "@/lib/university/programs";
import type { RegistrySnapshot } from "@/lib/university/types";

function Explorer({ snapshot }: { snapshot: RegistrySnapshot }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const latest = snapshot.admission_years[snapshot.admission_years.length - 1] ?? null;
  const state = programStateFromParams(params, latest);
  const selected = params.get("program");
  const paramString = params.toString();
  const onChange = useCallback((s: ProgramUrlState) => {
    const next = programStateToParams(s, latest, new URLSearchParams(paramString));
    router.replace(`${pathname}${next.toString() ? `?${next.toString()}` : ""}`, { scroll: false });
  }, [latest, paramString, pathname, router]);
  const onSelect = (code: string | null) => {
    const next = new URLSearchParams(paramString);
    if (code) next.set("program", code); else next.delete("program");
    router.replace(`${pathname}${next.toString() ? `?${next.toString()}` : ""}`, { scroll: false });
  };
  return <ProgramExplorer snapshot={snapshot} state={state} onChange={onChange} selected={selected} onSelect={onSelect} />;
}

export default function ProgramsPage() {
  return (
    <>
      <PageHeader title="University & Program Explorer">
        Browse university programs in the registry snapshot: reported quota indicators, placed counts and last-placed success ranks by admission year.
        These are historical registry observations, not simulation results. Filters live in the URL, so a view can be shared.
      </PageHeader>
      <FixtureNotice kind="registry" />
      <SnapshotGate>{(snapshot) => <Explorer snapshot={snapshot} />}</SnapshotGate>
    </>
  );
}
