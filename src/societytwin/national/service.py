"""Application service for the national pipeline. The API calls this; business rules live in the domain modules.

Flow: controls -> population (generate/load) -> cohort definition -> cohort sample -> personas
-> experiment definition -> reviewed plan (counts, calls, cost, warnings, blockers) -> run -> responses -> aggregates.
"""

from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path

from societytwin.common import canonical_hash, new_id, redact, sha256_bytes, utc_now
from societytwin.errors import conflict, invalid, not_found, unavailable
from societytwin.national import GENERATOR_VERSION
from societytwin.national import geography as geo
from societytwin.national.cohorts import (CohortDefinitionRequest, CohortSampleRequest, SamplingError, definition_hash,
                                          draw)
from societytwin.national.constraints import ADULT_AGE, RULES
from societytwin.national.controls import ControlsError, ControlStore, read_store, write_store
from societytwin.national.dependencies import DEFAULT_REGISTRY_PATH, RegistryError, load_registry
from societytwin.national.environment import coverage_summary, province_environment
from societytwin.national.experiments import (DEFINITION_VERSION, PROMPT_TEMPLATE_VERSION, ExperimentDefinition,
                                              render_prompts, scenario_scope_issues)
from societytwin.national.generator import GenerationConfig, GenerationError, generate
from societytwin.national.model import dependency_graph
from societytwin.national.persona_selection import experiment_persona_builder
from societytwin.national.personas import DEFAULT_VISIBLE, PERSON_FIELDS, TEMPLATE_VERSION, build_persona
from societytwin.national.registry import NationalRegistry
from societytwin.national.results import GROUPABLE, aggregate
from societytwin.national.runner import (RUNNER_VERSION, CallRequest, MatraixBackend, ReplayBackend, StubBackend,
                                         credentials_for, execute, load_prices, provider_env_names)
from societytwin.national.sources import BUILDER_VERSION, build_controls
from societytwin.national.store import PopulationFilter, PopulationStore, distribution, dumps, page, province_breakdown, pyramid
from societytwin.national.validation import ValidationTolerances, summarize, validate
from societytwin.national.vocab import VOCABULARIES, Evidence

SUMMARY_FIELDS = ("age_group", "sex", "marital_status", "education_level", "labour_status", "household_size_class",
                  "household_type", "urbanicity")
STUB_NOTICE = "Stub backend: deterministic placeholder responses for pipeline testing. Not produced by a model; not results."


def code_version(repo_root: Path) -> dict:
    git = repo_root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return {"commit": head, "ref": None, "note": "Detached HEAD. Uncommitted changes are not detected."}
        ref = head[5:]
        path = git / ref
        commit = path.read_text(encoding="utf-8").strip() if path.is_file() else None
        if commit is None and (git / "packed-refs").is_file():
            for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    commit = line.split(" ", 1)[0]
        return {"commit": commit, "ref": ref, "note": "Commit of the checkout; uncommitted changes are not detected."}
    except OSError:
        return {"commit": None, "ref": None, "note": "No git metadata available."}


