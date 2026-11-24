"""Result text summarizer for SocietyTwin policy simulations.

Generates structured text overviews and executive narrative summaries of
simulation results, behavioral distributions, and open-ended/free-text agent responses.
Supports live LLM executive synthesis when an LLM provider key is available,
with automatic fallback to deterministic structured synthesis.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


def _generate_llm_result_summary(
    definition: dict[str, Any],
    valid_responses: list[dict[str, Any]],
    is_free_text: bool,
    options: list[dict[str, Any]],
    option_counts: dict[str, int] | None = None,
    shares_dict: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Generate executive summary using OpenAI if API key is configured."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key)

        title = definition.get("title") or definition.get("scenario", {}).get("title") or "Policy Simulation"
        task = definition.get("task", {})
        task_instruction = task.get("instruction", "").strip()

        if is_free_text:
            quotes = []
            for r in valid_responses[:30]:
                text = (r.get("choice") if r.get("choice") not in ("open_response", None) else None) or r.get("rationale") or r.get("answer") or r.get("raw_response") or ""
                quotes.append(f"- Resident {r.get('synthetic_id', 'citizen')} (Province {r.get('province_code', 'TR')}): \"{text}\"")
            data_context = (
                f"Scenario: {title}\n"
                f"Question / Instruction: {task_instruction}\n"
                f"Response Type: Free-Text Qualitative ({len(valid_responses)} total valid responses)\n"
                f"Citizen Qualitative Responses (sample):\n"
                + "\n".join(quotes)
            )
        else:
            option_labels = {opt["id"]: opt.get("label", opt["id"]) for opt in options}
            lines = []
            for oid, cnt in (option_counts or {}).items():
                lbl = option_labels.get(oid, oid)
                sh = (shares_dict or {}).get(oid, 0.0)
                lines.append(f"- {lbl}: {sh}% ({cnt} respondents)")
            data_context = (
                f"Scenario: {title}\n"
                f"Question / Instruction: {task_instruction}\n"
                f"Response Type: Choice Survey ({len(valid_responses)} total valid responses)\n"
                f"Distribution of choices:\n"
                + "\n".join(lines)
            )
            sample_rats = []
            for r in valid_responses[:15]:
                if r.get("rationale"):
                    sample_rats.append(f"- Resident {r.get('synthetic_id')}: {r['rationale']}")
            if sample_rats:
                data_context += "\n\nSample rationales behind choices:\n" + "\n".join(sample_rats)

        system_instruction = (
            "You are an executive policy advisor and research methodologist. "
            "Synthesize the provided synthetic citizen survey results into an executive policy briefing. "
            "Return a valid JSON object with the following fields:\n"
            "- headline: A punchy, 1-2 sentence executive headline summarizing the outcome.\n"
            "- key_findings: A list of 3-5 concise bullet strings highlighting primary patterns, tensions, or insights.\n"
            "- summary_markdown: A comprehensive Markdown report with sections:\n"
            "  # Executive Policy Result Summary: {title}\n"
            "  ## 1. Executive Synthesis & Core Finding\n"
            "  ## 2. Key Takeaways & Behavioral Dynamics\n"
            "  ## 3. Citizen Perspectives & Qualitative Nuance\n"
            "  ## 4. Policy Implications & Strategic Recommendations\n"
            "- representative_quotes: A list of up to 6 objects with keys 'synthetic_id', 'province_code', 'quote', and 'rationale'.\n"
            "Return ONLY valid JSON."
        )

        model = os.environ.get("SOCIETYTWIN_SUMMARY_MODEL") or "gpt-4o-mini"
        if "/" in model:
            model = model.split("/")[-1]

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": data_context},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        content = response.choices[0].message.content
        if not content:
            return None
        parsed = json.loads(content)
        if not parsed.get("headline") or not parsed.get("key_findings"):
            return None

        return {
            "title": title,
            "headline": str(parsed.get("headline")),
            "key_findings": list(parsed.get("key_findings", [])),
            "summary_markdown": str(parsed.get("summary_markdown", "")),
            "representative_quotes": list(parsed.get("representative_quotes", [])),
            "generated_by": "llm",
        }
    except Exception as exc:
        logger.debug("LLM result summary generation bypassed: %s", exc)
        return None


def generate_result_text_summary(
    definition: dict[str, Any],
    responses: list[dict[str, Any]],
    agg: dict[str, Any] | None = None,
    *,
    allow_llm: bool = False,
) -> dict[str, Any]:
    """Generate a comprehensive executive result text summary from simulation data.

    Synthesizes quantitative shares or qualitative free-text perspectives,
    representative quotes, key behavioral findings, and policy implications.
    Uses LLM synthesis when an LLM key is configured, with deterministic fallback.

    Args:
        definition: Experiment definition dictionary.
        responses: List of raw or database response row dictionaries.
        agg: Optional aggregate response distribution dictionary.

    Returns:
        Structured result summary dictionary containing headline, key_findings,
        quotes, and full markdown report.
    """
    title = definition.get("title") or definition.get("scenario", {}).get("title") or "Policy Simulation"
    task = definition.get("task", {})
    task_instruction = task.get("instruction", "").strip()
    task_response_type = task.get("response_type", "single_choice")
    options = task.get("options", [])
    option_labels = {opt["id"]: opt.get("label", opt["id"]) for opt in options}

    is_free_text = task_response_type == "free_text" or len(options) == 0

    valid_responses = [r for r in responses if r.get("status") in ("ok", "valid")]
    total_valid = len(valid_responses)
    total_responses = len(responses)

    # 1. Handle scenario where no valid responses exist (e.g. backend/API key failure)
    if total_valid == 0:
        error_sample = ""
        for r in responses:
            if r.get("error"):
                error_sample = str(r["error"])
                if len(error_sample) > 200:
                    error_sample = error_sample[:200] + "..."
                break

        headline = (
            f"No valid citizen responses were recorded ({total_responses} attempted, {total_responses} failed). "
            + (f"Reported error: {error_sample}" if error_sample else "Please review backend execution logs.")
        )
        return {
            "title": title,
            "headline": headline,
            "key_findings": [
                f"Total attempted personas: {total_responses}",
                f"Valid responses: 0 (100% failure rate)",
                "Failure cause: Model provider authentication failure (HTTP 401) or runtime exception.",
                "Remediation: Verify your API key in experiments/matraix_simulation/.env or switch to offline mock mode.",
            ],
            "summary_markdown": (
                f"# Execution Incomplete: {title}\n\n"
                f"> [!WARNING]\n"
                f"> **0 of {total_responses} agent responses completed successfully.**\n\n"
                f"**Details:** {error_sample or 'All persona requests returned backend errors.'}\n\n"
                "### Next Steps\n"
                "1. Verify your API credentials in `.env` (ensure active OpenAI / provider key with credit).\n"
                "2. Alternatively, run with mock execution (offline mode) to test without cloud API charges."
            ),
            "representative_quotes": [],
            "is_free_text": is_free_text,
            "total_responses": total_responses,
            "valid_responses": 0,
            "generated_by": "system",
        }

    # 2. Try LLM synthesis if available
    option_counts: dict[str, int] = {}
    shares_dict: dict[str, float] = {}
    if not is_free_text:
        option_counts = {opt["id"]: 0 for opt in options}
        for r in valid_responses:
            ch = r.get("choice")
            if ch in option_counts:
                option_counts[ch] += 1
            elif ch:
                option_counts[ch] = option_counts.get(ch, 0) + 1

        agg_options = (agg.get("overall", {}).get("options", [])) if agg else []
        if agg_options:
            for ao in agg_options:
                val = next(
                    (ao[k] for k in ("weighted_share", "unweighted_share", "share") if ao.get(k) is not None),
                    0.0,
                )
                shares_dict[ao["option_id"]] = round(float(val) * 100.0, 1)
        else:
            denom = total_valid or 1
            for opt_id, cnt in option_counts.items():
                shares_dict[opt_id] = round((cnt / denom) * 100.0, 1)

    model_cfg = definition.get("model", {})
    transport = model_cfg.get("transport")
    backend = model_cfg.get("backend")
    # Strict execution-control gate: fake/stub runs never make external provider requests
    is_live = transport == "live" and backend != "stub"
    opt_in = os.environ.get("SOCIETYTWIN_ALLOW_LLM_SUMMARY", "0") in ("1", "true", "True")

    if is_live and (allow_llm or opt_in):
        llm_res = _generate_llm_result_summary(
            definition=definition,
            valid_responses=valid_responses,
            is_free_text=is_free_text,
            options=options,
            option_counts=option_counts,
            shares_dict=shares_dict,
        )
        if llm_res:
            llm_res.update({
                "is_free_text": is_free_text,
                "total_responses": total_responses,
                "valid_responses": total_valid,
            })
            return llm_res

    # 3. Deterministic template fallback
    key_findings: list[str] = []
    representative_quotes: list[dict[str, Any]] = []

    if is_free_text:
        text_answers: list[str] = []
        for r in valid_responses:
            val = (r.get("choice") if r.get("choice") not in ("open_response", None) else None) or r.get("rationale") or r.get("answer") or r.get("raw_response") or ""
            val_str = str(val).strip()
            if val_str and val_str.lower() not in ("refused", "none", "null"):
                text_answers.append(val_str)
                if len(representative_quotes) < 8:
                    representative_quotes.append({
                        "synthetic_id": r.get("synthetic_id", "RESIDENT"),
                        "province_code": r.get("province_code", "–"),
                        "quote": val_str,
                        "rationale": r.get("rationale"),
                    })

        word_counts = [len(a.split()) for a in text_answers]
        avg_words = round(sum(word_counts) / len(word_counts), 1) if word_counts else 0

        headline = (
            f"Synthetic citizens provided {len(text_answers)} in-depth qualitative responses to '{task_instruction}', "
            f"averaging {avg_words} words per response, highlighting key trade-offs in living costs and daily routines."
        )

        key_findings.append(f"Recorded {len(text_answers)} valid qualitative responses across synthetic personas.")
        key_findings.append(f"Average response depth: {avg_words} words per citizen response.")
        if text_answers:
            key_findings.append(f'Top voiced perspective: "{text_answers[0][:140]}..."')
        if len(text_answers) > 1:
            key_findings.append(f'Alternative perspective: "{text_answers[1][:140]}..."')

        md_lines = [
            f"# Executive Policy Result Summary: {title}",
            "",
            "## 1. Executive Summary & Core Qualitative Finding",
            headline,
            "",
            "## 2. Key Qualitative Takeaways",
        ]
        for kf in key_findings:
            md_lines.append(f"- {kf}")
        md_lines.append("")
        md_lines.append("## 3. Representative Citizen Perspectives (Verbatim Quotes)")
        for rq in representative_quotes:
            md_lines.append(f"> **Resident {rq['synthetic_id']} (Province {rq['province_code']}):**")
            md_lines.append(f'> "{rq["quote"]}"')
            if rq.get("rationale") and rq["rationale"] != rq["quote"]:
                md_lines.append(f"> *Rationale:* {rq['rationale']}")
            md_lines.append("")
        md_lines.append("## 4. Policy Implications & Next Steps")
        md_lines.append("- Open-ended responses indicate notable citizen sensitivity to cost changes and service reliability.")
        md_lines.append("- Clear targeted exemptions and transitional relief may mitigate negative household reactions.")

        summary_markdown = "\n".join(md_lines)

    else:
        sorted_options = sorted(option_counts.keys(), key=lambda oid: shares_dict.get(oid, 0.0), reverse=True)

        top_id = sorted_options[0] if sorted_options else ""
        top_share = shares_dict.get(top_id, 0.0)
        top_label = option_labels.get(top_id, top_id)

        second_id = sorted_options[1] if len(sorted_options) > 1 else ""
        second_share = shares_dict.get(second_id, 0.0)
        second_label = option_labels.get(second_id, second_id)

        if second_id and second_share > 0:
            headline = (
                f"Simulation results indicate a clear plurality: {top_share}% of synthetic respondents chose "
                f"'{top_label}', followed by {second_share}% choosing '{second_label}'."
            )
        else:
            headline = (
                f"Simulation results indicate a clear consensus: {top_share}% of synthetic respondents chose "
                f"'{top_label}'."
            )

        key_findings.append(f"Primary behavioral outcome: {top_share}% selected '{top_label}' ({option_counts.get(top_id, 0)} respondents).")
        if second_id and second_share > 0:
            key_findings.append(f"Secondary response: {second_share}% selected '{second_label}' ({option_counts.get(second_id, 0)} respondents).")
        key_findings.append(f"Total verified sample: {total_valid} valid persona responses ({total_responses} total attempted).")

        for r in valid_responses:
            rat = r.get("rationale") or r.get("other_text")
            if rat and len(representative_quotes) < 6:
                representative_quotes.append({
                    "synthetic_id": r.get("synthetic_id", "RESIDENT"),
                    "province_code": r.get("province_code", "–"),
                    "choice": option_labels.get(r.get("choice", ""), r.get("choice", "")),
                    "quote": rat,
                    "rationale": rat,
                })

        md_lines = [
            f"# Executive Policy Result Summary: {title}",
            "",
            "## 1. Executive Summary & Core Finding",
            headline,
            "",
            "## 2. Key Findings & Behavioral Breakdown",
        ]
        for kf in key_findings:
            md_lines.append(f"- {kf}")
        md_lines.append("")
        md_lines.append("## 3. Full Distribution of Choices")
        for oid in sorted_options:
            lbl = option_labels.get(oid, oid)
            cnt = option_counts.get(oid, 0)
            sh = shares_dict.get(oid, 0.0)
            md_lines.append(f"- **{lbl}**: **{sh}%** ({cnt} respondents)")
        md_lines.append("")

        if representative_quotes:
            md_lines.append("## 4. Persona Perspectives & Reasons Behind Decisions")
            for rq in representative_quotes:
                md_lines.append(f"> **Resident {rq['synthetic_id']} ({rq.get('choice', '')}):**")
                md_lines.append(f'> "{rq["quote"]}"')
                md_lines.append("")

        md_lines.append("## 5. Policy Implications")
        md_lines.append(f"- The dominant public preference towards '{top_label}' suggests targeted operational interventions are critical.")
        md_lines.append("- Municipal planners should account for potential modal shifts or behavioral adjustments before enactment.")

        summary_markdown = "\n".join(md_lines)

    return {
        "title": title,
        "headline": headline,
        "key_findings": key_findings,
        "summary_markdown": summary_markdown,
        "representative_quotes": representative_quotes,
        "is_free_text": is_free_text,
        "total_responses": total_responses,
        "valid_responses": total_valid,
        "generated_by": "deterministic",
    }


def summarize_placement_result(result: Any) -> dict[str, Any]:
    """Generate a deterministic executive Markdown summary for an offline placement run."""
    m = result.aggregate_metrics
    manifest = result.manifest
    placed = m["placed_count"]
    total = m["total_candidates"]
    unplaced = m["unplaced_count"]
    rate_pct = round(float(m["placement_rate"]) * 100.0, 1)
    first_pct = round(float(m["first_choice_rate"]) * 100.0, 1)
    util_pct = round(float(m["seat_utilization_rate"]) * 100.0, 1)

    headline = (
        f"Offline placement placed {placed} of {total} synthetic candidates ({rate_pct}%), "
        f"with {first_pct}% of placed candidates receiving their 1st preference and "
        f"{util_pct}% general-quota seat utilization."
    )

    key_findings = [
        f"Rule fidelity: {manifest.rule_fidelity} (osym_verified={manifest.osym_verified}).",
        f"Eligible candidates: {m['eligible_candidates']} | Excluded: {m['excluded_candidates']} | Cannot evaluate: {m['cannot_evaluate_candidates']}.",
        f"Unplaced eligible candidates: {unplaced} (reasons: {m['unplaced_reasons_breakdown'] or 'none'}).",
        f"Boundary ties resolved deterministically: {m['tie_break_count']}.",
        f"Net tuition revenue: {m['total_net_tuition_revenue']:,.2f} TL | Need-based aid disbursed: {m['total_need_aid_disbursed']:,.2f} TL.",
    ]

    md_lines = [
        f"# Offline University Placement Summary ({manifest.scenario_id or 'baseline'})",
        "",
        f"> **Disclaimer:** {manifest.disclaimer}",
        "",
        "## 1. Executive Headline",
        headline,
        "",
        "## 2. Key Metrics",
        *[f"- {item}" for item in key_findings],
        "",
        "## 3. Program Outcomes & Cutoffs (General Quotas)",
        "| Program ID | Score Type | Capacity | Filled | Cutoff Score | 1st Choice Demand |",
        "| :--- | :--- | ---: | ---: | ---: | ---: |",
    ]
    for po in result.program_outcomes:
        cutoff_str = f"{po.cutoff_score:.3f}" if po.cutoff_score is not None else "—"
        md_lines.append(
            f"| `{po.program_id}` | {po.score_type} | {po.effective_capacity} | {po.filled} | {cutoff_str} | {po.first_choice_count} |"
        )
    md_lines.extend([
        "",
        f"**Canonical Result SHA-256:** `{manifest.result_sha256}`",
    ])

    return {
        "title": f"Placement Summary: {manifest.scenario_id or 'baseline'}",
        "headline": headline,
        "key_findings": key_findings,
        "summary_markdown": "\n".join(md_lines),
        "osym_verified": manifest.osym_verified,
        "rule_fidelity": manifest.rule_fidelity,
        "disclaimer": manifest.disclaimer,
        "result_sha256": manifest.result_sha256,
        "generated_by": "deterministic",
    }


def summarize_placement_comparison(report: Any) -> dict[str, Any]:
    """Generate a deterministic Markdown report for a baseline-vs-policy comparison."""
    tr = report.transitions
    placed_delta = report.metric_deltas["placed_count"]["delta"]
    rate_delta_pp = round(float(report.metric_deltas["placement_rate"]["delta"] or 0.0) * 100.0, 2)
    net_rev_delta = report.metric_deltas["total_net_tuition_revenue"]["delta"]

    headline = (
        f"Counterfactual comparison ({report.baseline_scenario_id or 'baseline'} -> "
        f"{report.policy_scenario_id or 'policy'}): placed candidates changed by {placed_delta:+d} "
        f"({rate_delta_pp:+.2f} pp); {tr.newly_placed} newly placed, {tr.displaced_to_unplaced} displaced to unplaced."
    )

    key_findings = [
        f"Unchanged placements: {tr.same_program} | Improved preference: {tr.improved_preference} | Worsened preference: {tr.worsened_preference}.",
        f"Newly placed: {tr.newly_placed} | Displaced to unplaced: {tr.displaced_to_unplaced} | Remained unplaced: {tr.remained_unplaced}.",
        f"Eligibility transitions: {tr.eligibility_changed}.",
        f"Net tuition revenue delta: {float(net_rev_delta or 0.0):+,.2f} TL.",
    ]

    md_lines = [
        "# Counterfactual Placement Comparison Report",
        "",
        f"> **Disclaimer:** {report.disclaimer}",
        "",
        "## 1. Executive Headline",
        headline,
        "",
        "## 2. Candidate Migration Summary",
        *[f"- {item}" for item in key_findings],
        "",
        "## 3. Program Capacity & Cutoff Shifts",
        "| Program ID | Cap Δ | Filled Δ | Baseline Cutoff | Policy Cutoff | Cutoff Δ |",
        "| :--- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for pd in report.program_deltas:
        b_cut = f"{pd.baseline_cutoff_score:.3f}" if pd.baseline_cutoff_score is not None else "—"
        p_cut = f"{pd.policy_cutoff_score:.3f}" if pd.policy_cutoff_score is not None else "—"
        c_delta = f"{pd.cutoff_score_delta:+.3f}" if pd.cutoff_score_delta is not None else "—"
        md_lines.append(
            f"| `{pd.program_id}` | {pd.capacity_delta:+d} | {pd.filled_delta:+d} | {b_cut} | {p_cut} | {c_delta} |"
        )

    return {
        "title": "Counterfactual Placement Comparison",
        "headline": headline,
        "key_findings": key_findings,
        "summary_markdown": "\n".join(md_lines),
        "osym_verified": report.osym_verified,
        "rule_fidelity": report.rule_fidelity,
        "disclaimer": report.disclaimer,
        "generated_by": "deterministic",
    }


def summarize_university_result(result: Any) -> dict[str, Any]:
    """Generate a deterministic Markdown report for a single multi-semester university run."""
    manifest = result.manifest
    fs = result.final_summary
    retention_pct = round(float(fs["cumulative_retention_rate"]) * 100.0, 2)

    headline = (
        f"University simulation ({manifest.scenario_id or 'baseline'}, {manifest.semester_count} semesters): "
        f"{fs['final_active_students']}/{fs['initial_students']} active "
        f"({retention_pct:.2f}% cumulative retention), {fs['final_paused_stop_out']} stopped-out, "
        f"{fs['final_withdrawn_dropout']} withdrawn, {fs['final_graduated']} graduated."
    )

    key_findings = [
        (
            f"Final states — Active: {fs['final_active_students']}, Paused (stop-out): {fs['final_paused_stop_out']}, "
            f"Withdrawn (dropout): {fs['final_withdrawn_dropout']}, Graduated: {fs['final_graduated']}."
        ),
        f"Cumulative retention rate (non-graduating): {retention_pct:.2f}% | Final mean GPA: {fs['final_mean_gpa']:.3f}.",
        (
            f"Net tuition revenue: {fs['total_net_tuition_revenue']:,.2f} TL | "
            f"Aid disbursed: {fs['total_aid_disbursed']:,.2f} TL | "
            f"Payment defaults: {fs['total_payment_defaults']}."
        ),
        f"Total waitlisted course requests across terms: {fs['total_waitlisted_requests']}.",
    ]

    md_lines = [
        f"# University Policy Simulation Report ({manifest.scenario_id or 'baseline'})",
        "",
        f"> **Disclaimer:** {manifest.disclaimer}",
        "",
        "## 1. Executive Headline",
        headline,
        "",
        "## 2. Key Metrics",
        *[f"- {item}" for item in key_findings],
        "",
        "## 3. Semester Trajectory",
        "| Term | Active | Paused | Transferred | Withdrawn | Graduated | Mean GPA | Pass Rate | Waitlisted | Net Revenue (TL) |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for sn in result.semester_snapshots:
        pass_str = f"{sn.course_pass_rate * 100:.1f}%" if sn.course_pass_rate is not None else "—"
        md_lines.append(
            f"| {sn.semester} | {sn.active_students} | {sn.paused_stop_out_students} | "
            f"{sn.transferred_students} | {sn.withdrawn_dropout_students} | {sn.graduated_students} | "
            f"{sn.mean_gpa:.3f} | {pass_str} | {sn.total_waitlisted_requests} | {sn.total_net_tuition_revenue:,.2f} |"
        )
    md_lines.extend([
        "",
        f"**Canonical Result SHA-256:** `{manifest.result_sha256}`",
    ])

    return {
        "title": f"University Simulation Summary: {manifest.scenario_id or 'baseline'}",
        "headline": headline,
        "key_findings": key_findings,
        "summary_markdown": "\n".join(md_lines),
        "osym_verified": manifest.osym_verified,
        "coefficients_calibrated": manifest.coefficients_calibrated,
        "disclaimer": manifest.disclaimer,
        "result_sha256": manifest.result_sha256,
        "generated_by": "deterministic",
    }


def summarize_university_comparison(report: Any) -> dict[str, Any]:
    """Generate a deterministic Markdown report for a paired CRN university comparison."""
    pe = report.policy_effects
    ret = pe["cumulative_retention_rate"]
    drop = pe["final_withdrawn_dropout"]
    pause = pe["final_paused_stop_out"]
    rev = pe["total_net_tuition_revenue"]

    ret_pp = round(ret["mean"] * 100.0, 2)
    headline = (
        f"CRN counterfactual ({report.baseline_scenario_id or 'baseline'} -> "
        f"{report.policy_scenario_id or 'policy'}, {report.replications} replications): "
        f"retention changed by {ret_pp:+.2f} pp (p05..p95: {ret['p05']*100:+.2f}..{ret['p95']*100:+.2f} pp), "
        f"dropout {drop['mean']:+.2f}, stop-out {pause['mean']:+.2f}."
    )

    key_findings = [
        (
            f"Cumulative retention: baseline {ret['baseline_mean']*100:.2f}% -> "
            f"policy {ret['policy_mean']*100:.2f}% ({ret_pp:+.2f} pp)."
        ),
        f"Final withdrawn (dropout) delta: {drop['mean']:+.2f} (p05={drop['p05']:+.2f}, p95={drop['p95']:+.2f}).",
        f"Final paused (stop-out) delta: {pause['mean']:+.2f}.",
        f"Total net tuition revenue delta: {rev['mean']:+,.2f} TL.",
    ]

    md_lines = [
        "# Counterfactual University Policy Comparison (CRN)",
        "",
        f"> **Disclaimer:** {report.disclaimer}",
        "",
        "## 1. Executive Headline",
        headline,
        "",
        "## 2. Paired Policy Effects (Policy minus Baseline)",
        "| Metric | Baseline Mean | Policy Mean | Mean Δ | Std | P05 | P50 | P95 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric, stats in pe.items():
        md_lines.append(
            f"| `{metric}` | {stats['baseline_mean']:.4f} | {stats['policy_mean']:.4f} | "
            f"{stats['mean']:+.4f} | {stats['std']:.4f} | {stats['p05']:+.4f} | "
            f"{stats['p50']:+.4f} | {stats['p95']:+.4f} |"
        )

    return {
        "title": "Counterfactual University Policy Comparison",
        "headline": headline,
        "key_findings": key_findings,
        "summary_markdown": "\n".join(md_lines),
        "osym_verified": report.osym_verified,
        "coefficients_calibrated": report.coefficients_calibrated,
        "disclaimer": report.disclaimer,
        "generated_by": "deterministic",
    }


def _fmt_signed_pct(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{val:+.1f}%"


def _collect_grounding_numbers(obj: Any, out: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        v = float(obj)
        out.add(v)
        out.add(abs(v))
        out.add(round(v, 1))
        out.add(round(v, 2))
        out.add(round(abs(v), 1))
        out.add(round(abs(v), 2))
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_grounding_numbers(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_grounding_numbers(item, out)


def _llm_numbers_grounded(texts: list[str], allowed: set[float]) -> bool:
    """Reject LLM text if it introduces numbers absent from deterministic results."""
    for txt in texts:
        for m in re.finditer(r"(?<![A-Za-z0-9_])([+-]?\d[\d,]*(?:\.\d+)?)(?![A-Za-z])", txt):
            raw = m.group(1).replace(",", "")
            try:
                num = float(raw)
            except ValueError:
                continue
            start = m.start()
            # Ignore markdown ordered-list markers like "1. " at line start
            line_prefix = txt[txt.rfind("\n", 0, start) + 1 : m.end() + 1]
            if re.match(r"^\s*\d+\.\s*$", line_prefix):
                continue
            if any(
                abs(num - a) <= max(0.05, abs(a) * 0.005)
                or abs(abs(num) - abs(a)) <= max(0.05, abs(a) * 0.005)
                for a in allowed
            ):
                continue
            return False
    return True


def _build_query_sections(
    query_spec: Any,
    analytics: dict[str, Any],
    *,
    elasticity_range: dict[str, Any] | None = None,
    variant_summaries: list[dict[str, Any]] | None = None,
    sweep_rows: list[dict[str, Any]] | None = None,
    university_comparison: Any | None = None,
) -> list[dict[str, Any]]:
    from .university_analytics import StatisticsSection

    intent = query_spec.intent
    defs = analytics["application_definitions"]
    la = defs["listed_anywhere"]
    tk = defs["listed_top_k"]
    fc = defs["first_choice"]
    pl = defs["placed"]
    cap = analytics["target_capacity"]
    rev = analytics["target_revenue"]
    mig = analytics["migration"]
    cohort_meta = analytics["cohort_metadata"]
    top_k_n = analytics.get("top_k_definition", 3)

    sections: list[StatisticsSection] = []

    # 1. Headline KPI tiles (adapted to intent)
    tile_items: list[dict[str, Any]] = []
    if intent in ("application_demand", "competitor_flow", "composite", "scholarship_aid", "affordability_equity"):
        range_note = ""
        if elasticity_range and "listed_anywhere" in elasticity_range:
            er = elasticity_range["listed_anywhere"]
            range_note = f"Range across elasticities: {er['min']} to {er['max']}"
        tile_items = [
            {
                "label": "Applicants (listed anywhere)",
                "value": f"{la['policy']}",
                "sub": f"Baseline {la['baseline']} ({la['delta']:+d} / {_fmt_signed_pct(la['pct_change'])}){' · ' + range_note if range_note else ''}",
            },
            {
                "label": f"Top-{top_k_n} preference applicants",
                "value": f"{tk['policy']}",
                "sub": f"Baseline {tk['baseline']} ({tk['delta']:+d} / {_fmt_signed_pct(tk['pct_change'])})",
            },
            {
                "label": "1st-choice applicants",
                "value": f"{fc['policy']}",
                "sub": f"Baseline {fc['baseline']} ({fc['delta']:+d} / {_fmt_signed_pct(fc['pct_change'])})",
            },
            {
                "label": "Placed (admitted)",
                "value": f"{pl['policy']}",
                "sub": f"Baseline {pl['baseline']} ({pl['delta']:+d}) · Seats filled {cap['policy_filled']}/{cap['policy']}",
            },
        ]
    elif intent in ("cutoff_impact", "quota_capacity", "placement_fill"):
        tile_items = [
            {"label": "Target capacity", "value": f"{cap['policy']}", "sub": f"Baseline {cap['baseline']} ({cap['delta']:+d} seats)"},
            {"label": "Filled seats", "value": f"{cap['policy_filled']}", "sub": f"Fill rate {cap['policy_fill_rate']*100:.1f}% (was {cap['baseline_fill_rate']*100:.1f}%)"},
            {"label": "Applicants (listed anywhere)", "value": f"{la['policy']}", "sub": f"Baseline {la['baseline']} ({la['delta']:+d})"},
            {"label": "1st-choice demand", "value": f"{fc['policy']}", "sub": f"Baseline {fc['baseline']} ({fc['delta']:+d})"},
        ]
    elif intent == "revenue_tradeoff":
        tile_items = [
            {"label": "Target net tuition revenue", "value": f"{rev['policy']:,.0f} TL", "sub": f"Baseline {rev['baseline']:,.0f} TL ({rev['delta']:+,.0f} TL / {_fmt_signed_pct(rev['pct_change'])})"},
            {"label": "Fee-paying/admitted", "value": f"{pl['policy']}", "sub": f"Baseline {pl['baseline']} ({pl['delta']:+d})"},
            {"label": "Applicants (listed anywhere)", "value": f"{la['policy']}", "sub": f"Baseline {la['baseline']} ({la['delta']:+d})"},
            {"label": "Affordability drops", "value": f"{rev['dropped_due_to_affordability']}", "sub": "Applications dropped due to cost"},
        ]
    else:
        tile_items = [
            {"label": "Applicants (listed anywhere)", "value": f"{la['policy']}", "sub": f"Baseline {la['baseline']} ({la['delta']:+d})"},
            {"label": "1st-choice applicants", "value": f"{fc['policy']}", "sub": f"Baseline {fc['baseline']} ({fc['delta']:+d})"},
            {"label": "Placed (admitted)", "value": f"{pl['policy']}", "sub": f"Baseline {pl['baseline']} ({pl['delta']:+d})"},
            {"label": "Net revenue", "value": f"{rev['policy']:,.0f} TL", "sub": f"Delta {rev['delta']:+,.0f} TL"},
        ]

    sections.append(
        StatisticsSection(
            id="headline_kpis",
            title="Key Simulation Outcomes",
            type="tiles",
            data={
                "items": tile_items,
                "cohort_metadata": cohort_meta,
            },
            caveat=(
                f"Cohort counts (sample_size={cohort_meta['sample_size']}, seed={cohort_meta['seed']}, "
                f"source={cohort_meta['cohort_source']}, scale_factor={cohort_meta['cohort_scale_factor']})."
            ),
        )
    )

    # 2. Comparison variants (e.g. Lower vs Baseline vs Higher ranking, or multi-scenario compare)
    if variant_summaries:
        sections.append(
            StatisticsSection(
                id="variant_comparison",
                title="Scenario Variant Comparison",
                type="comparison_set",
                data={"variants": variant_summaries},
                caveat="All variants share identical Common Random Numbers (CRN) candidate traits and taste draws; rivals stay fixed.",
            )
        )
        sections.append(
            StatisticsSection(
                id="variant_bar_chart",
                title="Applicants & Placed Across Variants",
                type="bar_series",
                data={
                    "x_label": "Variant",
                    "value_label": "Candidates",
                    "series": [
                        {"key": "listed_anywhere", "label": "Applicants (listed anywhere)", "slot": "series-1"},
                        {"key": "placed", "label": "Placed", "slot": "series-2"},
                    ],
                    "rows": [
                        {
                            "category": v["variant_id"],
                            "label": v["label"],
                            "values": {
                                "listed_anywhere": v["listed_anywhere"],
                                "placed": v["placed"],
                            },
                        }
                        for v in variant_summaries
                    ],
                },
            )
        )

    # 3. Revenue / Tuition Sweep Curve
    if sweep_rows:
        sections.append(
            StatisticsSection(
                id="tuition_sweep_curve",
                title="Tuition Sweep: Net Revenue vs. Applicants",
                type="line_series",
                data={
                    "x_key": "label",
                    "x_label": "Tuition Change %",
                    "series": [
                        {"key": "net_revenue_k_tl", "label": "Net Tuition Revenue (k TL)", "slot": "series-1"},
                        {"key": "listed_anywhere", "label": "Applicants (listed anywhere)", "slot": "series-2"},
                    ],
                    "rows": [
                        {
                            "label": f"{row['tuition_change_pct']:+g}%",
                            "tuition_change_pct": row["tuition_change_pct"],
                            "net_revenue_k_tl": round(row["target_net_revenue"] / 1000.0, 2),
                            "listed_anywhere": row["listed_anywhere"],
                            "placed": row["placed"],
                        }
                        for row in sweep_rows
                    ],
                },
                unit="k TL / candidates",
            )
        )

    # 4. Application definitions breakdown table (always explicit so "apply" is never conflated)
    fee_def = defs.get("fee_paying_listed")
    app_rows = [
        ["Listed anywhere on preference list", la["baseline"], la["policy"], f"{la['delta']:+d}", _fmt_signed_pct(la["pct_change"])],
    ]
    if fee_def is not None and not analytics.get("all_target_programs_free", False):
        app_rows.append(
            ["Listed fee-paying programs (net tuition > 0)", fee_def["baseline"], fee_def["policy"], f"{fee_def['delta']:+d}", _fmt_signed_pct(fee_def["pct_change"])]
        )
    app_rows.extend([
        [f"Listed in top {top_k_n} choices", tk["baseline"], tk["policy"], f"{tk['delta']:+d}", _fmt_signed_pct(tk["pct_change"])],
        ["Eligible applicants", defs["eligible_applicants"]["baseline"], defs["eligible_applicants"]["policy"], f"{defs['eligible_applicants']['delta']:+d}", _fmt_signed_pct(defs["eligible_applicants"]["pct_change"])],
        ["First choice (#1 preference)", fc["baseline"], fc["policy"], f"{fc['delta']:+d}", _fmt_signed_pct(fc["pct_change"])],
        ["Placed (admitted)", pl["baseline"], pl["policy"], f"{pl['delta']:+d}", _fmt_signed_pct(pl["pct_change"])],
    ])
    sections.append(
        StatisticsSection(
            id="application_definitions",
            title="Application & Admission Definitions (Never Conflated)",
            type="table",
            data={
                "columns": ["Definition", "Baseline", "Policy", "Delta", "% Change"],
                "rows": app_rows,
            },
        )
    )

    # 5. Subgroup bar charts (income band + scholarship tier)
    income_rows = analytics["subgroups"].get("income_band", [])
    if income_rows:
        sections.append(
            StatisticsSection(
                id="applicants_by_income",
                title="Applicants by Household Income Band (Baseline vs. Policy)",
                type="bar_series",
                data={
                    "value_label": "Applicants (listed anywhere)",
                    "series": [
                        {"key": "baseline_listed", "label": "Baseline", "slot": "series-1"},
                        {"key": "policy_listed", "label": "Policy", "slot": "series-2"},
                    ],
                    "rows": [
                        {
                            "category": r["group"],
                            "label": str(r["group"]).title(),
                            "values": {"baseline_listed": r["baseline_listed"], "policy_listed": r["policy_listed"]},
                        }
                        for r in income_rows
                    ],
                },
            )
        )

    tier_rows = analytics.get("scholarship_tiers", [])
    if tier_rows:
        sections.append(
            StatisticsSection(
                id="scholarship_tier_breakdown",
                title="Demand & Fill by Scholarship Tier",
                type="table",
                data={
                    "columns": ["Tier", "Programs", "Base Listed", "Policy Listed", "Δ Listed", "Base Filled", "Policy Filled", "Affordability Drops"],
                    "rows": [
                        [
                            t["tier"],
                            t["programs"],
                            t["baseline_listed"],
                            t["policy_listed"],
                            f"{t['listed_delta']:+d}",
                            t["baseline_filled"],
                            t["policy_filled"],
                            t["dropped_due_to_affordability"],
                        ]
                        for t in tier_rows
                    ],
                },
            )
        )

    # 6. Program-level table
    if analytics["programs"]:
        sections.append(
            StatisticsSection(
                id="program_deltas_table",
                title="Targeted Program Breakdown (Applications, Fill & Cutoffs)",
                type="table",
                data={
                    "columns": ["Program", "Tier", "Base Apps", "Policy Apps", "Δ Apps", "1st Choice Δ", "Filled / Cap", "Base Cutoff", "Policy Cutoff", "Cutoff Δ"],
                    "rows": [
                        [
                            f"{p['department_name']} ({p['program_id']})",
                            p["scholarship_tier"],
                            p["baseline_listed_anywhere"],
                            p["policy_listed_anywhere"],
                            f"{p['listed_anywhere_delta']:+d}",
                            f"{p['first_choice_delta']:+d}",
                            f"{p['policy_filled']} / {p['policy_capacity']}",
                            f"{p['baseline_cutoff_score']:.2f}" if p["baseline_cutoff_score"] is not None else "—",
                            f"{p['policy_cutoff_score']:.2f}" if p["policy_cutoff_score"] is not None else "—",
                            f"{p['cutoff_score_delta']:+.2f}" if p["cutoff_score_delta"] is not None else "—",
                        ]
                        for p in analytics["programs"]
                    ],
                },
            )
        )

    # 7. Migration flow summary
    sections.append(
        StatisticsSection(
            id="applicant_migration",
            title="Applicant Migration & Competitor Flow",
            type="flow_summary",
            data={
                "stayed_at_target": mig["stayed_at_target"],
                "shifted_within_target": mig["shifted_within_target"],
                "shifted_to_rival_uni": mig["shifted_to_rival_uni"],
                "primary_or_placed_shifted_to_rival": mig.get("primary_or_placed_shifted_to_rival", 0),
                "dropped_out_of_applying": mig["dropped_out_of_applying"],
                "newly_attracted": mig["newly_attracted"],
                "top_rival_destinations": mig["top_rival_destinations"],
                "top_primary_rival_destinations": mig.get("top_primary_rival_destinations", []),
            },
            caveat="Rival universities remain completely fixed outside options.",
        )
    )

    # 8. Optional Milestone 2 Retention Trajectory
    if university_comparison is not None:
        base_traj = getattr(university_comparison, "baseline_trajectory", None) or (
            university_comparison.get("baseline_trajectory") if isinstance(university_comparison, dict) else None
        )
        pol_traj = getattr(university_comparison, "policy_trajectory", None) or (
            university_comparison.get("policy_trajectory") if isinstance(university_comparison, dict) else None
        )
        if base_traj and pol_traj:
            sections.append(
                StatisticsSection(
                    id="retention_trajectory",
                    title="Multi-Semester Retention Trajectory (CRN Mean)",
                    type="line_series",
                    data={
                        "x_key": "label",
                        "x_label": "Semester",
                        "series": [
                            {"key": "baseline_active", "label": "Baseline Active Students", "slot": "series-1"},
                            {"key": "policy_active", "label": "Policy Active Students", "slot": "series-2"},
                        ],
                        "rows": [
                            {
                                "label": f"Term {b['semester']}",
                                "semester": b["semester"],
                                "baseline_active": b["mean_active_students"],
                                "policy_active": p["mean_active_students"],
                            }
                            for b, p in zip(base_traj, pol_traj)
                        ],
                        "baseline_trajectory": base_traj,
                        "policy_trajectory": pol_traj,
                    },
                    unit="students",
                )
            )

    return [s.model_dump(mode="json") for s in sections]


def summarize_university_query(
    query_spec: Any,
    analytics: dict[str, Any],
    *,
    elasticity_range: dict[str, Any] | None = None,
    variant_summaries: list[dict[str, Any]] | None = None,
    sweep_rows: list[dict[str, Any]] | None = None,
    university_comparison: Any | None = None,
    allow_llm: bool = False,
) -> dict[str, Any]:
    """Build a question-aware executive answer and generic typed detailed statistics."""
    intent = query_spec.intent
    uni_label = query_spec.focus_university_name or "targeted programs"
    if getattr(query_spec, "focus_department_names", None):
        uni_label = f"{uni_label} ({', '.join(query_spec.focus_department_names)})"
    defs = analytics["application_definitions"]
    la = defs["listed_anywhere"]
    fee_la = defs.get("fee_paying_listed")
    tk = defs["listed_top_k"]
    fc = defs["first_choice"]
    pl = defs["placed"]
    cap = analytics["target_capacity"]
    rev = analytics["target_revenue"]
    mig = analytics["migration"]
    cohort_meta = analytics["cohort_metadata"]
    top_k_n = analytics.get("top_k_definition", 3)
    all_free = bool(analytics.get("all_target_programs_free", False))
    fee_lever_active = bool(
        getattr(query_spec.levers, "tuition_change_pct", None)
        or getattr(query_spec.levers, "aid_budget_change_pct", None)
    )

    range_text = ""
    if elasticity_range and "listed_anywhere" in elasticity_range:
        er = elasticity_range["listed_anywhere"]
        range_text = f" (about {er['min']} to {er['max']} across Low/Medium/High price & prestige sensitivities, central {er['central']})"

    fee_range_text = ""
    if elasticity_range and "fee_paying_listed" in elasticity_range:
        fer = elasticity_range["fee_paying_listed"]
        fee_range_text = f" (fee-paying Low/Med/High sensitivity range: {fer['min']} to {fer['max']}, central {fer['central']})"

    ret_note = ""
    if university_comparison is not None:
        pe_ret = university_comparison.policy_effects if hasattr(university_comparison, "policy_effects") else university_comparison["policy_effects"]
        ret_pp_note = round(pe_ret["cumulative_retention_rate"]["mean"] * 100.0, 2)
        drop_d_note = pe_ret["final_withdrawn_dropout"]["mean"]
        ret_note = (
            f" Over {getattr(query_spec.levers, 'semester_count', 4)} semesters on the enrolled target cohort, "
            f"cumulative retention changes by {ret_pp_note:+.2f} pp ({pe_ret['cumulative_retention_rate']['baseline_mean']*100:.2f}% -> "
            f"{pe_ret['cumulative_retention_rate']['policy_mean']*100:.2f}%) with {drop_d_note:+.2f} final dropouts."
        )

    # Intent-specific headline & direct answer
    if intent == "ranking_sensitivity" and variant_summaries:
        parts = [f"{v['label']}: {v['listed_anywhere']} listed ({v['first_choice']} 1st-choice, {v['placed']} placed)" for v in variant_summaries]
        headline = f"Exogenous ranking sensitivity for {uni_label}: " + " | ".join(parts) + "."
        direct_answer = (
            f"Using 'listed anywhere' on the preference list as the application metric (out of {cohort_meta['sample_size']} synthetic candidates), "
            + "; ".join(parts)
            + ". Higher ranking increases applicant demand and post-placement cutoffs, while lower ranking reduces both."
        )
    elif intent == "multi_scenario_compare" and variant_summaries:
        parts = [
            f"{v['label']}: {v['listed_anywhere']} total"
            + (f" ({v['fee_paying_listed']} fee-paying" if not all_free and "fee_paying_listed" in v else " (")
            + (", " if not all_free and "fee_paying_listed" in v else "")
            + f"{v['placed']} placed, {v['target_net_revenue']:,.0f} TL net rev)"
            for v in variant_summaries
        ]
        headline = f"Multi-scenario comparison for {uni_label}: " + " | ".join(parts) + "."
        direct_answer = (
            f"Comparing variants for {uni_label} across {cohort_meta['sample_size']} CRN-matched candidates: "
            + "; ".join(parts)
            + "."
        )
        if fee_la is not None and not all_free:
            direct_answer += f" Fee-paying program applications in the primary evaluated variant move {fee_la['baseline']} -> {fee_la['policy']} ({fee_la['delta']:+d})."
    elif intent == "revenue_tradeoff":
        best_row = max(sweep_rows, key=lambda r: r["target_net_revenue"]) if sweep_rows else None
        if best_row is not None:
            headline = (
                f"Tuition revenue trade-off for {uni_label}: net revenue moves from {rev['baseline']:,.0f} TL to {rev['policy']:,.0f} TL "
                f"({rev['delta']:+,.0f} TL / {_fmt_signed_pct(rev['pct_change'])}); sweep peak is {best_row['target_net_revenue']:,.0f} TL at {best_row['tuition_change_pct']:+g}%."
            )
            direct_answer = (
                f"At {uni_label}, the evaluated policy changes net tuition revenue by {rev['delta']:+,.0f} TL ({_fmt_signed_pct(rev['pct_change'])}) "
                f"as total applicants move {la['baseline']} -> {la['policy']}"
                + (
                    f" (fee-paying applicants {fee_la['baseline']} -> {fee_la['policy']})"
                    if fee_la is not None and not all_free
                    else ""
                )
                + f" and admitted students move {pl['baseline']} -> {pl['policy']}. "
                f"Across the tested tuition grid, net revenue peaks at {best_row['tuition_change_pct']:+g}% ({best_row['target_net_revenue']:,.0f} TL)."
            )
        else:
            headline = f"Net tuition revenue at {uni_label} changes from {rev['baseline']:,.0f} TL to {rev['policy']:,.0f} TL ({rev['delta']:+,.0f} TL)."
            direct_answer = headline
    elif intent == "retention_impact" and university_comparison is not None:
        pe = university_comparison.policy_effects if hasattr(university_comparison, "policy_effects") else university_comparison["policy_effects"]
        ret_pp = round(pe["cumulative_retention_rate"]["mean"] * 100.0, 2)
        drop_d = pe["final_withdrawn_dropout"]["mean"]
        headline = (
            f"Multi-semester retention impact for {uni_label}: retention changes by {ret_pp:+.2f} pp "
            f"with {drop_d:+.2f} final dropouts."
        )
        direct_answer = (
            f"Across {pe['cumulative_retention_rate']['policy_mean']*100:.2f}% policy vs {pe['cumulative_retention_rate']['baseline_mean']*100:.2f}% baseline retention "
            f"for {uni_label}'s enrolled students, cumulative retention changes by {ret_pp:+.2f} percentage points and final dropout changes by {drop_d:+.2f} students."
        )
    elif intent in ("cutoff_impact", "quota_capacity", "placement_fill"):
        cut_diffs = [p["cutoff_score_delta"] for p in analytics["programs"] if p["cutoff_score_delta"] is not None]
        avg_cut = round(sum(cut_diffs) / len(cut_diffs), 2) if cut_diffs else 0.0
        headline = (
            f"{uni_label}: filled seats move {cap['baseline_filled']} -> {cap['policy_filled']} "
            f"(fill rate {cap['baseline_fill_rate']*100:.1f}% -> {cap['policy_fill_rate']*100:.1f}%), "
            f"with mean cutoff score shift {avg_cut:+.2f}."
        )
        direct_answer = (
            f"Under this scenario at {uni_label}, total capacity shifts from {cap['baseline']} to {cap['policy']} seats and filled seats shift from "
            f"{cap['baseline_filled']} to {cap['policy_filled']} ({cap['policy_fill_rate']*100:.1f}% utilization). "
            f"Applicants (listed anywhere) move from {la['baseline']} to {la['policy']} ({la['delta']:+d})."
        )
    elif intent == "competitor_flow":
        top_r = mig["top_rival_destinations"][0] if mig["top_rival_destinations"] else None
        top_p_r_list = mig.get("top_primary_rival_destinations") or []
        top_p_r = top_p_r_list[0] if top_p_r_list else None
        top_r_txt = f" Top rival destination: {top_r['university_name']} ({top_r['count']} applicants)." if top_r else (
            f" Top rival gaining shifted #1/admitted choices: {top_p_r['university_name']} ({top_p_r['count']} candidates)."
            if top_p_r
            else ""
        )
        prim_shift = mig.get("primary_or_placed_shifted_to_rival", 0)
        headline = (
            f"Applicant migration at {uni_label}: {mig['shifted_to_rival_uni']} left {uni_label} entirely for rivals, "
            f"{prim_shift} shifted primary/admitted choice to rivals, "
            f"{mig['dropped_out_of_applying']} dropped out of applying."
        )
        direct_answer = (
            f"Of baseline applicants to {uni_label}, {mig['stayed_at_target']} kept the same application pattern, "
            f"{mig['shifted_within_target']} shifted within {uni_label}, {mig['shifted_to_rival_uni']} moved completely to fixed rival universities, "
            f"{prim_shift} shifted their #1 or placed destination to rivals, and {mig['dropped_out_of_applying']} dropped out.{top_r_txt}"
        )
    elif all_free and fee_lever_active:
        headline = (
            f"All targeted programs at {uni_label} are tuition-free (0 TL baseline); applicants remain {la['baseline']} -> {la['policy']} (+0)."
        )
        direct_answer = (
            f"Note: All targeted programs at {uni_label} currently have 0 TL annual tuition (state or 100% scholarship), so percentage tuition/aid scaling leaves net tuition at 0 TL. "
            f"Defining 'apply' as listing {uni_label} anywhere on the preference list (out of {cohort_meta['sample_size']} candidates), total applicants remain {la['policy']}."
        )
    elif fee_la is not None and not all_free and la["delta"] == 0 and fee_la["delta"] != 0:
        headline = (
            f"Fee-paying applicants to {uni_label} move {fee_la['baseline']} -> {fee_la['policy']} ({fee_la['delta']:+d} / {_fmt_signed_pct(fee_la['pct_change'])}); "
            f"total unique applicants (including 100% Burslu) stay {la['baseline']} -> {la['policy']}."
        )
        direct_answer = (
            f"Defining 'apply' as listing {uni_label} anywhere in the preference list (out of {cohort_meta['sample_size']} synthetic candidates), "
            f"candidates continue listing the tuition-exempt 100% Burslu program so overall 'listed anywhere' stays at {la['policy']}; "
            f"however, applicants to fee-paying programs (net tuition > 0 TL) shift from {fee_la['baseline']} to {fee_la['policy']} ({fee_la['delta']:+d}, {_fmt_signed_pct(fee_la['pct_change'])}){fee_range_text}. "
            f"Top-{top_k_n} preferences move {tk['baseline']} -> {tk['policy']}, 1st-choice applications move {fc['baseline']} -> {fc['policy']}, and placed students move {pl['baseline']} -> {pl['policy']}."
        )
    else:
        headline = (
            f"Estimated applicants to {uni_label} (listed anywhere): {la['baseline']} -> {la['policy']} "
            f"({la['delta']:+d} / {_fmt_signed_pct(la['pct_change'])}){range_text}."
        )
        direct_answer = (
            f"Defining 'apply' as listing {uni_label} anywhere in the candidate's preference list (out of {cohort_meta['sample_size']} synthetic candidates), "
            f"applications change from {la['baseline']} to {la['policy']} ({la['delta']:+d}, {_fmt_signed_pct(la['pct_change'])}){range_text}. "
            + (
                f"Fee-paying program applicants move {fee_la['baseline']} -> {fee_la['policy']} ({fee_la['delta']:+d}). "
                if fee_la is not None and not all_free
                else ""
            )
            + f"Top-{top_k_n} preferences move {tk['baseline']} -> {tk['policy']}, 1st-choice applications move {fc['baseline']} -> {fc['policy']}, "
            f"and placed (admitted) students move {pl['baseline']} -> {pl['policy']}."
        )

    if ret_note and intent != "retention_impact":
        direct_answer = direct_answer.rstrip() + ret_note

    # Key findings tailored to drivers
    income_rows = analytics["subgroups"].get("income_band", [])
    income_driver = ""
    if income_rows:
        worst = min(income_rows, key=lambda r: r["listed_delta"])
        income_driver = (
            f"Largest income-group shift: {worst['group']} income band ({worst['baseline_listed']} -> {worst['policy_listed']}, "
            f"{worst['listed_delta']:+d} listed)."
        )

    tier_rows = analytics.get("scholarship_tiers", [])
    tier_driver = ""
    if tier_rows:
        burslu = next((t for t in tier_rows if "100%" in t["tier"]), None)
        paid = next((t for t in tier_rows if "Full Fee" in t["tier"]), None)
        disc = next((t for t in tier_rows if "50%" in t["tier"]), None)
        if burslu and (paid or disc):
            parts_t = [f"100% Burslu {burslu['baseline_listed']} -> {burslu['policy_listed']} ({burslu['listed_delta']:+d})"]
            if disc:
                parts_t.append(f"50% Discount {disc['baseline_listed']} -> {disc['policy_listed']} ({disc['listed_delta']:+d})")
            if paid:
                parts_t.append(f"Full-Fee (Ücretli) {paid['baseline_listed']} -> {paid['policy_listed']} ({paid['listed_delta']:+d})")
            tier_driver = "Scholarship tier contrast: " + " vs ".join(parts_t) + "."

    key_findings = [
        f"Listed anywhere: {la['baseline']} -> {la['policy']} ({la['delta']:+d}); "
        + (f"Fee-paying programs: {fee_la['baseline']} -> {fee_la['policy']} ({fee_la['delta']:+d}); " if fee_la is not None and not all_free else "")
        + f"Top-{top_k_n}: {tk['baseline']} -> {tk['policy']} ({tk['delta']:+d}); 1st choice: {fc['baseline']} -> {fc['policy']} ({fc['delta']:+d}); Placed: {pl['baseline']} -> {pl['policy']} ({pl['delta']:+d}).",
    ]
    if elasticity_range and "listed_anywhere" in elasticity_range:
        er = elasticity_range["listed_anywhere"]
        fer = elasticity_range.get("fee_paying_listed")
        fer_txt = f"; fee-paying range {fer['min']} to {fer['max']} (central {fer['central']})" if (fer and not all_free) else ""
        key_findings.append(
            f"Elasticity sensitivity range (uncalibrated Low/Medium/High presets): total listed range from {er['min']} to {er['max']} (central {er['central']}){fer_txt}. Result depends strongly on assumed price/prestige sensitivity."
        )
    if ret_note and intent != "retention_impact":
        key_findings.append(ret_note.strip())
    if income_driver:
        key_findings.append(income_driver)
    if tier_driver:
        key_findings.append(tier_driver)
    key_findings.append(
        f"Migration: {mig['shifted_to_rival_uni']} shifted to fixed rivals, {mig['dropped_out_of_applying']} dropped out, {mig['newly_attracted']} newly attracted."
    )

    caveats = [
        "Uncalibrated behavioral elasticities (coefficients_calibrated=false): price and prestige responses are synthetic assumptions, not fitted to empirical applicant microdata.",
        "Rivals stay fixed: rival universities do not change tuition, quotas, or rankings in response.",
        f"Simplified/hypothetical placement rules (osym_verified=false): Cohort size={cohort_meta['sample_size']}, seed={cohort_meta['seed']}, reporting_basis={cohort_meta['reporting_basis']} (scale_factor={cohort_meta['cohort_scale_factor']}).",
        "Application definitions are reported separately ('listed anywhere', 'top-k', '1st choice', 'placed') and never conflated.",
    ]
    if cohort_meta.get("quota_scale_factor", 1.0) < 1.0:
        caveats.append(
            f"Sample-congested quotas (quota_scale_factor={cohort_meta['quota_scale_factor']}): program seat capacities are proportionally scaled to cohort size (floor 1 seat/open program) so competitive quotas bind."
        )
    if cohort_meta.get("empirical_priors_active"):
        caveats.append(
            "Scores and provincial origins are drawn from aggregate ÖSYM cumulative score distributions (2026) and YÖK Ankara mobility flows; household budgets remain synthetic assumptions."
        )

    sections = _build_query_sections(
        query_spec,
        analytics,
        elasticity_range=elasticity_range,
        variant_summaries=variant_summaries,
        sweep_rows=sweep_rows,
        university_comparison=university_comparison,
    )

    md_lines = [
        f"# University Query Summary: {uni_label}",
        "",
        f"**Question:** {query_spec.original_prompt}",
        f"**Intent:** `{intent}` | **Simulation Mode:** `{query_spec.simulation_mode}`",
        "",
        "## Direct Answer",
        direct_answer,
        "",
        "## Key Findings",
        *[f"- {kf}" for kf in key_findings],
        "",
        "## Caveats & Methodological Disclosures",
        *[f"- {cv}" for cv in caveats],
    ]

    assumptions_out = [a.model_dump(mode="json") for a in getattr(query_spec, "assumptions", [])]
    generated_by = "deterministic"

    # Optional gated LLM narrative enhancement strictly verified against computed numbers
    if allow_llm and os.environ.get("OPENAI_API_KEY"):
        try:
            from openai import OpenAI  # type: ignore

            grounding_payload = {
                "question": query_spec.original_prompt,
                "intent": intent,
                "levers": query_spec.levers.model_dump(mode="json", exclude_none=True),
                "application_definitions": defs,
                "elasticity_range": elasticity_range,
                "target_capacity": cap,
                "target_revenue": rev,
                "migration": mig,
                "cohort_metadata": cohort_meta,
            }
            allowed_nums: set[float] = {1.0, float(top_k_n)}
            _collect_grounding_numbers(grounding_payload, allowed_nums)
            for pm in re.findall(r"([+-]?\d+(?:\.\d+)?)", query_spec.original_prompt):
                try:
                    allowed_nums.add(float(pm))
                except ValueError:
                    pass
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            resp = client.chat.completions.create(
                model=os.environ.get("SOCIETYTWIN_SUMMARY_MODEL", "gpt-4o-mini").split("/")[-1],
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize the verified simulation JSON into a concise JSON with keys "
                            "'headline', 'direct_answer', 'key_findings' (list of strings). "
                            "CRITICAL: Use ONLY exact numbers present in the JSON. Never invent, extrapolate, or alter any number."
                        ),
                    },
                    {"role": "user", "content": json.dumps(grounding_payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw_content = resp.choices[0].message.content
            if raw_content:
                parsed = json.loads(raw_content)
                cand_texts = [
                    str(parsed.get("headline", "")),
                    str(parsed.get("direct_answer", "")),
                    *[str(x) for x in parsed.get("key_findings", [])],
                ]
                if parsed.get("headline") and parsed.get("direct_answer") and _llm_numbers_grounded(cand_texts, allowed_nums):
                    headline = str(parsed["headline"])
                    direct_answer = str(parsed["direct_answer"])
                    if parsed.get("key_findings"):
                        key_findings = [str(x) for x in parsed["key_findings"]]
                    generated_by = "llm_grounded"
        except Exception as exc:
            logger.debug("University LLM summary skipped/rejected: %s", exc)

    return {
        "title": f"University Simulation: {uni_label}",
        "headline": headline,
        "direct_answer": direct_answer,
        "key_findings": key_findings,
        "summary_markdown": "\n".join(md_lines),
        "detailed_statistics": sections,
        "assumptions": assumptions_out,
        "caveats": caveats,
        "generated_by": generated_by,
    }
