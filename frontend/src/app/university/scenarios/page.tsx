"use client";

import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, Loading, UnavailableState } from "@/components/States";
import { FixtureNotice, SnapshotGate } from "@/components/university/Gate";
import { ScenarioSetup } from "@/components/university/ScenarioSetup";
import { useCatalogue, useSelectedSnapshot, useUniversityCapabilities, useUniversitySource } from "@/lib/university/context";
import type { PresetId, RegistrySnapshot } from "@/lib/university/types";
import { useApi } from "@/lib/useApi";

function Setup({ snapshot }: { snapshot: RegistrySnapshot }) {
  const source = useUniversitySource();
  const params = useSearchParams();
  const caps = useUniversityCapabilities();
  const catalogue = useCatalogue(snapshot.snapshot_id);
  const { snapshots } = useSelectedSnapshot();
  const cohorts = useApi(`uni:${source.id}:cohorts`, (signal) => source.listCohorts(signal));
  const failed = caps.error ?? catalogue.error ?? cohorts.error;
  if (failed) return <ErrorState error={failed} onRetry={() => { caps.reload(); catalogue.reload(); cohorts.reload(); }} what="scenario setup" />;
  if (!caps.data || !catalogue.data || !cohorts.data) return <Loading what="registry, cohorts and capabilities" />;
  if (!cohorts.data.length) return <UnavailableState title="No candidate cohort is available." reasons={["A scenario needs a synthetic candidate cohort with preferences."]} />;
  return <ScenarioSetup key={snapshot.snapshot_id} catalogue={catalogue.data} snapshots={snapshots} caps={caps.data} cohortBase={cohorts.data[0]}
    initialPreset={params.get("preset") as PresetId | null} />;
}

export default function ScenariosPage() {
  return (
    <>
      <PageHeader title="Scenario Setup">
        Configure a university placement scenario from supported inputs without editing JSON. Every input is validated before it can run; unsupported
        scenario types are listed with the reason.
      </PageHeader>
      <FixtureNotice kind="simulation" />
      <SnapshotGate>{(snapshot) => <Setup snapshot={snapshot} />}</SnapshotGate>
    </>
  );
}