class NationalService:
    def __init__(self, settings, registry, runtime):
        self.settings = settings
        self.db = NationalRegistry(registry)
        self.runtime = runtime
        self.populations = PopulationStore(settings.populations_dir)
        self._store: tuple[str, ControlStore] | None = None
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()

    # ================================================================ controls
    def store(self) -> ControlStore:
        directory = self.settings.national_controls_dir
        manifest = directory / "manifest.json"
        if not manifest.is_file():
            raise unavailable("controls_not_built", "Control tables have not been built. Build them from the Data Sources page "
                                                    "or run: python -m societytwin.national build-controls")
        signature = sha256_bytes(manifest.read_bytes())
        with self._lock:
            if self._store and self._store[0] == signature:
                return self._store[1]
        try:
            store = read_store(directory)
        except (ControlsError, ValueError, KeyError) as exc:
            raise unavailable("controls_invalid", f"Control tables cannot be read: {exc}") from exc
        with self._lock:
            self._store = (signature, store)
        return store

    def build_controls(self) -> dict:
        try:
            store, report = build_controls(self.settings)
        except ControlsError as exc:
            raise invalid("controls_build_failed", str(exc)) from exc
        manifest = write_store(self.settings.national_controls_dir, store)
        return {"manifest": self._controls_summary(manifest), "adapters": report}

    def _controls_summary(self, manifest: dict) -> dict:
        return {k: manifest[k] for k in ("store_version", "built_at", "row_counts", "fingerprint", "warnings")} | {
            "tables": [t["table_id"] for t in manifest["tables"]], "sources": len(manifest["sources"])}

    def controls_status(self) -> dict:
        try:
            store = self.store()
        except Exception as exc:  # noqa: BLE001 - reported as a status
            code = getattr(exc, "code", "controls_unavailable")
            return {"status": "not_built" if code == "controls_not_built" else "invalid", "detail": getattr(exc, "message", str(exc)),
                    "package_dir_present": self.settings.tuik_package_dir.is_dir(), "builder_version": BUILDER_VERSION}
        tables = []
        for tid, meta in store.tables.items():
            covered = store.provinces_with(tid)
            years = sorted({r.year for r in store.rows if r.table_id == tid})
            tables.append({**meta.as_dict(), "province_coverage": len(covered), "provinces": covered, "years": years,
                           "rows": sum(1 for r in store.rows if r.table_id == tid)})
        indicators = store.indicators()
        domains: dict[str, int] = {}
        for info in indicators.values():
            domains[info["theme"]] = domains.get(info["theme"], 0) + 1
        return {"status": "built", "built_at": store.built_at, "fingerprint": store.fingerprint, "tables": tables,
                "sources": store.sources, "inputs": store.inputs, "warnings": store.warnings[:200],
                "context_indicators": len(indicators), "context_observations": len(store.context),
                "context_domains": dict(sorted(domains.items())),
                "multi_year_observations": sum(1 for c in store.context if c.is_multi_year),
                "projection_observations": sum(1 for c in store.context if c.is_projection),
                "audits": store.audits,
                "package_dir_present": self.settings.tuik_package_dir.is_dir(), "builder_version": BUILDER_VERSION}

    # ================================================================ geography / environment
    def geography(self, reference_year: int = 2025, population_id: str | None = None) -> dict:
        try:
            store = self.store()
            coverage = coverage_summary(store, reference_year)
            status = "built"
        except Exception:  # noqa: BLE001
            coverage = [{**p.as_dict(), "has_population_controls": False, "control_tables": [], "context_indicators": 0}
                        for p in geo.PROVINCES]
            status = "controls_not_built"
        records = {}
        if population_id:
            loaded = self._load(population_id)
            records = {r["province_code"]: r for r in province_breakdown(loaded.table)}
        for c in coverage:
            r = records.get(c["province_code"])
            c["records"] = r["records"] if r else 0
            c["represented_population"] = r["weighted"] if r else None
        return {"classification": geo.CLASSIFICATION, "provinces": coverage, "controls_status": status,
                "provinces_with_population_controls": sum(1 for c in coverage if c["has_population_controls"]),
                "province_count": len(geo.PROVINCES)}

    def environment(self, province_code: str, reference_year: int) -> dict:
        try:
            code = geo.normalize_code(province_code)
        except geo.UnknownProvince as exc:
            raise not_found("unknown_province", str(exc)) from exc
        return province_environment(self.store(), code, reference_year)

    # ================================================================ populations
    def list_populations(self) -> dict:
        items = [self._population_summary(m) for m in self.populations.manifests()]
        return {"items": items, "default_population_id": items[0]["population_id"] if items else None}

    def _population_summary(self, m: dict) -> dict:
        return {"population_id": m["population_id"], "generated_at": m["generated_at"], "reference_year": m["reference_year"],
                "seed": m["seed"], "synthetic_size": m["synthetic_size"],
                "scope": {**{k: v for k, v in m["scope"].items() if k != "excluded"}, "excluded_count": len(m["scope"]["excluded"])},
                "represented_population": m["represented_population"], "generator_version": m["generator_version"],
                "weights": m["weights"], "timings": m.get("timings"), "label": m["label"],
                "controls_fingerprint": m["source_versions"]["controls_fingerprint"]}

    def generate(self, config: GenerationConfig) -> dict:
        store = self.store()
        try:
            registry = load_registry(self.settings.dependency_registry_path or DEFAULT_REGISTRY_PATH)
            pop = generate(store, config, registry=registry)
        except (GenerationError, RegistryError) as exc:
            raise invalid("generation_failed", str(exc)) from exc
        report = validate(pop.columns, pop.manifest, store)
        manifest, created = self.populations.write(pop, report)
        return {"population": self._population_summary(manifest), "created": created,
                "validation_summary": summarize(report)}

    def _load(self, population_id: str):
        try:
            return self.populations.load(population_id)
        except KeyError as exc:
            raise not_found("unknown_population", f"No population {population_id}") from exc
        except ValueError as exc:
            raise conflict("population_changed", str(exc)) from exc

    def population(self, population_id: str) -> dict:
        m = self._load(population_id).manifest
        return {**self._population_summary(m), "excluded_provinces": m["scope"]["excluded"], "allocation": m["allocation"], "calibration": m["calibration"],
                "profiles": m["profiles"], "dependency_model": m["dependency_model"], "constraint_rules": m["constraint_rules"],
                "fields_not_modelled": m["fields_not_modelled"], "source_versions": m["source_versions"],
                "content_sha256": m["content_sha256"], "files": m["files"], "config": m["config"]}

    def summary(self, population_id: str, spec: PopulationFilter) -> dict:
        loaded = self._load(population_id)
        table = loaded.filtered(spec)
        m = loaded.manifest
        return {
            "population_id": population_id, "filters": spec.normalized(), "records": table.num_rows,
            "total_records": loaded.table.num_rows,
            "represented_population": float(sum(table["population_weight"].to_pylist())) if table.num_rows else 0.0,
            "reference_year": m["reference_year"], "provinces": province_breakdown(table),
            "distributions": [distribution(table, f) for f in SUMMARY_FIELDS], "pyramid": pyramid(table),
            "scope": m["scope"], "source_years": _source_years(m, spec.province_codes),
            "weighting": "Weighted counts use population_weight (persons represented). Record shares are unweighted.",
            "label": m["label"],
        }

    def records(self, population_id: str, spec: PopulationFilter, sort: str, direction: str, offset: int, limit: int) -> dict:
        loaded = self._load(population_id)
        table = loaded.filtered(spec)
        try:
            items = page(table, sort, direction, offset, limit)
        except ValueError as exc:
            raise invalid("invalid_page", str(exc)) from exc
        return {"items": items, "total_matching": table.num_rows, "offset": offset, "limit": limit, "sort": sort,
                "direction": direction, "filters": spec.normalized(), "label": loaded.manifest["label"]}

    def record(self, population_id: str, synthetic_id: str, visible_fields: list[str] | None = None) -> dict:
        loaded = self._load(population_id)
        rec = loaded.record(synthetic_id)
        if rec is None:
            raise not_found("unknown_record", f"No record {synthetic_id} in {population_id}")
        try:
            persona = build_persona(rec, loaded.manifest, visible_fields)
        except ValueError as exc:
            raise invalid("invalid_persona_fields", str(exc)) from exc
        profile = loaded.manifest["profiles"][rec["provenance_profile"]]
        return {"record": rec, "persona": persona, "profile": profile,
                "evidence_levels": Evidence.DESCRIPTIONS, "label": loaded.manifest["label"]}

    def validation(self, population_id: str, province_code: str | None = None) -> dict:
        loaded = self._load(population_id)
        report = loaded.validation
        if report is None:
            report = validate(loaded.columns(), loaded.manifest, self.store())
        if province_code:
            code = geo.normalize_code(province_code)
            report = dict(report, provinces=[p for p in report["provinces"] if p["province_code"] == code])
        return json.loads(dumps(report))

    # ================================================================ cohorts
    def preview_cohort(self, population_id: str, spec: PopulationFilter) -> dict:
        loaded = self._load(population_id)
        table = loaded.filtered(spec)
        minors = sum(1 for a in table["age"].to_pylist() if a < ADULT_AGE)
        return {"population_id": population_id, "filters": spec.normalized(), "eligible_records": table.num_rows,
                "eligible_weighted_population": float(sum(table["population_weight"].to_pylist())) if table.num_rows else 0.0,
                "minors": minors, "provinces": province_breakdown(table),
                "distributions": [distribution(table, f) for f in ("sex", "age_group", "marital_status")],
                "note": "Preview only: nothing is saved."}

    def create_cohort(self, request: CohortDefinitionRequest) -> dict:
        preview = self.preview_cohort(request.population_id, request.filters)
        if preview["eligible_records"] == 0:
            raise invalid("empty_cohort", "No records match these filters; a saved cohort must be nonempty.")
        loaded = self._load(request.population_id)
        cohort = {"cohort_id": new_id("cht"), "name": request.name, "description": request.description,
                  "population_id": request.population_id, "population_content_sha256": loaded.manifest["content_sha256"],
                  "filters": request.filters.normalized(), "definition_hash": definition_hash(request.population_id, request.filters),
                  "created_at": utc_now()}
        self.db.insert_cohort(cohort)
        return self.cohort(cohort["cohort_id"])

    def cohort(self, cohort_id: str) -> dict:
        c = self.db.cohort(cohort_id)
        if c is None:
            raise not_found("unknown_cohort", f"No cohort {cohort_id}")
        status, detail, preview = "valid", "The population this cohort was defined on is unchanged.", None
        try:
            loaded = self._load(c["population_id"])
            if loaded.manifest["content_sha256"] != c["population_content_sha256"]:
                status, detail = "population_changed", "The population's content differs from when the cohort was defined."
            else:
                preview = self.preview_cohort(c["population_id"], PopulationFilter(**c["filters"]))
        except Exception as exc:  # noqa: BLE001
            status, detail = "population_unavailable", getattr(exc, "message", str(exc))
        return {**c, "status": status, "status_detail": detail,
                "eligible_records": preview["eligible_records"] if preview else None,
                "eligible_weighted_population": preview["eligible_weighted_population"] if preview else None,
                "minors": preview["minors"] if preview else None,
                "samples": [{k: s[k] for k in ("sample_id", "config", "selected", "created_at")} for s in self.db.samples_for(cohort_id)]}

    def cohorts(self) -> dict:
        items = [self.cohort(c["cohort_id"]) for c in self.db.cohorts()]
        return {"items": items, "total": len(items)}

    def draw_sample(self, cohort_id: str, request: CohortSampleRequest) -> dict:
        c = self.cohort(cohort_id)
        if c["status"] != "valid":
            raise conflict("stale_cohort", c["status_detail"])
        loaded = self._load(c["population_id"])
        table = loaded.filtered(PopulationFilter(**c["filters"]))
        config = request.model_dump()
        config_hash = canonical_hash({"cohort": c["definition_hash"], "population": c["population_content_sha256"], **config})
        existing = self.db.sample_by_config(cohort_id, config_hash)
        if existing:
            return existing
        ids = table["synthetic_id"].to_pylist()
        weights = table["population_weight"].to_pylist()
        strata = table[request.strata_field].to_pylist() if request.strata_field else None
        try:
            result = draw(ids, weights, request, strata)
        except SamplingError as exc:
            raise invalid(exc.code, str(exc)) from exc
        sample = {"sample_id": new_id("smp"), "cohort_id": cohort_id, "population_id": c["population_id"],
                  "config": config, "config_hash": config_hash, **result,
                  "members_sha256": canonical_hash([m["synthetic_id"] for m in result["members"]]), "created_at": utc_now()}
        return self.db.insert_sample(sample)

    def sample(self, sample_id: str) -> dict:
        s = self.db.sample(sample_id)
        if s is None:
            raise not_found("unknown_sample", f"No sample {sample_id}")
        return s

    def sample_personas(self, sample_id: str, offset: int, limit: int, visible_fields: list[str] | None = None) -> dict:
        s = self.sample(sample_id)
        loaded = self._load(s["population_id"])
        members = s["members"][offset:offset + limit]
        personas = []
        for m in members:
            rec = loaded.record(m["synthetic_id"])
            if rec is None:
                continue
            p = build_persona(rec, loaded.manifest, visible_fields)
            personas.append({**{k: p[k] for k in ("persona_id", "synthetic_id", "province_code", "province_name", "model_visible",
                                                  "eligibility", "persona_card_sha256")},
                             "attributes": {a["field"]: a["display"] for a in p["attributes"]},
                             "inclusion_probability": m["inclusion_probability"], "analysis_weight": m["analysis_weight"]})
        return {"sample_id": sample_id, "population_id": s["population_id"], "total": len(s["members"]), "offset": offset,
                "limit": limit, "items": personas, "template_version": TEMPLATE_VERSION}

    # ================================================================ experiments
    def create_experiment(self, definition: ExperimentDefinition) -> dict:
        if self.db.cohort(definition.cohort.cohort_id) is None:
            raise invalid("unknown_cohort", f"No cohort {definition.cohort.cohort_id}")
        if definition.environment.province_code:
            try:
                geo.normalize_code(definition.environment.province_code)
            except geo.UnknownProvince as exc:
                raise invalid("unknown_province", str(exc)) from exc
        if definition.persona.visible_fields is not None:
            bad = [f for f in definition.persona.visible_fields if f not in PERSON_FIELDS]
            if bad:
                raise invalid("invalid_persona_fields", f"Unknown persona fields: {bad}")
        exp = {"experiment_id": new_id("nex"), "definition": definition.model_dump(), "definition_hash": definition.definition_hash(),
               "definition_version": DEFINITION_VERSION, "created_at": utc_now()}
        self.db.insert_experiment(exp)
        return self.experiment(exp["experiment_id"])

    def experiment(self, experiment_id: str) -> dict:
        exp = self.db.experiment(experiment_id)
        if exp is None:
            raise not_found("unknown_experiment", f"No experiment {experiment_id}")
        plans = self.db.plans_for(experiment_id)
        return {**exp, "plans": [{k: p[k] for k in ("plan_hash", "created_at", "blockers", "warnings", "calls", "active_personas")}
                                 for p in plans],
                "runs": [self._run_view(r) for r in self.db.runs(experiment_id)]}

    def experiments(self) -> dict:
        items = []
        for exp in self.db.experiments():
            runs = self.db.runs(exp["experiment_id"])
            items.append({"experiment_id": exp["experiment_id"], "title": exp["definition"]["title"], "created_at": exp["created_at"],
                          "backend": exp["definition"]["model"]["backend"], "transport": exp["definition"]["model"]["transport"],
                          "model": exp["definition"]["model"]["model"], "cohort_id": exp["definition"]["cohort"]["cohort_id"],
                          "sample_size": exp["definition"]["cohort"]["sample_size"],
                          "latest_run": self._run_view(runs[0]) if runs else None, "run_count": len(runs)})
        return {"items": items, "total": len(items)}

    def _definition(self, experiment_id: str) -> tuple[dict, ExperimentDefinition]:
        exp = self.db.experiment(experiment_id)
        if exp is None:
            raise not_found("unknown_experiment", f"No experiment {experiment_id}")
        return exp, ExperimentDefinition(**exp["definition"])

    def _context(self, store: ControlStore | None, code: str, year: int, wanted: list[str]) -> tuple[list[dict], list[str]]:
        if not wanted:
            return [], []
        if store is None:
            return [], [f"Context indicators {wanted} are unavailable: control tables are not built."]
        env = province_environment(store, code, year)
        found = {e["indicator_id"]: e for entries in env["domains"].values() for e in entries}
        out, missing = [], []
        for ind in wanted:
            e = found.get(ind)
            if e and e["value"] is not None and e["value_status"] == "OBSERVED":
                out.append({"indicator_id": ind, "label": e["label"], "value": e["value"], "unit": e["unit"], "source_year": e["source_year"],
                            "source_period": e.get("source_period"), "source_ref": e["source_ref"]})
            else:
                missing.append(ind)
        notes = [f"{geo.province(code).name}: indicator(s) {missing} not available; omitted from the prompt (never invented)."] if missing else []
        return out, notes

    def plan(self, experiment_id: str) -> dict:
        exp, d = self._definition(experiment_id)
        cohort = self.cohort(d.cohort.cohort_id)
        blockers, warnings = [], []

        def block(code, message):
            blockers.append({"code": code, "message": message})

        if cohort["status"] != "valid":
            raise conflict("stale_cohort", cohort["status_detail"])
        sample = self.draw_sample(d.cohort.cohort_id, CohortSampleRequest(size=d.cohort.sample_size, method=d.cohort.sampling_method,
                                                                          seed=d.cohort.seed, strata_field=d.cohort.strata_field))
        loaded = self._load(cohort["population_id"])
        try:
            store = self.store()
        except Exception:  # noqa: BLE001
            store = None
        personas, ctx_notes, prompt_hashes, chars = [], [], [], 0
        first_prompt = None
        minors = 0
        unavailable_counts: dict[str, int] = {}
        ref = d.scenario_ref
        scope_counts: dict[str, int] = {}
        outside_provinces: set[str] = set()
        build_selected = experiment_persona_builder(loaded, d.persona)
        for m in sample["members"]:
            rec = loaded.record(m["synthetic_id"])
            p = build_selected(m["synthetic_id"])
            if not p["eligibility"]["adult"]:
                minors += 1
            for a in p["attributes"]:
                if a["status"] == "unavailable" and (d.persona.visible_fields is None or a["field"] in d.persona.visible_fields) \
                        and a["field"] in DEFAULT_VISIBLE:
                    unavailable_counts[a["field"]] = unavailable_counts.get(a["field"], 0) + 1
            if ref is not None:
                for issue in scenario_scope_issues(ref, rec):
                    scope_counts[issue] = scope_counts.get(issue, 0) + 1
                    if issue == "province_outside_scope":
                        outside_provinces.add(rec["province_code"])
            code = d.environment.province_code or rec["province_code"]
            context, notes = self._context(store, code, loaded.manifest["reference_year"], d.environment.context_indicators)
            ctx_notes.extend(n for n in notes if n not in ctx_notes)
            system, user = render_prompts(d, p, context, geo.province(code).name)
            chars += len(system) + len(user)
            prompt_hashes.append({"synthetic_id": rec["synthetic_id"], "system_sha256": sha256_bytes(system.encode()),
                                  "user_sha256": sha256_bytes(user.encode())})
            if first_prompt is None:
                first_prompt = {"synthetic_id": rec["synthetic_id"], "system": system, "user": user}
            personas.append({"persona_id": p["persona_id"], "synthetic_id": rec["synthetic_id"], "province_code": rec["province_code"],
                             "age_group": rec["age_group"], "sex": rec["sex"], "adult": p["eligibility"]["adult"],
                             "model_visible_fields": p["model_visible_fields"], "analysis_weight": m["analysis_weight"]})
            if d.environment.province_code and rec["province_code"] != d.environment.province_code:
                note = (f"Environment is {geo.province(d.environment.province_code).name}, but some personas live in other provinces.")
                if note not in warnings:
                    warnings.append(note)
        n = len(personas)
        if ref is not None:
            scope = ", ".join(f"{geo.province(c).name} ({c})" for c in ref.province_codes or []) or "any province"
            if scope_counts.get("province_outside_scope"):
                found = ", ".join(f"{geo.province(c).name} ({c})" for c in sorted(outside_provinces))
                block("scenario_province_mismatch",
                      f"Scenario '{ref.scenario_id}' applies to {scope}, but {scope_counts['province_outside_scope']} sampled "
                      f"persona(s) live in {found}. Restrict the cohort to the scenario's provinces.")
            if d.environment.province_code and ref.province_codes and d.environment.province_code not in ref.province_codes:
                block("scenario_environment_mismatch",
                      f"Environment province {d.environment.province_code} is outside scenario '{ref.scenario_id}' scope ({scope}).")
            if scope_counts.get("age_outside_scope"):
                block("scenario_age_mismatch",
                      f"{scope_counts['age_outside_scope']} sampled persona(s) are outside the scenario's age range "
                      f"({ref.minimum_age if ref.minimum_age is not None else 0}-{ref.maximum_age if ref.maximum_age is not None else 'any'}).")
            for missing in ("province_missing", "age_missing"):
                if scope_counts.get(missing):
                    block(f"scenario_{missing}", f"{scope_counts[missing]} sampled persona(s) lack the value needed to check "
                                                 f"scenario scope ({missing.split('_')[0]}); they are never assumed eligible.")
            if ref.unenforced_filters:
                block("scenario_filters_unenforced",
                      f"Scenario '{ref.scenario_id}' targets {ref.unenforced_filters}, which this runtime cannot enforce.")
        planned_calls = n * d.execution.repetitions
        max_calls = planned_calls * d.execution.max_attempts
        if n > self.settings.max_agents_per_run:
            block("too_many_agents", f"{n} active personas exceed this installation's limit of {self.settings.max_agents_per_run} per run.")
        if d.execution.max_calls < planned_calls:
            block("call_cap_below_plan", f"The call cap ({d.execution.max_calls}) is below the {planned_calls} calls needed without retries.")
        elif d.execution.max_calls < max_calls:
            warnings.append(f"Retries can need up to {max_calls} calls; the run stops at the cap of {d.execution.max_calls}.")
        if d.task.adult_only and minors:
            block("minors_in_adult_task", f"{minors} sampled record(s) are under {ADULT_AGE}. Add 'adult_only' (or an age minimum ≥ "
                                          f"{ADULT_AGE}) to the cohort filters; children are never used for adult tasks.")
        backend = d.model.backend
        live = backend == "matraix" and d.model.transport == "live"
        prices = load_prices(self.settings.model_price_table)
        tokens_in = math.ceil(chars / 4) if n else 0
        if backend == "stub":
            cost, cost_basis = 0.0, "No provider calls (stub backend)."
            warnings.append(STUB_NOTICE)
        elif not live:
            cost, cost_basis = 0.0, "No provider calls (MatrAIx fake transport)."
            warnings.append("MatrAIx fake transport: answers are MatrAIx's schema-valid placeholders, identical for every persona.")
        else:
            price = prices.get(d.model.model or "")
            if price:
                cost = (tokens_in * d.execution.repetitions * price["input_per_mtok"]
                        + planned_calls * d.model.max_output_tokens * price["output_per_mtok"]) / 1e6
                cost_basis = (f"Upper bound from the configured price table ({price.get('source', 'source not stated')}, "
                              f"{price.get('as_of', 'date not stated')}): input ≈ characters ÷ 4, output = max_output_tokens per call.")
            else:
                cost, cost_basis = None, "Unknown: no verified price for this model is configured (SOCIETYTWIN_MODEL_PRICES)."
                if d.execution.max_cost_usd is not None:
                    block("cost_cap_unenforceable", "A cost cap is set but the cost cannot be estimated without a configured price table.")
                else:
                    warnings.append("No cost cap and no price table: the provider cost of this run is unknown in advance.")
        if backend == "matraix":
            status = self.runtime.national_status()
            if not status["available"]:
                block("runtime_unavailable", "; ".join(status["reasons"]))
        if live:
            if not self.settings.live_execution_enabled:
                block("live_execution_disabled", "Live provider execution is disabled (SOCIETYTWIN_ENABLE_LIVE_EXECUTION is not set).")
            if not credentials_for(d.model.model):
                block("credentials_missing", f"No key for this provider in the API server's environment ({', '.join(provider_env_names(d.model.model)) or 'unknown provider'}).")
        for field, count in sorted(unavailable_counts.items()):
            warnings.append(f"{field} has no source for {count} of {n} personas; it is not shown to the model for them.")
        profiles = loaded.manifest["profiles"]
        if any(p["fields"].get("marital_status", {}).get("evidence") == Evidence.MARGINAL_INFERENCE for p in profiles.values()):
            warnings.append("Marital status is inferred conditional on sex only (its relationship with age is not observed).")
        if d.execution.repetitions > 1 and d.model.temperature == 0:
            warnings.append("Repetitions at temperature 0 may return identical answers; repetition variance is not informative then.")
        warnings.extend(ctx_notes)
        plan = {
            "experiment_id": experiment_id, "definition_hash": exp["definition_hash"],
            "population_id": loaded.population_id, "population_content_sha256": loaded.manifest["content_sha256"],
            "cohort_id": cohort["cohort_id"], "cohort_definition_hash": cohort["definition_hash"],
            "sample_id": sample["sample_id"], "sample_members_sha256": sample["members_sha256"],
            "eligible_records": sample["eligible_records"], "eligible_weighted_population": sample["eligible_weighted_population"],
            "selected_records": sample["selected"], "active_personas": n, "minors_in_sample": minors,
            "calls": {"planned": planned_calls, "maximum_with_retries": max_calls, "cap": d.execution.max_calls,
                      "provider_calls_expected": planned_calls if live else 0},
            "tokens": {"input_estimate_per_repetition": tokens_in, "method": "Characters ÷ 4 heuristic over rendered prompts; not a tokenizer.",
                       "max_output_tokens_per_call": d.model.max_output_tokens},
            "cost": {"estimate_usd": cost, "basis": cost_basis, "cap_usd": d.execution.max_cost_usd},
            "backend": {"backend": backend, "transport": d.model.transport, "model": d.model.model, "temperature": d.model.temperature,
                        "seed": d.model.seed},
            "personas": personas, "prompt_hashes": prompt_hashes, "example_prompt": first_prompt,
            "persona_template_version": TEMPLATE_VERSION, "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "visible_fields_policy": (d.persona.field_selection.required + d.persona.field_selection.optional
                                      if d.persona.field_selection is not None
                                      else d.persona.visible_fields or list(DEFAULT_VISIBLE)),
            "blockers": blockers, "warnings": warnings, "executable": not blockers,
        }
        if ref is not None:
            plan["scenario_ref"] = ref.model_dump()
        plan["plan_hash"] = canonical_hash(plan)
        plan["created_at"] = utc_now()
        self.db.insert_plan(plan)
        return plan

    # ================================================================ runs
    def start_run(self, experiment_id: str, plan_hash: str, idempotency_key: str) -> dict:
        exp, d = self._definition(experiment_id)
        plan = self.db.plan(plan_hash)
        if plan is None or plan["experiment_id"] != experiment_id:
            raise not_found("unknown_plan", "No such reviewed plan for this experiment.")
        if plan["blockers"]:
            raise conflict("plan_blocked", "This plan has blockers and cannot run.", {"blockers": plan["blockers"]})
        if plan["definition_hash"] != exp["definition_hash"]:
            raise conflict("stale_plan", "The experiment definition differs from the reviewed plan.")
        try:
            run, created = self.db.create_run({"run_id": new_id("run"), "experiment_id": experiment_id, "plan_hash": plan_hash,
                                               "kind": "execute", "idempotency_key": idempotency_key})
        except ValueError as exc:
            raise conflict("plan_already_ran", str(exc)) from exc
        if created and d.model.backend == "stub":
            self.execute_run(run["run_id"], worker_id="inline")  # offline and instantaneous; executed in the request
        return {"run": self._run_view(self.db.run(run["run_id"])), "created": created}

    def replay(self, run_id: str, idempotency_key: str) -> dict:
        source = self.db.run(run_id)
        if source is None:
            raise not_found("unknown_run", f"No run {run_id}")
        if source["state"] not in ("completed", "completed_with_errors"):
            raise conflict("not_replayable", "Only completed runs can be replayed from the cache.")
        run, created = self.db.create_run({"run_id": new_id("run"), "experiment_id": source["experiment_id"], "plan_hash": source["plan_hash"],
                                           "kind": "replay", "replay_of": run_id, "idempotency_key": idempotency_key})
        if created:
            self.execute_run(run["run_id"], worker_id="inline")
        return {"run": self._run_view(self.db.run(run["run_id"])), "created": created}

    def claim_and_run(self, worker_id: str) -> bool:
        run = self.db.claim_next(worker_id)
        if run is None:
            return False
        self._execute_claimed(run, worker_id)
        return True

    def execute_run(self, run_id: str, worker_id: str) -> None:
        if not self.db.claim(run_id, worker_id):
            return
        self._execute_claimed(self.db.run(run_id), worker_id)

    def _execute_claimed(self, run: dict, worker_id: str) -> None:
        run_id = run["run_id"]
        try:
            with self._run_lock:
                self._execute(run)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded on the run
            self.db.finish(run_id, "failed", None, "run_error", redact(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}", max_length=600))

    def _execute(self, run: dict) -> None:
        exp, d = self._definition(run["experiment_id"])
        plan = self.db.plan(run["plan_hash"])
        loaded = self._load(plan["population_id"])
        if loaded.manifest["content_sha256"] != plan["population_content_sha256"]:
            raise RuntimeError("The population changed after the plan was reviewed.")
        sample = self.sample(plan["sample_id"])
        if sample["members_sha256"] != plan["sample_members_sha256"]:
            raise RuntimeError("The cohort sample differs from the reviewed plan.")
        try:
            store = self.store()
        except Exception:  # noqa: BLE001
            store = None
        run_dir = self.settings.national_runs_dir / run["run_id"]
        run_dir.mkdir(parents=True, exist_ok=False)
        requests, members = [], {}
        build_selected = experiment_persona_builder(loaded, d.persona)
        for m in sample["members"]:
            rec = loaded.record(m["synthetic_id"])
            p = build_selected(m["synthetic_id"])
            code = d.environment.province_code or rec["province_code"]
            context, _ = self._context(store, code, loaded.manifest["reference_year"], d.environment.context_indicators)
            system, user = render_prompts(d, p, context, geo.province(code).name)
            if d.scenario_ref is not None:
                issues = scenario_scope_issues(d.scenario_ref, rec)
                if issues or d.scenario_ref.unenforced_filters:
                    raise RuntimeError(f"Scenario '{d.scenario_ref.scenario_id}' scope violated during execution: {issues or d.scenario_ref.unenforced_filters}")
            members[rec["synthetic_id"]] = {**{f: rec.get(f) for f in GROUPABLE}, "analysis_weight": m["analysis_weight"]}
            for k in range(1, d.execution.repetitions + 1):
                requests.append(CallRequest(f"{p['persona_id']}:{k}", p, k, 1, system, user))
        hashes = {h["synthetic_id"]: h for h in plan["prompt_hashes"]}
        for r in requests:
            h = hashes.get(r.persona["synthetic_id"])
            if not h or h["system_sha256"] != sha256_bytes(r.system.encode()) or h["user_sha256"] != sha256_bytes(r.user.encode()):
                raise RuntimeError("Rendered prompts differ from the reviewed plan (inputs changed); review a new plan.")
        if run["kind"] == "replay":
            backend = ReplayBackend(d, self.db.cache_get)
        elif d.model.backend == "stub":
            backend = StubBackend(d)
        else:
            live = d.model.transport == "live"
            if live and not self.settings.live_execution_enabled:
                raise RuntimeError("Live execution is disabled.")
            creds = credentials_for(d.model.model) if live else {}
            if live and not creds:
                raise RuntimeError("Provider credentials are missing.")
            backend = MatraixBackend(d, self.runtime, run_dir, self.settings, creds)
        outcome = execute(d, requests, backend, load_prices(self.settings.model_price_table),
                          None if run["kind"] == "replay" else self.db.cache_put)
        self.db.insert_responses(run["run_id"], outcome.responses)
        finals = [r for r in outcome.responses if r["is_final"]]
        option_ids = [o.id for o in d.task.options]
        agg = aggregate(finals, members, option_ids, d.execution.repetitions)
        ok = agg["valid_responses"]
        state = ("budget_stopped" if outcome.budget_stopped else "completed" if ok == len(finals) and finals
                 else "completed_with_errors" if ok else "failed")
        usage = {"input_tokens": _sum(r["input_tokens"] for r in outcome.responses),
                 "output_tokens": _sum(r["output_tokens"] for r in outcome.responses),
                 "cost_usd": _sum(r["cost_usd"] for r in outcome.responses),
                 "latency_ms_mean": _mean([r["latency_ms"] for r in outcome.responses if r["latency_ms"] is not None])}
        summary = {"backend": backend.name, "backend_label": backend.label, "calls_attempted": outcome.calls_attempted,
                   "provider_calls": outcome.provider_calls, "personas": len(members), "final_responses": len(finals),
                   "valid_responses": ok, "status_counts": agg["status_counts"], "usage": usage, "errors": outcome.errors[:20],
                   "overall": agg["overall"]}
        manifest = self._run_manifest(run, exp, d, plan, loaded, sample, backend, summary, store)
        (run_dir / "manifest.json").write_text(dumps(manifest, indent=1) + "\n", encoding="utf-8")
        with (run_dir / "responses.jsonl").open("w", encoding="utf-8") as handle:
            for row in outcome.responses:
                handle.write(dumps(row) + "\n")
        summary["manifest_rel"] = (run_dir / "manifest.json").relative_to(self.settings.state_dir).as_posix()
        if state == "completed":
            self.db.finish(run["run_id"], state, summary)
        else:
            detail = f"{len(finals) - ok} of {len(finals)} final responses are not valid." if finals else "No responses were produced."
            self.db.finish(run["run_id"], state, summary, state, detail)

    def _run_manifest(self, run, exp, d, plan, loaded, sample, backend, summary, store) -> dict:
        m = loaded.manifest
        return {
            "run_id": run["run_id"], "kind": run["kind"], "replay_of": run.get("replay_of"), "experiment_id": exp["experiment_id"],
            "created_at": run["created_at"], "finished_at": utc_now(), "runner_version": RUNNER_VERSION,
            "code_version": code_version(self.settings.repo_root),
            "population": {"population_id": m["population_id"], "content_sha256": m["content_sha256"], "seed": m["seed"],
                           "generator_version": m["generator_version"], "reference_year": m["reference_year"],
                           "synthetic_size": m["synthetic_size"]},
            "cohort": self.db.cohort(plan["cohort_id"]), "sample": {k: sample[k] for k in ("sample_id", "config", "members_sha256",
                                                                                         "eligible_records", "selected", "algorithm_version")},
            "persona_template_version": TEMPLATE_VERSION, "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "experiment_definition": exp["definition"], "definition_hash": exp["definition_hash"], "plan_hash": plan["plan_hash"],
            "scenario_ref": d.scenario_ref.model_dump() if d.scenario_ref is not None else None,
            "model": d.model.model_dump(), "backend": backend.name, "backend_label": backend.label,
            "source_versions": {"controls_fingerprint": store.fingerprint if store else None,
                                "sources": m["source_versions"]["sources"]},
            "reference_years": {"population": m["reference_year"],
                                "source_years": {p: prof.get("source_years") for p, prof in m["profiles"].items()}},
            "summary": summary,
            "reproduction": "Replay serves the cached responses of this run for identical prompts (exact). A fresh run with the same "
                            "definition re-draws the same sample and prompts; model outputs may differ.",
        }

    def _run_view(self, run: dict | None) -> dict | None:
        if run is None:
            return None
        summary = run.get("summary") or {}
        return {k: run.get(k) for k in ("run_id", "experiment_id", "plan_hash", "kind", "replay_of", "state", "created_at",
                                        "started_at", "finished_at", "error_code", "error_message")} | {
            "backend": summary.get("backend"), "backend_label": summary.get("backend_label"),
            "personas": summary.get("personas"), "valid_responses": summary.get("valid_responses"),
            "final_responses": summary.get("final_responses"), "calls_attempted": summary.get("calls_attempted"),
            "provider_calls": summary.get("provider_calls"), "usage": summary.get("usage"),
            "status_counts": summary.get("status_counts")}

    def run(self, run_id: str) -> dict:
        run = self.db.run(run_id)
        if run is None:
            raise not_found("unknown_run", f"No run {run_id}")
        exp, d = self._definition(run["experiment_id"])
        plan = self.db.plan(run["plan_hash"])
        manifest = None
        rel = (run.get("summary") or {}).get("manifest_rel")
        if rel and (self.settings.state_dir / rel).is_file():
            manifest = json.loads((self.settings.state_dir / rel).read_text(encoding="utf-8"))
        cohort = self.db.cohort(d.cohort.cohort_id)
        return {"run": self._run_view(run), "title": d.title, "definition": exp["definition"], "cohort": cohort,
                "plan": {k: plan[k] for k in ("plan_hash", "active_personas", "eligible_records", "eligible_weighted_population",
                                             "calls", "cost", "warnings", "population_id", "sample_id", "visible_fields_policy",
                                             "persona_template_version", "prompt_template_version")},
                "manifest": manifest, "is_stub": (run.get("summary") or {}).get("backend") == "stub",
                "is_placeholder": d.model.transport == "fake",
                "label": "Synthetic personas and AI-generated responses. Not real people. Not a prediction of real behaviour."}

    def run_responses(self, run_id: str, final_only: bool, offset: int, limit: int) -> dict:
        if self.db.run(run_id) is None:
            raise not_found("unknown_run", f"No run {run_id}")
        rows = self.db.responses(run_id, final_only)
        return {"run_id": run_id, "total": len(rows), "offset": offset, "limit": limit, "items": rows[offset:offset + limit]}

    def run_aggregate(self, run_id: str, group_by: list[str], min_group: int) -> dict:
        run = self.db.run(run_id)
        if run is None:
            raise not_found("unknown_run", f"No run {run_id}")
        _, d = self._definition(run["experiment_id"])
        plan = self.db.plan(run["plan_hash"])
        sample = self.sample(plan["sample_id"])
        loaded = self._load(plan["population_id"])
        members = {}
        for m in sample["members"]:
            rec = loaded.record(m["synthetic_id"])
            members[m["synthetic_id"]] = {**{f: rec.get(f) for f in GROUPABLE}, "analysis_weight": m["analysis_weight"]}
        finals = self.db.responses(run_id, final_only=True)
        try:
            out = aggregate(finals, members, [o.id for o in d.task.options], d.execution.repetitions, group_by, min_group)
        except ValueError as exc:
            raise invalid("invalid_group_by", str(exc)) from exc
        out["options"] = [o.model_dump() for o in d.task.options]
        out["is_stub"] = (run.get("summary") or {}).get("backend") == "stub"
        out["is_placeholder"] = d.model.transport == "fake"
        return out

    def runs(self) -> dict:
        items = []
        for r in self.db.runs():
            exp = self.db.experiment(r["experiment_id"])
            items.append({**self._run_view(r), "title": exp["definition"]["title"] if exp else None})
        return {"items": items, "total": len(items)}

    def recover(self) -> list[str]:
        return self.db.recover_interrupted()

    # ================================================================ overview / capabilities
    def overview(self) -> dict:
        controls = self.controls_status()
        pops = self.list_populations()
        latest = self.runs()["items"][:1]
        cohorts = self.db.cohorts()
        personas = sum((r.get("personas") or 0) for r in self.runs()["items"] if r["state"] in ("completed", "completed_with_errors"))
        geo_info = self.geography(population_id=pops["default_population_id"]) if pops["default_population_id"] else self.geography()
        return {"controls": {"status": controls["status"], "built_at": controls.get("built_at"),
                             "tables": [t["table_id"] for t in controls.get("tables", [])]},
                "populations": pops["items"][:5], "default_population_id": pops["default_population_id"],
                "provinces_with_population_controls": geo_info["provinces_with_population_controls"],
                "province_count": geo_info["province_count"], "saved_cohorts": len(cohorts),
                "experiments": len(self.db.experiments()), "personas_used_in_completed_runs": personas,
                "latest_run": latest[0] if latest else None}

    def capabilities(self) -> dict:
        status = self.runtime.national_status()
        live_reasons = []
        if not self.settings.live_execution_enabled:
            live_reasons.append("Disabled (SOCIETYTWIN_ENABLE_LIVE_EXECUTION is not set).")
        if not status["available"]:
            live_reasons.extend(status["reasons"])
        keys = {p: any(os.environ.get(n) for n in provider_env_names(f"{p}/x")) for p in ("anthropic", "openai", "gemini")}
        return {"backends": {"stub": {"available": True, "reasons": [], "note": STUB_NOTICE},
                             "matraix_fake": {"available": status["available"], "reasons": status["reasons"]},
                             "matraix_live": {"available": not live_reasons and any(keys.values()), "reasons": live_reasons
                                              + ([] if any(keys.values()) else ["No provider key in the server environment."])}},
                "provider_key_present": keys, "max_agents_per_run": self.settings.max_agents_per_run,
                "price_table_configured": bool(load_prices(self.settings.model_price_table)),
                "generator_version": GENERATOR_VERSION, "constraint_rules": [r.as_dict() for r in RULES],
                "dependency_model": dependency_graph(), "tolerances": ValidationTolerances().__dict__,
                "tolerance_justification": ValidationTolerances().justification(),
                "vocabularies": {k: v.as_dict() for k, v in VOCABULARIES.items()}, "evidence_levels": Evidence.DESCRIPTIONS,
                "persona_fields": {"all": list(PERSON_FIELDS), "default_visible": list(DEFAULT_VISIBLE)},
                "groupable": list(GROUPABLE)}


def _sum(values) -> float | None:
    values = list(values)
    if not values or any(v is None for v in values):
        return None
    return float(math.fsum(values))


def _mean(values: list) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _source_years(manifest: dict, provinces: list[str] | None) -> list[dict]:
    out = []
    for pid, prof in sorted(manifest["profiles"].items()):
        if provinces and prof["province_code"] not in provinces:
            continue
        out.append({"province_code": prof["province_code"], "province_name": prof["province_name"],
                    "reference_year": prof["reference_year"], "source_years": prof["source_years"]})
    return out
