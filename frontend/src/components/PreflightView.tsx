import type { Schemas } from "@/lib/api/client";
import { fmtInt, fmtUsd } from "@/lib/format";
import { CopyId } from "./CopyId";
import { Notice } from "./Notices";
import { KeyValues } from "./StatTile";
import { Badge } from "./StatusBadge";

/** The immutable reviewed plan. Everything shown here was produced without any provider call. */
export function PreflightView({ plan }: { plan: Omit<Schemas["Preflight"], "model_seed"> }) {
  return (
    <div className="stack">
      <p className="row small">
        <Badge tone="good" glyph="✓">{`${plan.provider_calls_made} provider calls made by preflight`}</Badge>
        <span className="muted">Created {plan.created_at}</span>
      </p>
      <KeyValues items={[
        ["Preflight hash", <CopyId key="h" value={plan.preflight_hash} label="preflight hash" />],
        ["Mode", plan.mode],
        ["Realized resident IDs", plan.realized_ids.join(", ")],
        ["Task", <span key="t"><code>{plan.task_path}</code> (instrument <code>{plan.instrument_id}</code>)</span>],
        ["Task content hash", plan.task_hash ? <code key="th">{plan.task_hash}</code> : "unknown"],
        ["Model", <code key="m">{plan.model ?? "–"}</code>],
        ["Temperature", plan.temperature === null ? "not applicable" : String(plan.temperature)],
        plan.mode === "preflight"
          ? ["Calls a live run of this plan would make", `${plan.planned_provider_calls}. This preflight-only draft cannot execute; your limit is ${plan.calls_limit}.`]
          : ["Planned provider calls", `${plan.planned_provider_calls} (logical calls ${plan.planned_logical_calls}; your limit ${plan.calls_limit})`],
        ["Automatic retries", String(plan.automatic_retries)],
        ["Output-token cap", plan.output_token_cap === null ? "None enforced by the runner for this provider" : fmtInt(plan.output_token_cap)],
        ["Input-token estimate", plan.input_token_estimate === null ? "unknown" : `${fmtInt(plan.input_token_estimate)} (${plan.estimate_method})`],
        ["Cost estimate", plan.cost_estimate_usd === null ? `unknown: ${plan.cost_note ?? ""}` : `${fmtUsd(plan.cost_estimate_usd)} (${plan.cost_source})`],
        ["Model-side seed", "Not available; a cohort seed does not make model outputs deterministic."],
        ["Credential flag from the runner", `${plan.runner_reported_credentials_present === null ? "not reported" : String(plan.runner_reported_credentials_present)}. ${plan.runner_credentials_note}`],
        ["Dependency readiness", plan.dependency_readiness
          ? `runtime files ready; import probe ${plan.dependency_readiness.runtime_probe}${plan.dependency_readiness.provider_key_present === null ? "" : `; provider key present: ${plan.dependency_readiness.provider_key_present}`}${plan.dependency_readiness.live_execution_enabled === null ? "" : `; live execution enabled: ${plan.dependency_readiness.live_execution_enabled}`}. ${plan.dependency_readiness.note}`
          : "not recorded"],
        ["Staleness", plan.stale_policy],
      ]} />
      {plan.warnings.length ? <Notice tone="warn" title="Warnings:"><ul>{plan.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Notice> : null}
      {plan.trials.map((t) => (
        <details key={t.label}>
          <summary>Trial {t.label}: {t.persona_id} · {t.prompt_visible_fields.length} prompt-visible fields</summary>
          <div className="details-body">
            <KeyValues items={[
              ["Persona file SHA-256", <code key="p">{t.persona_sha256}</code>],
              ["Prompt-visible fields", t.prompt_visible_fields.join(", ")],
              ["System prompt SHA-256", t.system_sha256 ? <code key="s">{t.system_sha256}</code> : "captured during the run"],
              ["Task prompt SHA-256", t.user_sha256 ? <code key="u">{t.user_sha256}</code> : "captured during the run"],
              ["Input-token estimate", t.input_token_estimate === null ? "unknown" : fmtInt(t.input_token_estimate)],
            ]} />
            {t.system_prompt ? (<><h4>Exact system prompt</h4><pre className="prompt">{t.system_prompt}</pre></>) : null}
            {t.user_prompt ? (<><h4>Exact task prompt</h4><pre className="prompt">{t.user_prompt}</pre></>) : null}
          </div>
        </details>
      ))}
      <ul className="small muted">{plan.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
    </div>
  );
}
