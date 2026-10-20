"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, toApiError } from "./api/client";

export type ApiState<T> = {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  /** True while a refetch for a different key is in flight and the previous data is still shown. */
  stale: boolean;
  reload: () => void;
};

/**
 * Fetch keyed by `key`; `null` means "do not fetch". While refetching, the previous render is kept
 * (callers dim it) instead of flashing a skeleton. Data for a different key is never shown after an
 * error, so a failed request cannot leave another build's numbers on screen.
 */
export function useApi<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): ApiState<T> {
  const [state, setState] = useState<{ key: string | null; data?: T; error?: ApiError; loading: boolean }>({
    key: null,
    loading: key !== null,
  });
  const [nonce, setNonce] = useState(0);
  const loader = useRef(load);
  loader.current = load;

  useEffect(() => {
    if (key === null) {
      setState({ key: null, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: undefined }));
    loader.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ key, data, loading: false });
      },
      (err) => {
        if (controller.signal.aborted) return;
        setState((s) => ({ key, data: s.key === key ? s.data : undefined, error: toApiError(err), loading: false }));
      },
    );
    return () => controller.abort();
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return {
    data: state.data,
    error: state.error,
    loading: state.loading,
    stale: state.loading && state.data !== undefined && state.key !== key,
    reload,
  };
}
