/**
 * Deterministic SYNTHETIC applicant cohort for the frontend, mirroring the distributions and JSON shape of
 * `societytwin.candidates.generate` (candidate-development-v1): age uniform 17–25, score type uniform over
 * SAY/EA/SOZ/DIL, achievement an independent uniform proxy 0–10000 (higher is better, not a YKS score or rank),
 * and null location/interests/budget.
 *
 * Differences from the Python generator, stated in the manifest:
 *   - the PRNG is mulberry32, not the SHA-256 counter stream, so values are not byte-identical;
 *   - the Python handoff has no preference model; these preferences are ARTIFICIAL fixture lists (popularity-weighted
 *     draws without replacement) with a few deliberate defects: score-type mismatches, an unknown program code
 *     and some candidates with no preferences, so validation states are visible.
 * Candidate N's attributes depend only on the seed and N, so a larger cohort extends a smaller one with the same seed.
 */
import type { Candidate, Cohort, CohortManifest, Preference } from "../types";
import { below, rng, scoreTypeKey } from "../util";
import { buildRegistryFixture, FIXTURE_POPULARITY, FIXTURE_SNAPSHOT_ID } from "./registry";

export const FIXTURE_COHORT_GENERATOR = "frontend-fixture-candidates-v1";
export const DEFAULT_COHORT = { seed: 42, size: 1000 } as const;
export const MAX_FIXTURE_COHORT = 5000;
/** A program code that does not exist in the fixture snapshot, used to exercise "invalid preference reference". */
export const UNKNOWN_PROGRAM_CODE = "009999901";
const SCORE_TYPES = ["SAY", "EA", "SOZ", "DIL"] as const;

export type { Cohort } from "../types";

export function cohortId(seed: number, size: number): string {
  return `fixture-cohort-s${seed}-n${size}`;
}

export function parseCohortId(id: string): { seed: number; size: number } | null {
  const m = /^fixture-cohort-s(\d+)-n(\d+)$/.exec(id);
  if (!m) return null;
  const seed = Number(m[1]);
  const size = Number(m[2]);
  return Number.isSafeInteger(seed) && Number.isSafeInteger(size) && size >= 1 && size <= MAX_FIXTURE_COHORT ? { seed, size } : null;
}

const cache = new Map<string, Cohort>();

function candidateDraws(seed: number, index: number) {
  // One independent stream per candidate and attribute, so candidate N never depends on cohort size.
  const ages = rng(seed, `candidate:age:v1:${index}`);
  const types = rng(seed, `candidate:score-type:v1:${index}`);
  const proxies = rng(seed, `candidate:achievement:v1:${index}`);
  const prefs = rng(seed, `fixture:preferences:v1:${index}`);
  return { ages, types, proxies, prefs };
}

export function buildCohort(seed: number = DEFAULT_COHORT.seed, size: number = DEFAULT_COHORT.size): Cohort {
  const id = cohortId(seed, size);
  const hit = cache.get(id);
  if (hit) return hit;
  const registry = buildRegistryFixture();
  const programs = registry.programs;
  const candidates: Candidate[] = [];
  const preferences: Preference[] = [];
  for (let i = 0; i < size; i++) {
    const d = candidateDraws(seed, i);
    const candidateId = `candidate-${String(i + 1).padStart(8, "0")}`;
    const scoreType = SCORE_TYPES[below(d.types, SCORE_TYPES.length)];
    candidates.push({
      candidate_id: candidateId, age: 17 + below(d.ages, 9), home_location: null, score_type: scoreType,
      achievement: { kind: "synthetic_proxy", value: below(d.proxies, 10001), scale: "integer 0..10000; higher is better; not a YKS score or rank" },
      educational_interests: null, annual_budget_try: null,
    });
    const roll = d.prefs();
    const count = roll < 0.02 ? 0 : 1 + below(d.prefs, 8);
    const chosen = new Set<string>();
    let invalidUsed = false;
    for (let position = 1; position <= count; position++) {
      const r = d.prefs();
      let code: string | null = null;
      if (!invalidUsed && r < 0.015) {
        code = UNKNOWN_PROGRAM_CODE;
        invalidUsed = true;
      } else {
        const anyType = r > 0.92;
        const pool = programs.filter((p) => !chosen.has(p.program_code) && (anyType || scoreTypeKey(p.score_type) === scoreType));
        if (pool.length === 0) break;
        const weights = pool.map((p) => FIXTURE_POPULARITY.get(p.program_code) ?? 1);
        let t = d.prefs() * weights.reduce((a, b) => a + b, 0);
        for (let k = 0; k < pool.length; k++) {
          t -= weights[k];
          if (t <= 0 || k === pool.length - 1) { code = pool[k].program_code; break; }
        }
      }
      if (code === null) break;
      chosen.add(code);
      preferences.push({ candidate_id: candidateId, program_id: code, position });
    }
  }
  const manifest: CohortManifest = {
    cohort_id: id,
    generator_version: FIXTURE_COHORT_GENERATOR,
    stream_version: "mulberry32-fixture-v1",
    configuration: { size, seed },
    data_versions: { applicant_data: null },
    evidence: { applicant_distributions: "none available; no empirical applicant calibration" },
    assumptions: {
      age: "development assumption: uniform integers 17..25 inclusive",
      score_type: "development assumption: uniform SAY, EA, SOZ, DIL labels; not a statement of eligibility",
      achievement: "development assumption: independent uniform synthetic proxy 0..10000, higher better; not a score or rank",
      relationships: "independent draws; joint relationships are unsupported",
      unknowns: "home location, educational interests and annual budget are unknown (null)",
    },
    preference_source: "artificial frontend fixture; popularity-weighted draws without replacement; not a behavioral model",
    registry_snapshot: FIXTURE_SNAPSHOT_ID,
    origin: "fixture",
    fixture_notes: [
      "Mirrors the distributions of candidate-development-v1 with a different PRNG; values are not byte-identical to the Python generator.",
      "Preferences are artificial. About 8% of draws ignore score type and some lists include an unknown program code, to exercise validation.",
      "Candidates are fictional synthetic applicants, not real students.",
    ],
  };
  const cohort = { manifest, candidates, preferences };
  cache.set(id, cohort);
  return cohort;
}
