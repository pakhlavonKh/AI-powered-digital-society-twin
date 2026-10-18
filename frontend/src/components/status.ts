export type Tone = "good" | "warn" | "crit" | "info" | "neutral" | "fake";

export type StatusInfo = { label: string; tone: Tone; glyph: string; description: string };

/** One vocabulary for run and job states, so the same evidence always reads the same way. */
export const RUN_STATES: Record<string, StatusInfo> = {
  completed: { label: "Completed", tone: "good", glyph: "✓", description: "Completion evidence recorded for every planned trial." },
  completed_fake: { label: "Fake smoke run", tone: "fake", glyph: "◇", description: "Deterministic fake transport; wiring check only, zero provider calls." },
  partial: { label: "Partial", tone: "warn", glyph: "◐", description: "Some trial results saved; no completed comparison." },
  outcome_unknown: { label: "Outcome unknown", tone: "warn", glyph: "?", description: "A request was started but no response or failure was recorded. Not known to have failed, and not running." },
  prepared_only: { label: "Prepared only", tone: "neutral", glyph: "○", description: "Only a preflight plan exists." },
  malformed: { label: "Malformed evidence", tone: "crit", glyph: "!", description: "Evidence files could not be parsed." },
  unrecognized: { label: "Unrecognized", tone: "neutral", glyph: "·", description: "No recognised runner layout." },
  draft: { label: "Draft", tone: "neutral", glyph: "○", description: "Saved configuration; nothing has run." },
  prepared: { label: "Prepared", tone: "info", glyph: "◎", description: "A reviewed preflight exists; nothing has run." },
  queued: { label: "Queued", tone: "info", glyph: "…", description: "Waiting for the local worker." },
  running: { label: "Running", tone: "info", glyph: "▸", description: "Claimed by the local worker." },
  failed: { label: "Failed", tone: "crit", glyph: "×", description: "The managed job ended with an error." },
  stopped: { label: "Stopped", tone: "neutral", glyph: "■", description: "Cancelled before it started." },
  completed_with_errors: { label: "Completed with errors", tone: "warn", glyph: "◐", description: "Some final responses are invalid or failed; they are listed, never dropped." },
  budget_stopped: { label: "Stopped at budget", tone: "warn", glyph: "■", description: "The call or cost cap was reached; remaining calls were not made." },
  unknown_after_interruption: { label: "Unknown after interruption", tone: "warn", glyph: "?", description: "The worker stopped mid-job; the outcome is unknown and it was not retried." },
};

export const TRIAL_STATES: Record<string, StatusInfo> = {
  result_recorded: { label: "Result recorded", tone: "good", glyph: "✓", description: "A survey result was saved for this trial." },
  fake_result: { label: "Fake result", tone: "fake", glyph: "◇", description: "Answers from the deterministic fake transport." },
  request_started_no_response: { label: "Request started, no response", tone: "warn", glyph: "?", description: "Outcome unknown." },
  response_without_saved_result: { label: "Response without saved result", tone: "warn", glyph: "◐", description: "A response was recorded at the model boundary but no result file exists." },
  no_trial_evidence: { label: "No trial evidence", tone: "neutral", glyph: "·", description: "Planned, but nothing was recorded." },
};

export const HASH_STATES: Record<string, StatusInfo> = {
  match: { label: "Byte-identical", tone: "good", glyph: "✓", description: "The recorded digest equals the current file bytes." },
  line_ending_equivalent: { label: "Line-ending drift", tone: "warn", glyph: "≈", description: "Matches only after LF/CRLF conversion: explained drift, not verified byte identity." },
  mismatch: { label: "Mismatch", tone: "crit", glyph: "×", description: "The current file differs from the recorded digest." },
  unavailable: { label: "Not comparable", tone: "neutral", glyph: "·", description: "The file or the recorded digest is unavailable." },
};

export function statusInfo(table: Record<string, StatusInfo>, key: string | null | undefined): StatusInfo {
  return (key && table[key]) || { label: key ?? "unknown", tone: "neutral", glyph: "·", description: "" };
}
