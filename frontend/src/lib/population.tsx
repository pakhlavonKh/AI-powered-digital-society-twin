"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import type { ApiError } from "./api/client";
import { v2, type PopulationList, type PopulationListItem } from "./api/v2";
import { useApi } from "./useApi";

type PopulationContextValue = {
  items: PopulationListItem[];
  population: PopulationListItem | null;
  populationId: string | null;
  /** True when no ?pop= was given and the newest population is in use. */
  usingDefault: boolean;
  /** ?pop= names something that does not exist; nothing else is substituted. */
  missingId: string | null;
  loading: boolean;
  error: ApiError | undefined;
  reload: () => void;
  select: (id: string) => void;
};

const PopulationContext = createContext<PopulationContextValue | null>(null);

export function PopulationProvider({ children }: { children: ReactNode }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requested = params.get("pop");
  const list = useApi("v2:populations", (signal) => v2<PopulationList>("/populations", { signal }));

  const value = useMemo(() => {
    const items = list.data?.items ?? [];
    const byId = requested ? items.find((p) => p.population_id === requested) ?? null : null;
    const fallback = !requested && list.data?.default_population_id ? items.find((p) => p.population_id === list.data?.default_population_id) ?? null : null;
    const population = requested ? byId : fallback;
    return {
      items, population, populationId: population?.population_id ?? null, usingDefault: !requested && population !== null,
      missingId: requested && list.data && !byId ? requested : null, loading: list.loading, error: list.error, reload: list.reload,
    };
  }, [list.data, list.loading, list.error, list.reload, requested]);

  const select = useCallback((id: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("pop", id);
    for (const key of ["page", "record"]) next.delete(key);
    router.replace(`${pathname}?${next.toString()}`);
  }, [params, pathname, router]);

  return <PopulationContext.Provider value={{ ...value, select }}>{children}</PopulationContext.Provider>;
}

export function usePopulation(): PopulationContextValue {
  const ctx = useContext(PopulationContext);
  if (!ctx) throw new Error("usePopulation must be used inside PopulationProvider");
  return ctx;
}

/** Only an explicit ?pop= choice is carried in links, so the default stays visible as the default. */
export function useLinkPop(): string | null {
  return useSearchParams().get("pop");
}

export function withPop(path: string, pop: string | null | undefined, extra?: Record<string, string | undefined>): string {
  const [base, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  if (pop) params.set("pop", pop);
  for (const [k, v] of Object.entries(extra ?? {})) {
    if (v === undefined || v === "") params.delete(k);
    else params.set(k, v);
  }
  const s = params.toString();
  return s ? `${base}?${s}` : base;
}
