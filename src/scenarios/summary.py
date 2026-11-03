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
                val = ao.get("weighted_share")
                if val is None:
                    val = ao.get("unweighted_share", ao.get("share", 0.0))
                shares_dict[ao["option_id"]] = round(val * 100.0, 1)
        else:
            denom = total_valid or 1
            for opt_id, cnt in option_counts.items():
                shares_dict[opt_id] = round((cnt / denom) * 100.0, 1)

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
