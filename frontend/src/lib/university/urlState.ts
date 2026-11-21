"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * URL search params as page state, without lag or lost updates.
 *
 * `router.replace` updates `useSearchParams()` asynchronously. Reading state only from the URL makes a controlled
 * checkbox lag behind the click, and two quick changes race: the second builds on the stale URL and drops the
 * first. Here every update builds on the latest *intended* query string and is shown immediately; the pending value
 * is dropped once the real URL reaches it (or the URL moves somewhere else, e.g. back/forward navigation).
 */
export function useUrlParams() {
  const actual = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const actualKey = actual.toString();
  const [targets, setTargets] = useState<string[]>([]);
  useEffect(() => {
    setTargets((t) => {
      if (t.length === 0) return t;
      const i = t.indexOf(actualKey);
      return i === -1 ? [] : t.slice(i + 1);
    });
  }, [actualKey]);
  const effectiveKey = targets.length ? targets[targets.length - 1] : actualKey;
  const latest = useRef(effectiveKey);
  latest.current = effectiveKey;
  const params = useMemo(() => new URLSearchParams(effectiveKey), [effectiveKey]);
  const update = useCallback((mutate: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(latest.current);
    mutate(next);
    const key = next.toString();
    latest.current = key;
    setTargets((t) => [...t, key]);
    router.replace(`${pathname}${key ? `?${key}` : ""}`, { scroll: false });
  }, [pathname, router]);
  return { params, update };
}
