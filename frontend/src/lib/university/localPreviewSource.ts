/**
 * Opt-in, development-only source for the Programs explorer: real ÖSYM 2025 Table 4 records read from the git-ignored
 * national CSVs by /api/local-preview/university (see that route). Registry methods only; candidates and simulations
 * are not part of the preview and report themselves unavailable.
 *
 * Enabled with `?source=local-preview` (add `&scope=logos` for universities with a registered logo only).
 */
import { ApiError } from "../api/client";
import { createPendingApiSource } from "./apiSource";
import { queryProgramRows } from "./programs";
import type { UniversityDataSource } from "./source";
import type { RegistryCatalogue, UniversityCapabilities } from "./types";

export const LOCAL_PREVIEW_PARAM = "local-preview";

/** True only in a development build and only when the URL asks for it. */
export function localPreviewRequested(params: URLSearchParams): boolean {
  return process.env.NODE_ENV === "development" && params.get("source") === LOCAL_PREVIEW_PARAM;
}

const CAPS: UniversityCapabilities = {
  origin: "local_preview",
  registry: { available: true, detail: "Local preview of the git-ignored ÖSYM 2025 Table 4 CSVs on this machine (development only)." },
  candidates: { available: false, detail: "Candidates are not part of the local registry preview." },
  execution: { mode: "unavailable", detail: "Simulations are not part of the local registry preview." },
  supported_presets: [],
  unsupported_presets: [],
  limits: { max_cohort_size: 0, quota_adjustment_pct: [-90, 200] },
};

const cache = new Map<string, Promise<RegistryCatalogue>>();

export function createLocalPreviewSource(scope: string | null): UniversityDataSource {
  const key = scope === "logos" ? "logos" : "all";
  const load = (): Promise<RegistryCatalogue> => {
    if (!cache.has(key)) {
      cache.set(key, fetch(`/api/local-preview/university${key === "logos" ? "?scope=logos" : ""}`, { cache: "no-store" }).then(async (r) => {
        if (!r.ok) {
          cache.delete(key);
          const body = await r.json().catch(() => ({}));
          throw new ApiError(r.status, body.code ?? "local_preview_unavailable", body.message ?? "The local preview is not available (development builds only).");
        }
        return r.json() as Promise<RegistryCatalogue>;
      }));
    }
    return cache.get(key)!;
  };
  const check = (c: RegistryCatalogue, id: string) => {
    if (c.snapshot.snapshot_id !== id) throw new ApiError(404, "not_found", `Registry snapshot ${id} was not found.`);
  };
  const pending = createPendingApiSource();
  return {
    ...pending,
    id: `local-preview:${key}`,
    origin: "local_preview",
    capabilities: () => Promise.resolve(CAPS),
    listSnapshots: () => load().then((c) => [c.snapshot]),
    getCatalogue: (id) => load().then((c) => { check(c, id); return c; }),
    queryPrograms: (q) => load().then((c) => { check(c, q.snapshot_id); return queryProgramRows(c, q); }),
    getProgram: (id, code) => load().then((c) => {
      check(c, id);
      const program = c.programs.find((p) => p.program_code === code);
      if (!program) throw new ApiError(404, "not_found", `Program ${code} was not found.`);
      const university = c.universities.find((u) => u.university_id === program.university_id)!;
      return { snapshot: c.snapshot, program, university, admissions: c.admissions.filter((a) => a.program_id === program.program_id), tuition: [],
        issues: c.issues.filter((i) => i.program_id === program.program_id) };
    }),
  };
}
