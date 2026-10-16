"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { api, type ApiError, type Schemas, unwrap } from "./api/client";
import { useApi } from "./useApi";

type BuildContextValue = {
  builds: Schemas["BuildDescriptor"][];
  relations: Schemas["BuildRelation"][];
  loadErrors: Schemas["LoadError"][];
  /** The build the page should use, or null when none can be used. */
  build: Schemas["BuildDescriptor"] | null;
  buildId: string | null;
  /** True when no ?build= was given and the registered default is in use. */
  usingDefault: boolean;
  /** Set when ?build= names something that is not registered; nothing else is substituted. */
  missingBuildId: string | null;
  loading: boolean;
  error: ApiError | undefined;
  reload: () => void;
  select: (id: string) => void;
};

const BuildContext = createContext<BuildContextValue | null>(null);

export function BuildProvider({ children }: { children: ReactNode }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const requested = params.get("build");
  const list = useApi("builds", (signal) => unwrap(api.GET("/api/v1/builds", { signal })));

  const value = useMemo<BuildContextValue>(() => {
    const builds = list.data?.items ?? [];
    const byId = requested ? builds.find((b) => b.build_id === requested) ?? null : null;
    const fallback = !requested && list.data?.default_build_id
      ? builds.find((b) => b.build_id === list.data?.default_build_id) ?? null
      : null;
    const build = requested ? byId : fallback;
    return {
      builds,
      relations: list.data?.relations ?? [],
      loadErrors: list.data?.load_errors ?? [],
      build,
      buildId: build?.build_id ?? null,
      usingDefault: !requested && build !== null,
      missingBuildId: requested && list.data && !byId ? requested : null,
      loading: list.loading,
      error: list.error,
      reload: list.reload,
      select: () => undefined,
    };
  }, [list.data, list.loading, list.error, list.reload, requested]);

  const select = useCallback(
    (id: string) => {
      const next = new URLSearchParams(params.toString());
      next.set("build", id);
      for (const key of ["page", "record"]) next.delete(key);
      router.replace(`${pathname}?${next.toString()}`);
    },
    [params, pathname, router],
  );

  return <BuildContext.Provider value={{ ...value, select }}>{children}</BuildContext.Provider>;
}

export function useBuild(): BuildContextValue {
  const ctx = useContext(BuildContext);
  if (!ctx) throw new Error("useBuild must be used inside BuildProvider");
  return ctx;
}

/** The ID to carry in links: only an explicit choice is propagated, so the default stays visible as default. */
export function useLinkBuildId(): string | null {
  const params = useSearchParams();
  return params.get("build");
}
