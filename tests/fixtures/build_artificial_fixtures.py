"""Write the small, clearly artificial experiment fixture used by CI.

Everything produced here is invented for tests: the province TESTLAND, the year 2099, the IDs
TST2099_*, every count, the model name and every answer. Run from the repository root:

    python tests/fixtures/build_artificial_fixtures.py

The output is committed; tests never regenerate it.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "artificial_experiment"
AGE_GROUPS = [f"{a}-{a + 4}" for a in range(0, 90, 5)] + ["90+"]
UNDER_15 = {"0-4", "5-9", "10-14"}
STATUSES = ["Hiç evlenmedi", "Evli", "Boşandı", "Eşi öldü"]
PROVINCE, YEAR = "TESTLAND", 2099
MODEL = "fakeprov/artificial-model"


def write(rel: str, text: str) -> Path:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def wjson(rel: str, payload) -> None:
    write(rel, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crlf_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\n", b"\r\n")).hexdigest()


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    write("README.md", "# Artificial test fixture\n\nEverything in this folder is invented for automated tests "
          "(province TESTLAND, year 2099, IDs TST2099_*). It mirrors the layout of experiments/matraix_simulation "
          "and contains no real or official data. Regenerate with tests/fixtures/build_artificial_fixtures.py.\n")
    wjson("layout.json", {
        "base_population": "synthetic/testland_population_base.csv",
        "v2_population": "synthetic/testland_population_v2.csv",
        "age_gender": "processed/testland_age_gender.csv",
        "marital_gender": "processed/testland_marital_gender.csv",
        "controls": "processed/testland_controls.csv",
        "fixture_kind": "artificial_test_fixture",
    })
    # Reference table: invented counts with exact probabilities.
    counts = {(age, g): 10 + i * 3 + (j * 2) for i, age in enumerate(AGE_GROUPS) for j, g in enumerate(("male", "female"))}
    total = sum(counts.values())
    lines = ["year,province,age_group,gender,population,probability"]
    for age in AGE_GROUPS:
        for g in ("female", "male"):
            lines.append(f"{YEAR},{PROVINCE},{age},{g},{counts[age, g]},{counts[age, g] / total!r}")
    age_path = write("processed/testland_age_gender.csv", "\n".join(lines) + "\n")
    marital = {"female": [40, 90, 15, 25], "male": [55, 95, 10, 5]}
    lines = ["year,province,gender,marital_status,population,conditional_probability"]
    for g in ("female", "male"):
        denom = sum(marital[g])
        for status, n in zip(STATUSES, marital[g]):
            lines.append(f"{YEAR},{PROVINCE},{g},{status},{n},{n / denom!r}")
    marital_path = write("processed/testland_marital_gender.csv", "\n".join(lines) + "\n")
    male = sum(v for (a, g), v in counts.items() if g == "male")
    female = total - male
    write("processed/testland_controls.csv", "\n".join([
        "year,province,statistic,value,unit,source_workbook,source_sheet,source_row",
        f"{YEAR},{PROVINCE},female_population,{female},persons,artificial_workbook_a.xls,t1,5",
        f"{YEAR},{PROVINCE},male_population,{male},persons,artificial_workbook_a.xls,t1,5",
        f"{YEAR},{PROVINCE},total_population,{total},persons,artificial_workbook_a.xls,t1,5",
        f"{YEAR - 1},{PROVINCE},total_median_age,33.5,years,artificial_workbook_b.xls,t2,7",
        f"{YEAR - 1},{PROVINCE},total_median_age,33.5,years,older/artificial_workbook_b.xls,t2,7",
    ]) + "\n")
    # Population: 40 invented residents.
    rng = random.Random(2099)
    cells = list(counts)
    rows = []
    for i in range(1, 41):
        age, g = rng.choices(cells, weights=[counts[c] for c in cells])[0]
        if i == 1:
            age, g = "45-49", "female"
        if i == 2:
            age, g = "80-84", "female"
        if i == 3:
            age, g = "0-4", "male"
        rows.append((f"TST2099_{i:06d}", age, g))
    write("synthetic/testland_population_base.csv",
          "person_id,age_group,gender\n" + "".join(f"{p},{a},{g}\n" for p, a, g in rows))
    v2 = []
    for p, a, g in rows:
        status = "not_applicable" if a in UNDER_15 else rng.choice(STATUSES)
        if p == "TST2099_000001":
            status = "Evli"
        if p == "TST2099_000002":
            status = "Eşi öldü"
        v2.append((p, a, g, status))
    v2_path = write("synthetic/testland_population_v2.csv",
                    "person_id,age_group,gender,marital_status,marital_status_conditioning\n"
                    + "".join(f"{p},{a},{g},{s},gender_only\n" for p, a, g, s in v2))
    # Static stubs: only literal constants are read (never executed).
    write("src/synthetic_population/generate_population.py",
          '"""Artificial stub for tests; never executed. Only the SEED constant is read statically."""\nSEED = 7\n')
    write("src/persona_adapter/build_matraix_persona.py",
          '"""Artificial stub for tests; never executed."""\n'
          'SOURCE_FIELDS = ["person_id", "age_group", "gender", "marital_status", "marital_status_conditioning"]\n'
          'PROMPT_VISIBLE_ALLOWLIST = frozenset({"age_bracket", "demo_marital_status", "dst_age_group"})\n'
          'MARITAL_MAPPING = {"Evli": "Married", "Bo\\u015fand\\u0131": "Divorced", "E\\u015fi \\u00f6ld\\u00fc": "Widowed"}\n')
    write("src/runtime/run_matraix_ab.py",
          '"""Artificial stub for tests; never executed."""\n'
          'EXPECTED_IDS = ("TST2099_000001", "TST2099_000002")\n'
          'KEYS = {"fakeprov": ("FAKEPROV_API_KEY",), "otherprov": ("OTHERPROV_API_KEY",)}\n')
    write("src/runtime/run_matraix_smoke.py", '"""Artificial stub for tests; never executed."""\n')

    def persona(pid: str, row: int, age: str, status: str, mapped: str, bracket: str) -> str:
        return (
            f"persona_id: {pid}\nversion: '1.0'\nsource: synthetic\ndimensions:\n"
            f"  dst_residence_province: {PROVINCE}\n  dst_age_group: {age}\n  dst_reference_year: '{YEAR}'\n"
            f"  age_bracket: {bracket}\n  demo_marital_status: {mapped}\n"
            "metadata:\n"
            "  source_population: synthetic/testland_population_v2.csv\n"
            f"  source_sha256: {crlf_sha(v2_path)}\n  source_csv_row: {row}\n"
            f"  source_attributes:\n    person_id: {pid}\n    age_group: {age}\n    gender: female\n"
            f"    marital_status: {status}\n    marital_status_conditioning: gender_only\n"
            f"  reference_year: {YEAR}\n  province: {PROVINCE}\n  generation_seed: 7\n"
            "  seed_provenance: artificial\n  catalog_path: ARTIFICIAL/dimensions.json\n"
            f"  catalog_sha256: {'0' * 64}\n"
            "  processed_sources:\n"
            f"    testland_age_gender.csv:\n      path: processed/testland_age_gender.csv\n      sha256: {crlf_sha(age_path)}\n"
            f"    testland_marital_gender.csv:\n      path: processed/testland_marital_gender.csv\n      sha256: {sha(marital_path)}\n"
            "  field_provenance:\n"
            "    persona_id: {source_field: person_id, source_value: X, source_type: synthetic_identifier, method: identity}\n"
            "    dst_age_group: {source_field: age_group, source_type: sampled_observed_distribution, method: identity}\n"
            "    dst_residence_province: {source_field: province, source_type: sampled_observed_distribution, method: join}\n"
            "    dst_reference_year: {source_field: year, source_type: sampled_observed_distribution, method: join}\n"
            "    age_bracket: {source_field: age_group, source_type: sampled_observed_distribution, method: contained}\n"
            "    demo_marital_status: {source_field: marital_status, source_type: statistically_inferred, dataset: T10, method: translation}\n"
            "  prompt_visible_fields: [age_bracket, demo_marital_status, dst_age_group, dst_reference_year, dst_residence_province]\n"
            "  unassigned_fields: [gender_identity, education, exact_age]\n"
        )
    pa = write("personas/persona_a.yaml", persona("TST2099_000001", 2, "45-49", "Evli", "Married", "45-54"))
    pb = write("personas/persona_b.yaml", persona("TST2099_000002", 3, "80-84", "Eşi öldü", "Widowed", "75-84"))

    questionnaire = (
        "# Artificial Survey\n\nUse exact `questionId` and valid choice ids.\n\n"
        "## q_pick\n\nPrompt: Pick an invented option.\n\n- Construct: `artificial`\n- Type: `single_choice`\n- Required: `true`\n\n"
        "| choice_id | label |\n|-----------|-------|\n| `opt_a` | Invented option A. |\n| `opt_b` | Invented option B. |\n\n"
        "## q_scale\n\nPrompt: Rate this invented thing.\n\n- Construct: `artificial_scale`\n- Type: `likert`\n- Required: `true`\n- Scale: `1`-`5`\n\n"
        "## q_beta\n\nPrompt: Invented yes/no.\n\n- Type: `single_choice`\n\n| choice_id | label |\n|-----------|-------|\n"
        "| `true` | Invented yes. |\n| `false` | Invented no. |\n\n## Answer envelope\n\nIgnored section.\n"
    )
    prompts = {"A": ("You are persona-TST2099_000001. Artificial system prompt.", "Artificial task prompt."),
               "B": ("You are persona-TST2099_000002. Artificial system prompt.", "Artificial task prompt.")}
    answers = {"A": [{"questionId": "q_pick", "value": "opt_a"}, {"questionId": "q_scale", "value": 4},
                     {"questionId": "q_beta", "value": "true"}, {"questionId": "q_unlisted", "value": "mystery_code"}],
               "B": [{"questionId": "q_pick", "value": "opt_a"}, {"questionId": "q_scale", "value": 2},
                     {"questionId": "q_beta", "value": "false"}, {"questionId": "q_unlisted", "value": "mystery_code"}]}
    usage = {"A": {"n_input_tokens": 100, "n_output_tokens": 20, "cost_usd": 0.0001, "request_id": "artificial-a",
                   "model": "artificial-model", "provider": "fakeprov", "cost_source": "estimated"},
             "B": {"n_input_tokens": 101, "n_output_tokens": 21, "cost_usd": 0.0002, "request_id": "artificial-b",
                   "model": "artificial-model", "provider": "fakeprov", "cost_source": "estimated"}}
    persona_files = {"A": pa, "B": pb}
    persona_ids = {"A": "TST2099_000001", "B": "TST2099_000002"}

    def preflight(run: str, labels=("A", "B")):
        wjson(f"runs/{run}/preflight.json", {
            "status": "prepared", "model": MODEL, "temperature": 0, "provider": "fakeprov",
            "required_env_any_of": ["FAKEPROV_API_KEY"], "credentials_present": True,
            "task": "application/tasks/example-survey_product-feedback", "calls_planned": 2, "automatic_retries": 0,
            "max_output_tokens_per_call": None, "expected_answer_count": 4,
            "trials": [{"label": l, "persona_id": persona_ids[l], "path": f"C:\\Users\\someone\\{persona_files[l].name}",
                        "sha256": sha(persona_files[l]), "dimensions": {}, "system": prompts[l][0], "user": prompts[l][1],
                        "estimated_input_tokens_chars_div_4": 20} for l in labels],
            "limitations": ["Artificial limitation text."]})

    def trial(run: str, label: str, status: str, with_result: bool, coerced=None):
        base = f"runs/{run}/trial_{label}"
        write(f"{base}/questionnaire.md", questionnaire)
        write(f"{base}/artifacts/app/input/persona.yaml", persona_files[label].read_text(encoding="utf-8"))
        boundary = {"mode": "live", "model": MODEL, "temperature": 0, "system": prompts[label][0],
                    "user": prompts[label][1], "status": status}
        events = [{"type": "instruction", "markdown": "artificial"}, {"type": "prompts", "prompts": ["x"]}, {"type": "phase", "phase": "answering"}]
        if status == "response_received":
            boundary.update(response={"answers": answers[label]}, coerced_answers=coerced or [], usage=usage[label])
            events += [{"type": "usage", "usage": usage[label]}, {"type": "done", "result": {}}]
        wjson(f"{base}/model_boundary.json", boundary)
        write(f"{base}/events.jsonl", "".join(json.dumps(e) + "\n" for e in events))
        if with_result:
            wjson(f"{base}/artifacts/app/output/survey_result.json",
                  {"instrument": {"id": "artificial_v1", "title": "Artificial Survey"},
                   "answers": [dict(a, rationale="", confidence=None) for a in answers[label]],
                   "trajectory": [], "usage": usage[label]})

    # Completed A/B.
    preflight("ab_complete")
    trial("ab_complete", "A", "response_received", True, [{"questionId": "q_beta", "original": True, "recorded": "true"}])
    trial("ab_complete", "B", "response_received", True)
    rows_cmp = []
    for qa, qb in zip(answers["A"], answers["B"]):
        rows_cmp.append({"question_id": qa["questionId"], "prompt": "artificial", "answer_a": dict(qa, rationale="", confidence=None),
                         "answer_b": dict(qb, rationale="", confidence=None), "value_differs": qa["value"] != qb["value"]})
    wjson("runs/ab_complete/comparison.json", {
        "status": "completed", "model": MODEL, "temperature": 0, "calls": 2, "trials": [],
        "answers_compared": rows_cmp, "differing_values": sum(r["value_differs"] for r in rows_cmp),
        "usage": {"n_input_tokens": 201, "n_output_tokens": 41, "n_cache_tokens": None, "cost_usd": 0.0003},
        "runtime_seconds": 1.5, "limitations": ["Artificial limitation text."]})
    wjson("runs/ab_complete/_matraix_budget.json", {"spent_usd": 0.0003, "max_cost_usd": None})
    write("runs/ab_complete/persona_A_report.md", "# Artificial report\n\n<script>alert('x')</script>\n\nNot billed on a free-tier key.\n")
    # Fake smoke.
    write("runs/smoke_fake/trial_001/questionnaire.md", questionnaire)
    write("runs/smoke_fake/trial_001/artifacts/app/input/persona.yaml", pa.read_text(encoding="utf-8"))
    wjson("runs/smoke_fake/trial_001/artifacts/app/output/survey_result.json",
          {"instrument": {"id": "artificial_v1", "title": "Artificial Survey"}, "answers": answers["B"], "trajectory": []})
    wjson("runs/smoke_fake/model_boundary.json", {"mode": "fake", "provider_calls": 0, "calls": [
        {"system": prompts["A"][0], "user": prompts["A"][1], "response": {"answers": answers["B"]}}]})
    wjson("runs/smoke_fake/smoke_report.json", {"ok": True, "model_mode": "fake", "logical_calls": 1, "provider_calls": 0,
                                                "answered_questions": 4, "limitations": ["Artificial fake transport."]})
    # Partial: A completed, B started without response.
    preflight("partial")
    trial("partial", "A", "response_received", True)
    trial("partial", "B", "request_started", False)
    # Only a started request.
    preflight("started_only")
    trial("started_only", "A", "request_started", False)
    # Only a preflight.
    preflight("prepared_only")
    # Malformed JSON evidence.
    write("runs/malformed/preflight.json", "{not json")
    write("runs/malformed/trial_A/model_boundary.json", "[1, 2")
    # Not a runner layout.
    write("runs/unrecognized/notes.md", "Artificial notes only.\n")
    print(f"Wrote artificial fixture to {ROOT}")


if __name__ == "__main__":
    main()
