/** Build a same-origin path that preserves the selected build (when one was chosen explicitly). */
export function withBuild(path: string, buildId: string | null | undefined, extra?: Record<string, string | undefined>): string {
  const [base, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  if (buildId) params.set("build", buildId);
  for (const [k, v] of Object.entries(extra ?? {})) {
    if (v === undefined || v === "") params.delete(k);
    else params.set(k, v);
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

export function apiPath(path: string): string {
  return `/api/v1${path}`;
}
