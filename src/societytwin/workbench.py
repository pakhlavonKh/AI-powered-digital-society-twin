"""Application services used by the API. Business rules live here and in the domain modules."""

from __future__ import annotations

import threading
from collections import Counter
from pathlib import Path

from societytwin import FIXTURE_ATTRIBUTION_NOTE, SYNTHETIC_POPULATION_LABEL, SYNTHETIC_RESPONSE_LABEL
from societytwin.agents.matraix_runtime import MatraixRuntime
from societytwin.common import new_id, sha256_bytes, utc_now
from societytwin.config import Settings
from societytwin.errors import WorkbenchError, conflict, invalid, not_found, unavailable
from societytwin.evaluation.source_fit import base_v2_consistency, validation_report
from societytwin.experiments.historical import RUN_DIR_PATTERN, file_manifest, parse_run
from societytwin.experiments.models import CohortCreateRequest
from societytwin.ingestion.manifest import load_manifest
from societytwin.persona.views import (
    adapter_constants,
    build_context_notes,
    fixture_persona_index,
    persona_artifact_view,
    runner_constants,
)
from societytwin.population.categories import MARITAL_DISPLAY_EN
from societytwin.population.fixtures import FixtureFormatError
from societytwin.population.repository import CsvPopulationRepository, FixtureUnavailable, LoadedBuild
from societytwin.registry.store import Registry
from societytwin.sampling.filters import FieldUnavailable, FilterSpec
from societytwin.sampling.query import QueryError, crosstab, distributions, filtered_rows, page
from societytwin.sampling.srs import ALGORITHM_VERSION, SamplingError, design_weights, simple_random_sample

DEFAULT_GROUPS = ("age_group", "gender", "marital_status")


class Workbench:
    def __init__(self, settings: Settings, runtime: MatraixRuntime | None = None):
        self.settings = settings
        self.population = CsvPopulationRepository(settings)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.registry = Registry(settings.registry_path)
        self.runtime = runtime or MatraixRuntime(settings)
        self._run_cache: dict[str, tuple[str, dict]] = {}
        self._run_lock = threading.Lock()
        self.sync_builds()

    def close(self) -> None:
        self.registry.close()

    # ================================================================ builds
    def sync_builds(self) -> list[LoadedBuild]:
        current = self.population.current_builds()
        for build in current:
            self.registry.register_build(build.descriptor)
        return current

    def _availability(self, descriptor: dict, current_ids: set[str]) -> dict:
        if descriptor["build_id"] in current_ids:
            return {"status": "available", "detail": "The registered file bytes are present and unchanged."}
        return {"status": "source_changed",
                "detail": "The file registered under this ID has changed or is missing. The ID is kept for provenance; "
                          "records and dependent operations are unavailable."}

    def list_builds(self) -> dict:
        current = self.sync_builds()
        current_ids = {b.descriptor["build_id"] for b in current}
        items = [dict(d, availability=self._availability(d, current_ids)) for d in self.registry.builds()]
        default = next((b.descriptor["build_id"] for b in current if b.descriptor["is_default"]), None)
        relations = []
        base = next((b for b in current if b.source.variant == "base"), None)
        v2 = next((b for b in current if b.source.variant == "v2"), None)
        if base and v2:
            check = base_v2_consistency(base.table, v2.table)
            relations.append({"from_build_id": base.descriptor["build_id"], "to_build_id": v2.descriptor["build_id"],
                              "relation": "same_residents_extended" if check["passed"] else "unrelated", "detail": check["detail"]})
        return {"items": items, "default_build_id": default, "relations": relations,
                "load_errors": self.population.build_errors()}

    def get_build(self, build_id: str) -> dict:
        current = self.sync_builds()
        descriptor = self.registry.build(build_id)
        if descriptor is None:
            raise not_found("unknown_build", f"No build is registered with ID {build_id}")
        return dict(descriptor, availability=self._availability(descriptor, {b.descriptor["build_id"] for b in current}))

    def load_build(self, build_id: str) -> LoadedBuild:
        for build in self.sync_builds():
            if build.descriptor["build_id"] == build_id:
                return build
        if self.registry.build(build_id) is not None:
            raise conflict("build_source_changed",
                           f"Build {build_id} is registered, but its source file has changed or is missing. "
                           "No other build is substituted.")
        raise not_found("unknown_build", f"No build is registered with ID {build_id}")

    # ================================================================ records
    def _filtered(self, build: LoadedBuild, spec: FilterSpec) -> list[dict]:
        try:
            spec.check_available(build.descriptor["available_fields"], build.descriptor["build_id"])
        except FieldUnavailable as exc:
            raise invalid("field_unavailable", str(exc), {"field": exc.field}) from exc
        return filtered_rows(build.table, spec)

    def records(self, build_id: str, spec: FilterSpec, sort: str, direction: str, offset: int, limit: int) -> dict:
        build = self.load_build(build_id)
        rows = self._filtered(build, spec)
        try:
            items = page(rows, build.descriptor["available_fields"], sort, direction, offset, limit)
        except QueryError as exc:
            raise invalid(exc.code, str(exc)) from exc
        return {
            "items": [dict(row, csv_row=build.table.csv_rows[row["person_id"]]) for row in items],
            "total_matching": len(rows), "total_records": build.table.row_count, "offset": offset, "limit": limit,
            "sort": sort, "direction": direction, "filters": spec.normalized(),
            "build_id": build_id, "source_sha256": build.table.sha256, "synthetic_label": SYNTHETIC_POPULATION_LABEL,
        }

    def summary(self, build_id: str, spec: FilterSpec, group_by: list[str] | None, with_crosstab: bool) -> dict:
        build = self.load_build(build_id)
        rows = self._filtered(build, spec)
        fields = build.descriptor["available_fields"]
        groups = group_by or [g for g in DEFAULT_GROUPS if g in fields]
        try:
            dists = distributions(rows, fields, groups)
            table = crosstab(rows, fields, "age_group", "gender") if with_crosstab else None
        except QueryError as exc:
            raise invalid(exc.code, str(exc)) from exc
        return {
            "build_id": build_id, "source_sha256": build.table.sha256, "filters": spec.normalized(),
            "denominator": len(rows), "total_records": build.table.row_count,
            "distributions": dists, "crosstab": table,
            "display_translations": {"marital_status": MARITAL_DISPLAY_EN},
            "method": "Counts over the loaded synthetic rows after applying the filters; shares use the filtered count as denominator.",
            "limitations": [
                "Describes the synthetic build only; it is not an estimate of the real population.",
                "Under-15 residents carry marital_status=not_applicable by construction.",
            ] if "marital_status" in fields else ["Describes the synthetic build only; it is not an estimate of the real population."],
            "synthetic_label": SYNTHETIC_POPULATION_LABEL,
        }

    def validation(self, build_id: str) -> dict:
        build = self.load_build(build_id)
        try:
            age_gender = self.population.age_gender()
            marital = self.population.marital_gender() if build.source.variant == "v2" else None
            controls = self.population.controls()
        except (FixtureUnavailable, FixtureFormatError) as exc:
            raise unavailable("reference_unavailable", f"Reference tables cannot be read: {exc}") from exc
        report = validation_report(build.table, build.source.variant, age_gender, marital, controls)
        if build.source.variant == "v2":
            base = next((b for b in self.population.current_builds() if b.source.variant == "base"), None)
            if base:
                report["checks"].append(base_v2_consistency(base.table, build.table))
        report.update(
            build_id=build_id,
            reference_tables=[self._table_ref(self.settings.layout.age_gender, age_gender.sha256, age_gender.year, len(age_gender.rows))]
            + ([self._table_ref(self.settings.layout.marital_gender, marital.sha256, marital.year, len(marital.rows))] if marital else []),
            persona_hash_checks=self._fixture_hash_checks(build),
            synthetic_label=SYNTHETIC_POPULATION_LABEL,
            attribution_note=FIXTURE_ATTRIBUTION_NOTE,
        )
        return report

    @staticmethod
    def _table_ref(path: str, sha: str, year: int, rows: int) -> dict:
        return {"path": path, "sha256": sha, "reference_year": year, "rows": rows}

    def _fixture_hash_checks(self, build: LoadedBuild) -> list[dict]:
        out = []
        for persona_id, paths in sorted(fixture_persona_index(self.settings).items()):
            if persona_id not in build.table.csv_rows:
                continue
            for path in paths:
                view = self._persona_file_view(path, build, persona_id, origin="fixture")
                if view.get("valid") and view["metadata"].get("source_population") == build.source.relative_path:
                    out.append({"persona_file": view["relpath"], "persona_id": persona_id, "sha256": view["sha256"],
                                "checks": view["hash_checks"], "source_row_check": view["source_row_check"]})
        return out

    # ================================================================ cohorts
    def _realized_counts(self, rows: list[dict], fields: list[str]) -> dict:
        return {f: dict(Counter(r[f] for r in rows)) for f in DEFAULT_GROUPS if f in fields}

    def preview_cohort(self, build_id: str, spec: FilterSpec) -> dict:
        build = self.load_build(build_id)
        rows = self._filtered(build, spec)
        fields = build.descriptor["available_fields"]
        return {
            "build_id": build_id, "source_sha256": build.table.sha256, "filters": spec.normalized(),
            "eligible_count": len(rows), "total_records": build.table.row_count,
            "distributions": distributions(rows, fields, [g for g in DEFAULT_GROUPS if g in fields]),
            "can_persist": len(rows) > 0,
            "note": "Preview only: nothing is saved and nothing is run. A saved cohort must be nonempty.",
            "synthetic_label": SYNTHETIC_POPULATION_LABEL,
        }

    def create_cohort(self, request: CohortCreateRequest) -> dict:
        build = self.load_build(request.build_id)
        if build.table.sha256 != request.source_sha256:
            raise conflict("stale_source_hash", "The build's source bytes differ from the previewed hash; preview again.")
        rows = self._filtered(build, request.filters)
        if not rows:
            raise invalid("empty_frame", "No records match these filters; an executable cohort must be nonempty.")
        frame = [r["person_id"] for r in rows]
        try:
            selected = simple_random_sample(frame, request.size, request.seed)
        except SamplingError as exc:
            raise invalid(exc.code, str(exc)) from exc
        by_id = {r["person_id"]: r for r in rows}
        manifest = {
            "cohort_id": new_id("coh"),
            "name": request.name,
            "build_id": request.build_id,
            "source_sha256": build.table.sha256,
            "requested": {"filters": request.filters.normalized(), "size": request.size,
                          "sampling": request.sampling, "seed": request.seed},
            "realized": {
                "record_ids": selected,
                "eligible_count": len(frame),
                "selected_count": len(selected),
                **design_weights(len(frame), len(selected)),
                "realized_counts": self._realized_counts([by_id[i] for i in selected], build.descriptor["available_fields"]),
            },
            "sampling_algorithm_version": ALGORITHM_VERSION,
            "frame_ordering": "Eligible person IDs sorted ascending before sampling; record_ids are in selection order.",
            "created_at": utc_now(),
            "scope_note": "Drawn from the loaded synthetic build only. Weights describe that synthetic frame, not real residents.",
            "synthetic_label": SYNTHETIC_POPULATION_LABEL,
        }
        self.registry.insert_cohort(manifest)
        return self.cohort(manifest["cohort_id"])

    def _cohort_status(self, manifest: dict) -> dict:
        current = {b.descriptor["build_id"]: b for b in self.sync_builds()}
        build = current.get(manifest["build_id"])
        if build is None:
            return {"status": "build_unavailable", "detail": "The cohort's build source has changed or is missing; the cohort cannot be used for new operations."}
        if build.table.sha256 != manifest["source_sha256"]:
            return {"status": "source_changed", "detail": "The build bytes differ from those the cohort was drawn from."}
        return {"status": "valid", "detail": "The cohort's build source is unchanged."}

    def cohort(self, cohort_id: str) -> dict:
        manifest = self.registry.cohort(cohort_id)
        if manifest is None:
            raise not_found("unknown_cohort", f"No cohort {cohort_id}")
        return dict(manifest, current=self._cohort_status(manifest))

    def cohorts(self) -> dict:
        items = [dict(m, current=self._cohort_status(m)) for m in self.registry.cohorts()]
        return {"items": items, "total": len(items)}

    def require_valid_cohort(self, cohort_id: str) -> dict:
        cohort = self.cohort(cohort_id)
        if cohort["current"]["status"] != "valid":
            raise conflict("stale_cohort", cohort["current"]["detail"])
        return cohort

    # ================================================================ datasets
    def datasets(self) -> dict:
        manifest_status, manifest_entries, manifest_error = "missing", [], None
        if self.settings.data_manifest.is_file():
            try:
                manifest = load_manifest(self.settings.data_manifest)
                manifest_entries = manifest["datasets"]
                manifest_status = "empty" if not manifest_entries else "populated"
            except (ValueError, OSError) as exc:
                manifest_status, manifest_error = "invalid", str(exc)
        layout = self.settings.layout
        evidence = []
        declared = {
            layout.age_gender: ("processed_reference", "TÜİK ADNKS T16 (Ankara population by age group and sex), as recorded by the project's processing code."),
            layout.marital_gender: ("processed_reference", "TÜİK ADNKS T10 (marital status by sex, ages 15+), as recorded by the project's processing code."),
            layout.controls: ("processed_reference", "TÜİK provincial workbooks (population, density, median age); workbook, sheet and row are recorded per observation."),
            layout.base_population: ("synthetic_population", "Generated by the project from the processed age × sex table."),
            layout.v2_population: ("synthetic_population", "Generated by the project: base rows plus sex-conditioned marital status."),
        }
        for rel, (kind, source) in declared.items():
            path = self.settings.experiment_file(rel)
            entry = {"id": Path(rel).stem, "path": rel, "kind": kind, "declared_source": source,
                     "present": path.is_file(), "sha256": None, "bytes": None, "rows": None, "columns": None,
                     "raw_evidence_status": "unavailable", "licence": None, "url": None, "download_date": None,
                     "raw_checksum": None,
                     "gaps": ["Raw source file absent", "Licence/reuse terms unknown (OPEN DECISION in docs)",
                              "Download date and URL not recorded"] if kind == "processed_reference" else
                             ["Generated fixture; no external licence applies, but its inputs inherit the gaps above"]}
            if path.is_file():
                data = path.read_bytes()
                lines = data.decode("utf-8-sig", errors="replace").splitlines()
                entry.update(sha256=sha256_bytes(data), bytes=len(data), rows=max(len(lines) - 1, 0),
                             columns=lines[0].split(",") if lines else [])
            evidence.append(entry)
        for persona_id, paths in sorted(fixture_persona_index(self.settings).items()):
            for path in paths:
                data = path.read_bytes()
                evidence.append({"id": path.stem, "path": f"{layout.personas_dir}/{path.name}", "kind": "persona_fixture",
                                 "declared_source": f"Persona YAML for {persona_id} written by the project's persona adapter.",
                                 "present": True, "sha256": sha256_bytes(data), "bytes": len(data), "rows": None, "columns": None,
                                 "raw_evidence_status": "not_applicable", "licence": None, "url": None, "download_date": None,
                                 "raw_checksum": None, "gaps": ["Recorded input hashes match current files only after line-ending conversion (see Persona Explorer)"]})
        controls = []
        try:
            for fact in self.population.controls().facts:
                controls.append({"year": fact.year, "province": fact.province, "statistic": fact.statistic, "value": fact.value,
                                 "unit": fact.unit,
                                 "observations": [{"source_workbook": o["source_workbook"], "source_sheet": o["source_sheet"],
                                                   "source_row": o["source_row"], "csv_row": o["csv_row"]} for o in fact.observations]})
        except (FixtureUnavailable, FixtureFormatError):
            controls = []
        return {
            "manifest": {"path": "data/manifest.yaml", "status": manifest_status, "datasets": manifest_entries,
                         "error": manifest_error,
                         "note": "The root data manifest is the project's record of downloaded datasets. It is empty: no dataset has been registered there."},
            "fixture_evidence": evidence,
            "controls": controls,
            "controls_note": "Agreeing duplicate observations are grouped; every source observation is kept. Median ages are aggregate context, not resident ages.",
            "synthetic_label": SYNTHETIC_POPULATION_LABEL,
            "attribution_note": FIXTURE_ATTRIBUTION_NOTE,
        }

    # ================================================================ personas
    def _recorded_file_bytes(self, rel) -> bytes | None:
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            return None
        path = self.settings.experiment_root / rel
        try:
            if path.is_file() and path.resolve().is_relative_to(self.settings.experiment_root.resolve()):
                return path.read_bytes()
        except OSError:
            return None
        return None

    def _persona_file_view(self, path: Path, build: LoadedBuild, record_id: str, origin: str,
                           artifact_id: str | None = None) -> dict:
        data = path.read_bytes()
        if origin == "fixture":
            relpath = f"{self.settings.layout.personas_dir}/{path.name}"
            artifact_id = artifact_id or f"fixture:{path.name}"
        else:
            relpath = path.relative_to(self.settings.state_dir).as_posix()
        try:
            import yaml

            meta = (yaml.safe_load(data.decode("utf-8")) or {}).get("metadata") or {}
        except Exception:  # noqa: BLE001
            meta = {}
        current = {"source_population": self._recorded_file_bytes(meta.get("source_population"))}
        for name, entry in (meta.get("processed_sources") or {}).items():
            current[f"processed:{name}"] = self._recorded_file_bytes(entry.get("path") if isinstance(entry, dict) else None)
        row = next((r for r in build.table.rows if r["person_id"] == record_id), None)
        return persona_artifact_view(data, artifact_id=artifact_id, origin=origin, relpath=relpath, row=row,
                                     csv_row=build.table.csv_rows.get(record_id), current_files=current,
                                     catalog_bytes=self.runtime.catalog_bytes())

    def persona_view(self, build_id: str, record_id: str) -> dict:
        build = self.load_build(build_id)
        if record_id not in build.table.csv_rows:
            raise not_found("unknown_record", f"No resident {record_id} in build {build_id}")
        row = next(r for r in build.table.rows if r["person_id"] == record_id)
        layout = self.settings.layout
        artifacts = []
        if build.source.variant == "v2":
            for path in fixture_persona_index(self.settings).get(record_id, []):
                view = self._persona_file_view(path, build, record_id, "fixture")
                if view.get("valid") and view["metadata"].get("source_population") != build.source.relative_path:
                    view["mapping_warnings"].append("This persona records a different source population file.")
                artifacts.append(view)
            for rec in self.registry.personas_for(build_id, record_id):
                path = self.settings.state_dir / rec["path_rel"]
                if path.is_file():
                    artifacts.append(self._persona_file_view(path, build, record_id, "managed", rec["persona_artifact_id"]))
        valid = [a for a in artifacts if a.get("valid")]
        has_fixture = any(a["origin"] == "fixture" for a in valid)
        has_managed = any(a["origin"] == "managed" for a in valid)
        status = ("fixture_and_materialized" if has_fixture and has_managed else "materialized_persona" if has_managed
                  else "fixture_persona" if has_fixture else "source_card_only")

        tables = [{"field": "age_group", "table": layout.age_gender, "note": "Sampled jointly with sex from the age × sex cells."},
                  {"field": "gender", "table": layout.age_gender, "note": "Sampled jointly with the age group."}]
        if "marital_status" in row:
            tables.append({"field": "marital_status", "table": layout.marital_gender,
                           "note": "Drawn conditional on sex only for ages 15+; not_applicable under 15."})
        constants = adapter_constants(self.settings)
        runner = runner_constants(self.settings)
        mapping = constants["marital_mapping"]
        omissions = []
        if mapping is not None and "marital_status" in row and row["marital_status"] not in mapping:
            omissions.append(f"demo_marital_status would be absent: the adapter has no mapping for {row['marital_status']!r}; "
                             "the source value stays in metadata.")
        omissions.append("Sex stays in metadata only; it is never a prompt dimension.")
        omissions.append("The catalog age bracket is chosen by the adapter against the external catalog; it is omitted when no bracket wholly contains the band.")
        runtime_status = self.runtime.file_status()
        reasons = []
        if build.source.variant != "v2":
            reasons.append("The persona adapter reads only the v2 population schema.")
        if mapping is None:
            reasons.append("The adapter source could not be read in this checkout.")
        if not runtime_status["files_ready"]:
            reasons.extend(runtime_status["reasons"])
        elif runtime_status["probe"]["status"] != "passed":
            reasons.append("Run the runtime import probe first (Check runtime) so the adapter's MatrAIx loader check can run.")
        fixed = runner["expected_ids"] or []
        legacy_note = ("The fixed A/B runner loads only its two fixture files by path; other residents cannot run through it, "
                       "even after materialization.")
        if omissions and omissions[0].startswith("demo_marital_status") :
            legacy_note += " Its preflight also requires demo_marital_status, which this resident's mapping would not provide."
        evidence = []
        for run in self.imported_runs():
            for trial in run["trials"]:
                if trial["persona_id"] == record_id and trial["prompts"]:
                    evidence.append({"experiment_id": run["experiment_id"], "trial_label": trial["label"],
                                     "display_state": run["display_state"], "evidence_kind": run["evidence_kind"],
                                     "model": run["model"], "system_sha256": trial["prompts"]["system_sha256"],
                                     "prompt_source": trial["prompts"]["source"],
                                     "persona_snapshot_sha256": (trial["persona_snapshot"] or {}).get("sha256")})
        return {
            "build_id": build_id, "record_id": record_id, "build_variant": build.source.variant,
            "source_card": {
                "attributes": row, "csv_row": build.table.csv_rows[record_id], "source_path": build.source.relative_path,
                "source_sha256": build.table.sha256, "context": build.descriptor["scope"], "source_tables": tables,
                "display_translations": {"marital_status": MARITAL_DISPLAY_EN},
                "not_modelled": build.descriptor["unavailable_fields"],
                "note": "Read-only view of the population row. This is not a MatrAIx persona and was never shown to a model.",
            },
            "persona_status": status,
            "personas": artifacts,
            "materialization": {"available": not reasons, "reasons": reasons, "expected_omissions": omissions,
                                "output_note": "Writes a new YAML under managed state and never overwrites a fixture. Its provenance hashes "
                                               "reflect today's bytes, so it is a new artifact, not a copy of a fixture."},
            "legacy_runner": {"fixed_ids": fixed, "in_fixed_pair": record_id in fixed,
                              "slot": ("A" if fixed and record_id == fixed[0] else "B" if len(fixed) > 1 and record_id == fixed[1] else None),
                              "note": legacy_note},
            "historical_prompt_evidence": evidence,
            "notes": build_context_notes(),
            "synthetic_label": SYNTHETIC_RESPONSE_LABEL,
        }

    def persona_index(self, build_id: str) -> dict:
        build = self.load_build(build_id)
        items = []
        if build.source.variant == "v2":
            for persona_id, paths in sorted(fixture_persona_index(self.settings).items()):
                if persona_id in build.table.csv_rows:
                    for path in paths:
                        items.append({"record_id": persona_id, "origin": "fixture", "persona_artifact_id": f"fixture:{path.name}",
                                      "relpath": f"{self.settings.layout.personas_dir}/{path.name}",
                                      "sha256": sha256_bytes(path.read_bytes()), "created_at": None})
            for rec in self.registry.personas_for_build(build_id):
                items.append({"record_id": rec["record_id"], "origin": "managed", "persona_artifact_id": rec["persona_artifact_id"],
                              "relpath": rec["path_rel"], "sha256": rec["sha256"], "created_at": rec["created_at"]})
        return {"build_id": build_id, "items": items, "fixed_pair": runner_constants(self.settings)["expected_ids"] or [],
                "note": "Stored persona YAMLs linked to this build. Every other resident has a read-only source card only."}

    def materialize_persona(self, build_id: str, record_id: str) -> dict:
        view = self.persona_view(build_id, record_id)
        build = self.load_build(build_id)
        if build.source.variant != "v2":
            raise conflict("materialization_unsupported_build", "The persona adapter reads only the v2 population schema.")
        if not view["materialization"]["available"]:
            status = self.runtime.file_status()
            if status["files_ready"] and status["probe"]["status"] != "passed":
                if self.runtime.probe()["status"] != "passed":
                    raise unavailable("runtime_probe_failed", "The runtime interpreter could not import MatrAIx.",
                                      {"log": self.runtime.file_status()["probe"].get("log_relpath")})
            else:
                raise unavailable("runtime_unavailable", "Persona materialization is unavailable.",
                                  {"reasons": view["materialization"]["reasons"]})
        artifact = new_id("per")
        out_dir = self.settings.managed_personas_dir / build_id / record_id / artifact
        output = out_dir / "persona.yaml"
        log = self.settings.state_dir / "logs" / f"{artifact}.log"
        source_before = sha256_bytes(self.settings.experiment_file(build.source.relative_path).read_bytes())
        result = self.runtime.materialize(record_id, self.settings.experiment_file(build.source.relative_path), output, log)
        if not result.ok:
            raise invalid("materialization_failed",
                          "The existing persona adapter rejected this resident or could not run; nothing was registered.",
                          {"adapter_message": result.error_tail, "log": result.log_relpath, "timed_out": result.timed_out})
        if sha256_bytes(self.settings.experiment_file(build.source.relative_path).read_bytes()) != source_before:
            raise conflict("source_changed_during_materialization", "The source population changed while the adapter ran.")
        data = output.read_bytes()
        catalog = self.runtime.catalog_bytes()
        adapter_src = self.settings.experiment_file(self.settings.layout.adapter_source)
        self.registry.insert_persona({
            "persona_artifact_id": artifact, "build_id": build_id, "record_id": record_id,
            "path_rel": output.relative_to(self.settings.state_dir).as_posix(), "sha256": sha256_bytes(data),
            "source_sha256": build.table.sha256, "catalog_sha256": sha256_bytes(catalog) if catalog else None,
            "adapter_sha256": sha256_bytes(adapter_src.read_bytes()) if adapter_src.is_file() else None,
            "created_at": utc_now(),
        })
        return self.persona_view(build_id, record_id)

    # ================================================================ imported runs
    def _import_dirs(self) -> list[Path]:
        root = self.settings.import_runs_root
        if not root.is_dir():
            return []
        return sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and RUN_DIR_PATTERN.fullmatch(p.name))

    def _parse_cached(self, run_dir: Path, experiment_id: str, origin: str) -> dict:
        from societytwin.experiments.evidence_files import RunFiles

        signature = sha256_bytes(repr(RunFiles(run_dir).listing()).encode())
        with self._run_lock:
            hit = self._run_cache.get(experiment_id)
            if hit and hit[0] == signature:
                return hit[1]
        run = parse_run(run_dir, experiment_id, origin)
        if origin == "imported":
            manifest = file_manifest(run_dir)
            first = self.registry.imported_manifest(experiment_id)
            if first is None:
                self.registry.register_import(experiment_id, run_dir.name, manifest)
                drift = []
            else:
                before = first["file_manifest"]
                drift = sorted({k for k in set(before) | set(manifest) if before.get(k) != manifest.get(k)})
            run["evidence_drift"] = drift
            if drift:
                run["warnings"].append(f"{len(drift)} file(s) changed, appeared or disappeared since this folder was first imported.")
        else:
            run["evidence_drift"] = []
        with self._run_lock:
            self._run_cache[experiment_id] = (signature, run)
        return run

    def imported_runs(self) -> list[dict]:
        return [self._parse_cached(d, f"imp_{d.name}", "imported") for d in self._import_dirs()]

    def _managed_runs(self, experiment_id: str) -> list[dict]:
        runs = []
        for job in self.registry.jobs_for(experiment_id):
            out = self.settings.state_dir / job["output_rel"]
            if out.is_dir():
                run = self._parse_cached(out, f"{experiment_id}:{job['job_id']}", "managed")
                runs.append(dict(run, job_id=job["job_id"], job_state=job["state"]))
        return runs

    def _run_for(self, experiment_id: str, job_id: str | None = None) -> dict:
        if experiment_id.startswith("imp_"):
            for run in self.imported_runs():
                if run["experiment_id"] == experiment_id:
                    return run
            raise not_found("unknown_experiment", f"No imported run {experiment_id}")
        if self.registry.experiment(experiment_id) is None:
            raise not_found("unknown_experiment", f"No experiment {experiment_id}")
        runs = self._managed_runs(experiment_id)
        if job_id:
            runs = [r for r in runs if r["job_id"] == job_id]
        if not runs:
            raise not_found("no_results", "This experiment has no recorded run output yet.")
        return runs[0]

    # ================================================================ experiments
    def _fixture_selection(self, persona_source: str) -> list[dict]:
        ids = runner_constants(self.settings)["expected_ids"]
        if not ids:
            raise unavailable("runner_constants_unavailable", "The A/B runner's fixed persona IDs could not be read.")
        wanted = ids if persona_source == "legacy_fixture_pair" else ids[:1]
        index = fixture_persona_index(self.settings)
        out = []
        for label, pid in zip(("A", "B"), wanted):
            paths = index.get(pid, [])
            if len(paths) != 1:
                raise unavailable("fixture_persona_unavailable", f"Expected exactly one fixture persona file for {pid}.")
            out.append({"label": label, "persona_id": pid, "path": f"{self.settings.layout.personas_dir}/{paths[0].name}",
                        "sha256": sha256_bytes(paths[0].read_bytes())})
        return out

    def _current_fixture_hashes(self, selection: list[dict]) -> list[dict]:
        current = []
        for item in selection:
            data = self._recorded_file_bytes(item["path"])
            current.append(dict(item, sha256=sha256_bytes(data) if data is not None else None))
        return current

    def draft_blockers(self, config: dict) -> list[dict]:
        blockers = []

        def add(code, message):
            blockers.append({"code": code, "message": message})

        if config["persona_source"] == "cohort":
            add("cohort_execution_unsupported",
                "No verified runner accepts arbitrary cohorts: the existing runners use fixed fixture personas. "
                "This draft is saved for design only.")
            try:
                if self.cohort(config["cohort_id"])["current"]["status"] != "valid":
                    add("stale_cohort", "The cohort's build source has changed since it was drawn.")
            except WorkbenchError:
                add("unknown_cohort", "The referenced cohort no longer exists.")
        if config["scenario"]["kind"] == "draft":
            add("scenario_execution_unsupported",
                "Custom scenarios are saved drafts only; the fixed survey runner cannot add a scenario condition.")
        if config["environment"] != "SURVEY":
            add("environment_not_executable", "Only the SURVEY environment has a verified executor; SCENARIO is draft-only.")
        mode = config["mode"]
        if mode == "smoke" and config["persona_source"] != "legacy_fixture_single":
            add("mode_persona_mismatch", "Smoke runs only the first fixture persona (ANK2025_000001) through the fake transport.")
        if mode in {"preflight", "legacy_ab_live"} and config["persona_source"] != "legacy_fixture_pair":
            add("mode_persona_mismatch", "The A/B preflight and live path use exactly the existing two-persona fixture.")
        if mode in {"preflight", "legacy_ab_live"}:
            prefixes = runner_constants(self.settings)["provider_prefixes"] or []
            if not config.get("model"):
                add("model_required", "Choose an explicit provider/model; nothing is resolved from server defaults.")
            elif config["model"].split("/", 1)[0] not in prefixes:
                add("unsupported_provider", f"The A/B runner accepts these provider prefixes only: {', '.join(prefixes)}.")
            if config.get("temperature") is None:
                add("temperature_required", "Set an explicit temperature in [0, 1].")
        if mode == "legacy_ab_live" and config["calls_limit"] != 2:
            add("call_limit_mismatch", "The fixed A/B runner makes exactly two calls (one per persona); set the call limit to 2.")
        if config["persona_source"] != "cohort":
            recorded = config["persona_artifact_hashes"]
            if any(c["sha256"] != r["sha256"] for c, r in zip(self._current_fixture_hashes(recorded), recorded)):
                add("stale_persona_fixture", "A fixture persona file changed after this draft was saved.")
        return blockers

    def create_draft(self, request) -> dict:
        if request.persona_source == "cohort":
            cohort = self.cohort(request.cohort_id)
            realized = list(cohort["realized"]["record_ids"])
            build_id = cohort["build_id"]
            selection = []
        else:
            selection = self._fixture_selection(request.persona_source)
            realized = [s["persona_id"] for s in selection]
            build_id = next((b.descriptor["build_id"] for b in self.sync_builds() if b.source.variant == "v2"), None)
        config = {
            "experiment_id": new_id("exp"),
            "origin": "managed",
            "name": request.name,
            "persona_source": request.persona_source,
            "cohort_id": request.cohort_id,
            "build_id": build_id,
            "realized_ids": realized,
            "scenario": request.scenario.model_dump(),
            "task": {"id": request.task.id, "instrument_id": "product_feedback_v1",
                     "task_path": "application/tasks/example-survey_product-feedback",
                     "content_hash": self.runtime.task_content_hash()},
            "environment": request.environment,
            "mode": request.mode,
            "model": request.model,
            "temperature": request.temperature,
            "calls_limit": request.calls_limit,
            "persona_artifact_hashes": selection,
            "created_at": utc_now(),
            "provenance_gaps": [],
        }
        if config["task"]["content_hash"] is None:
            config["provenance_gaps"].append("External task content was not available when the draft was saved; its hash is unknown.")
        config["model_seed"] = None
        config["provenance_gaps"].append("No model-side seed is available; a cohort seed does not make model outputs deterministic.")
        hashed = {k: v for k, v in config.items() if k not in {"experiment_id", "created_at", "config_hash"}}
        from societytwin.common import canonical_hash

        config["config_hash"] = canonical_hash(hashed)
        self.registry.insert_experiment(config)
        return self.experiment_detail(config["experiment_id"])

    def _managed_state(self, config: dict, blockers: list[dict], jobs: list[dict], preflights: list[dict]) -> tuple[str, str]:
        if jobs:
            state = jobs[0]["state"]
            reasons = {"queued": "Waiting for the local worker.", "running": "The local worker has claimed this job.",
                       "completed": "The managed job finished and its completion evidence was found.",
                       "failed": "The managed job ended with an error.", "stopped": "Cancelled before it started.",
                       "unknown_after_interruption": "The worker stopped mid-job; the outcome is unknown and it was not retried."}
            return state, reasons.get(state, state)
        if blockers:
            return "draft", "Saved draft. Execution is blocked by the reasons listed."
        if preflights:
            return "prepared", "A reviewed preflight exists; nothing has been executed."
        return "draft", "Saved draft; no preflight yet."

    def experiment_detail(self, experiment_id: str) -> dict:
        if experiment_id.startswith("imp_"):
            run = self._run_for(experiment_id)
            return {"experiment_id": experiment_id, "origin": "imported", "name": run["dirname"], "config": None,
                    "blockers": [], "preflights": [], "jobs": [], "run": run, "runs": [run],
                    "display_state": run["display_state"], "display_state_reason": run["display_state_reason"],
                    "preparation_status": None, "synthetic_label": SYNTHETIC_RESPONSE_LABEL}
        config = self.registry.experiment(experiment_id)
        if config is None:
            raise not_found("unknown_experiment", f"No experiment {experiment_id}")
        blockers = self.draft_blockers(config)
        preflights = self.registry.preflights_for(experiment_id)
        jobs = self.registry.jobs_for(experiment_id)
        runs = self._managed_runs(experiment_id)
        state, reason = self._managed_state(config, blockers, jobs, preflights)
        runtime = self.runtime.file_status()
        prep = "blocked_by_config" if blockers else ("ready_for_preflight" if runtime["files_ready"] else "blocked_by_dependencies")
        return {"experiment_id": experiment_id, "origin": "managed", "name": config["name"], "config": config,
                "blockers": blockers, "preflights": preflights, "jobs": jobs, "run": runs[0] if runs else None, "runs": runs,
                "display_state": state, "display_state_reason": reason, "preparation_status": prep,
                "dependency_reasons": runtime["reasons"] if prep == "blocked_by_dependencies" else [],
                "synthetic_label": SYNTHETIC_RESPONSE_LABEL}

    def experiments(self) -> dict:
        items = []
        for config in self.registry.experiments():
            detail = self.experiment_detail(config["experiment_id"])
            items.append({"experiment_id": config["experiment_id"], "origin": "managed", "name": config["name"],
                          "kind": config["mode"], "display_state": detail["display_state"],
                          "display_state_reason": detail["display_state_reason"], "model": config.get("model"),
                          "evidence_kind": None, "created_at": config["created_at"], "trial_count": len(config["realized_ids"]),
                          "differing_values": None})
        for run in self.imported_runs():
            items.append({"experiment_id": run["experiment_id"], "origin": "imported", "name": run["dirname"],
                          "kind": run["kind"], "display_state": run["display_state"],
                          "display_state_reason": run["display_state_reason"], "model": run["model"],
                          "evidence_kind": run["evidence_kind"], "created_at": None, "trial_count": len(run["trials"]),
                          "differing_values": run["differing_values_recomputed"]})
        return {"items": items, "total": len(items), "synthetic_label": SYNTHETIC_RESPONSE_LABEL}

    def _provider_credentials_present(self, model: str | None) -> bool:
        import os

        envs = (runner_constants(self.settings)["provider_env"] or {}).get((model or "/").split("/", 1)[0], [])
        return any(os.environ.get(name) for name in envs)

    def _require_runtime_ready(self) -> None:
        status = self.runtime.file_status()
        if not status["files_ready"]:
            raise unavailable("runtime_unavailable", "The MatrAIx runtime is not available.", {"reasons": status["reasons"]})
        if status["probe"]["status"] != "passed":
            probe = self.runtime.probe()
            if probe["status"] != "passed":
                raise unavailable("runtime_probe_failed", "The runtime interpreter could not import MatrAIx.",
                                  {"detail": probe.get("detail"), "log": probe.get("log_relpath")})

    def preflight(self, experiment_id: str) -> dict:
        import json
        import secrets

        from societytwin.common import canonical_hash

        if experiment_id.startswith("imp_"):
            raise conflict("imported_runs_are_read_only", "Imported runs are evidence; create a new draft instead.")
        config = self.registry.experiment(experiment_id)
        if config is None:
            raise not_found("unknown_experiment", f"No experiment {experiment_id}")
        blockers = self.draft_blockers(config)
        if blockers:
            raise conflict("draft_not_executable", "This draft cannot be prepared for execution.", {"blockers": blockers})
        self._require_runtime_ready()
        task_hash = self.runtime.task_content_hash()
        if config["task"]["content_hash"] and task_hash != config["task"]["content_hash"]:
            raise conflict("stale_task", "The external task content changed after this draft was saved; create a new draft.")
        mode = config["mode"]
        nonce = secrets.token_hex(8)
        out = self.settings.managed_experiments_dir / experiment_id / f"preflight_{nonce}"
        log = self.settings.state_dir / "logs" / f"{experiment_id}_preflight_{nonce}.log"
        trials, warnings, execution_blockers = [], [], []
        output_cap, token_estimate, estimate_method = None, None, None
        runner_credentials = None
        if mode in {"preflight", "legacy_ab_live"}:
            result = self.runtime.run_ab_prepare(out, config["model"], config["temperature"], log)
            if not result.ok:
                raise invalid("preflight_rejected_by_runner", "The existing A/B runner rejected this configuration (no calls were made).",
                              {"runner_message": result.error_tail, "log": result.log_relpath})
            raw = json.loads((out / "preflight.json").read_text(encoding="utf-8"))
            expected = {s["persona_id"]: s["sha256"] for s in config["persona_artifact_hashes"]}
            for t in raw.get("trials", []):
                if t.get("persona_id") not in expected or t.get("sha256") != expected[t["persona_id"]]:
                    raise conflict("preflight_persona_mismatch", "The runner prepared personas that differ from the reviewed fixture hashes.")
                trials.append({"label": t["label"], "persona_id": t["persona_id"], "persona_sha256": t["sha256"],
                               "prompt_visible_fields": sorted(t.get("dimensions", {})), "dimensions": t.get("dimensions", {}),
                               "system_prompt": t.get("system"), "user_prompt": t.get("user"),
                               "system_sha256": sha256_bytes(t["system"].encode()), "user_sha256": sha256_bytes(t["user"].encode()),
                               "input_token_estimate": t.get("estimated_input_tokens_chars_div_4")})
            if raw.get("calls_planned") != 2 or raw.get("automatic_retries") != 0 or raw.get("task") != config["task"]["task_path"]:
                raise conflict("preflight_plan_unexpected", "The runner's plan does not match the fixed two-call, zero-retry survey path.")
            output_cap = raw.get("max_output_tokens_per_call")
            token_estimate = sum(t["input_token_estimate"] or 0 for t in trials)
            estimate_method = "Characters ÷ 4 heuristic computed by the runner; not a tokenizer count."
            runner_credentials = raw.get("credentials_present")
            planned_provider_calls = 2
            if mode == "legacy_ab_live":
                if not self.settings.live_execution_enabled:
                    execution_blockers.append({"code": "live_execution_disabled",
                                               "message": "Live execution is disabled in this release (SOCIETYTWIN_ENABLE_LIVE_EXECUTION is not set). "
                                                          "It has not been exercised against a provider here."})
                if not self._provider_credentials_present(config["model"]):
                    execution_blockers.append({"code": "credentials_missing",
                                               "message": "No key for this provider is present in the API server's environment (checked as a boolean only)."})
            else:
                execution_blockers.append({"code": "nothing_to_execute", "message": "Preflight mode prepares and reviews only."})
            if output_cap is None:
                warnings.append("The runner enforces no output-token cap for this provider; only Anthropic is capped (2048).")
        else:
            planned_provider_calls = 0
            sel = config["persona_artifact_hashes"][0]
            import yaml

            dims = (yaml.safe_load(self._recorded_file_bytes(sel["path"]).decode("utf-8")) or {}).get("dimensions", {})
            trials.append({"label": "001", "persona_id": sel["persona_id"], "persona_sha256": sel["sha256"],
                           "prompt_visible_fields": sorted(dims), "dimensions": {k: str(v) for k, v in dims.items()},
                           "system_prompt": None, "user_prompt": None, "system_sha256": None, "user_sha256": None,
                           "input_token_estimate": None})
            warnings.append("Smoke prompts are captured at the fake transport boundary during the run; they are not rendered in advance.")
        readiness = self.runtime.file_status()
        plan = {
            "experiment_id": experiment_id,
            "config_hash": config["config_hash"],
            "mode": mode,
            "realized_ids": config["realized_ids"],
            "task_hash": task_hash,
            "task_path": config["task"]["task_path"],
            "instrument_id": config["task"]["instrument_id"],
            "model": config["model"] if mode != "smoke" else "smoke/fake",
            "temperature": config["temperature"],
            "trials": trials,
            "prompt_hashes": [h for t in trials for h in (t["system_sha256"], t["user_sha256"]) if h],
            "planned_provider_calls": planned_provider_calls,
            "planned_logical_calls": 1 if mode == "smoke" else 2,
            "calls_limit": config["calls_limit"],
            "automatic_retries": 0,
            "output_token_cap": output_cap,
            "input_token_estimate": token_estimate,
            "estimate_method": estimate_method,
            "cost_estimate_usd": 0.0 if mode == "smoke" else None,
            "cost_source": "No provider calls (fake transport)." if mode == "smoke" else None,
            "cost_note": None if mode == "smoke" else "No verified price table is available, so no cost is estimated before the run.",
            "runner_reported_credentials_present": runner_credentials,
            "runner_credentials_note": "Reported by the runner's own preflight; the preflight subprocess receives no keys from this service.",
            "model_seed": None,
            "persona_artifact_hashes": config["persona_artifact_hashes"],
            "execution_blockers": execution_blockers,
            "dependency_readiness": {
                "runtime_files_ready": True,
                "runtime_probe": readiness["probe"]["status"],
                "probe_checked_at": readiness["probe"]["checked_at"],
                "matraix_root_source": readiness["matraix_root_source"],
                "provider_key_present": self._provider_credentials_present(config["model"]) if mode == "legacy_ab_live" else None,
                "live_execution_enabled": self.settings.live_execution_enabled if mode == "legacy_ab_live" else None,
                "note": "Recorded when the plan was made; execution re-checks readiness and credentials.",
            },
            "warnings": warnings,
            "stale_policy": "Invalid if the draft config, a fixture persona file or the external task content changes; "
                            "re-checked at execution. One reviewed plan executes at most once.",
            "preflight_output_rel": out.relative_to(self.settings.state_dir).as_posix() if out.exists() else None,
            "nonce": nonce,
            "provider_calls_made": 0,
            "limitations": [
                "Two trials cannot establish causality, population validity or statistical significance.",
                "The two fixture personas differ in age band and marital status, not in a single attribute.",
            ],
            "synthetic_label": SYNTHETIC_RESPONSE_LABEL,
        }
        plan["preflight_hash"] = canonical_hash({k: v for k, v in plan.items() if k != "preflight_output_rel"})
        plan["created_at"] = utc_now()
        self.registry.insert_preflight(plan)
        return plan

    def _assert_fresh(self, config: dict, plan: dict) -> None:
        if plan["config_hash"] != config["config_hash"]:
            raise conflict("stale_preflight", "The draft configuration differs from the reviewed plan.")
        current = self._current_fixture_hashes(config["persona_artifact_hashes"])
        if any(c["sha256"] != r["sha256"] for c, r in zip(current, plan["persona_artifact_hashes"])):
            raise conflict("stale_preflight", "A fixture persona file changed after the plan was reviewed.")
        if plan["task_hash"] != self.runtime.task_content_hash():
            raise conflict("stale_preflight", "The external task content changed after the plan was reviewed.")

    def execute(self, experiment_id: str, request) -> dict:
        from societytwin.registry.store import Conflict

        config = self.registry.experiment(experiment_id)
        if config is None:
            raise not_found("unknown_experiment", f"No managed experiment {experiment_id}")
        plan = self.registry.preflight(request.preflight_hash)
        if plan is None or plan["experiment_id"] != experiment_id:
            raise not_found("unknown_preflight", "No such reviewed plan for this experiment.")
        if plan["mode"] == "preflight":
            raise conflict("nothing_to_execute", "This draft's mode is preflight-only.")
        if request.mode != plan["mode"]:
            raise conflict("mode_mismatch", f"The reviewed plan is for mode {plan['mode']}.")
        blockers = self.draft_blockers(config)
        if blockers:
            raise conflict("draft_not_executable", "This draft cannot be executed.", {"blockers": blockers})
        self._assert_fresh(config, plan)
        if plan["mode"] == "legacy_ab_live":
            if not self.settings.live_execution_enabled:
                raise conflict("live_execution_disabled", "Live execution is disabled in this release.")
            if not self._provider_credentials_present(config["model"]):
                raise conflict("credentials_missing", "No key for this provider is present in the server environment.")
        self._require_runtime_ready()
        job_id = new_id("job")
        output_rel = f"experiments/{experiment_id}/{job_id}"
        if (self.settings.state_dir / output_rel).exists():
            raise conflict("output_exists", "The managed output directory already exists.")
        try:
            job, created = self.registry.create_job({"job_id": job_id, "experiment_id": experiment_id,
                                                     "preflight_hash": plan["preflight_hash"], "mode": plan["mode"],
                                                     "idempotency_key": request.idempotency_key, "output_rel": output_rel})
        except Conflict as exc:
            raise conflict(exc.code, str(exc)) from exc
        return {"job": job, "created": created}

    def cancel(self, experiment_id: str, job_id: str) -> dict:
        job = self.registry.job(job_id)
        if job is None or job["experiment_id"] != experiment_id:
            raise not_found("unknown_job", "No such job for this experiment.")
        if job["state"] == "queued" and self.registry.cancel_queued(job_id):
            return {"job": self.registry.job(job_id), "cancelled": True}
        if job["state"] == "running":
            raise conflict("cancel_not_supported_while_running",
                           "Running jobs are not interrupted: a provider request that was already sent cannot be retracted.")
        raise conflict("job_already_finished", f"The job is already {job['state']}.")

    def run_job(self, job: dict) -> None:
        """Called by the single local worker after it claimed ``job``. Never retries."""
        import json
        import os

        from societytwin.common import redact

        try:
            plan = self.registry.preflight(job["preflight_hash"])
            out = self.settings.state_dir / job["output_rel"]
            log = self.settings.state_dir / "logs" / f"{job['job_id']}.log"
            if job["mode"] == "smoke":
                result = self.runtime.run_smoke(out, log)
            elif job["mode"] == "legacy_ab_live":
                envs = (runner_constants(self.settings)["provider_env"] or {}).get(plan["model"].split("/", 1)[0], [])
                creds = {name: os.environ[name] for name in envs if os.environ.get(name)}
                self.registry.mark_provider_window_open(job["job_id"])
                result = self.runtime.run_ab_execute(out, plan["model"], plan["temperature"], log, creds)
            else:
                self.registry.finish_job(job["job_id"], "failed", "unsupported_mode", "Unsupported mode")
                return
            if not result.ok:
                code = "runner_timeout" if result.timed_out else "runner_exit_nonzero"
                note = "" if job["mode"] == "smoke" else " The provider-side outcome of any request already started is unknown."
                self.registry.finish_job(job["job_id"], "failed", code, (result.error_tail or "Runner failed") + note)
                return
            if job["mode"] == "smoke":
                report = json.loads((out / "smoke_report.json").read_text(encoding="utf-8"))
                ok = report.get("ok") is True and report.get("provider_calls") == 0
            else:
                comparison = json.loads((out / "comparison.json").read_text(encoding="utf-8"))
                ok = comparison.get("status") == "completed"
            if ok:
                self.registry.finish_job(job["job_id"], "completed")
            else:
                self.registry.finish_job(job["job_id"], "failed", "missing_completion_evidence",
                                         "The runner exited normally but its completion evidence is missing or inconsistent.")
        except Exception as exc:  # noqa: BLE001 - the worker must record every failure
            self.registry.finish_job(job["job_id"], "failed", "worker_error", redact(f"{type(exc).__name__}: {exc}", max_length=500))

    # ================================================================ results
    def trials(self, experiment_id: str, job_id: str | None = None) -> dict:
        run = self._run_for(experiment_id, job_id)
        return {"experiment_id": experiment_id, "run_experiment_id": run["experiment_id"], "origin": run["origin"],
                "evidence_kind": run["evidence_kind"], "display_state": run["display_state"], "trials": run["trials"],
                "synthetic_label": SYNTHETIC_RESPONSE_LABEL}

    def results(self, experiment_id: str, job_id: str | None = None) -> dict:
        run = self._run_for(experiment_id, job_id)
        keys = ("experiment_id", "origin", "dirname", "kind", "evidence_kind", "display_state", "display_state_reason",
                "raw_statuses", "model", "temperature", "provider", "task", "planned_calls", "recorded_calls",
                "provider_calls_recorded", "automatic_retries", "max_output_tokens_per_call", "historical_credentials_present",
                "runtime_seconds", "comparison_rows", "differing_values_recorded", "differing_values_recomputed",
                "consistency_checks", "usage", "budget_file", "limitations", "warnings", "artifacts", "files", "evidence_drift")
        out = {k: run.get(k) for k in keys}
        if run["origin"] == "managed":
            config = self.registry.experiment(experiment_id) or {}
            out["display_name"] = f"{config.get('name', experiment_id)} · {run.get('job_id')}"
        else:
            out["display_name"] = run["dirname"]
        out["trial_summaries"] = [{"label": t["label"], "persona_id": t["persona_id"], "state": t["state"],
                                   "boundary_status_raw": t["boundary_status_raw"], "answer_count": t["answer_count"],
                                   "usage": t["usage"], "coerced_answers": t["coerced_answers"],
                                   "answers": t["answers"]} for t in run["trials"]]
        out["inference_note"] = ("Two personas answering once each: differences describe these two recorded responses only. They are "
                                 "not population percentages, causal effects, significance tests or confidence intervals.")
        out["historical_credentials_note"] = "A credential flag stored in an old preflight does not show current readiness."
        out["synthetic_label"] = SYNTHETIC_RESPONSE_LABEL
        return out

    def events(self, experiment_id: str, trial_label: str | None, offset: int, limit: int, job_id: str | None = None) -> dict:
        from societytwin.experiments.evidence_files import RunFiles

        run = self._run_for(experiment_id, job_id)
        root = (self.settings.import_runs_root / run["dirname"]) if run["origin"] == "imported" else (
            self.settings.state_dir / f"experiments/{experiment_id}/{run.get('job_id')}")
        files = RunFiles(root)
        items = []
        for trial in run["trials"]:
            if trial_label and trial["label"] != trial_label or not trial["trial_dir"]:
                continue
            events, malformed = files.read_jsonl(f"{trial['trial_dir']}/events.jsonl")
            for i, event in enumerate(events or []):
                items.append({"trial_label": trial["label"], "index": i, "type": event.get("type") if isinstance(event.get("type"), str) else None,
                              "phase": event.get("phase") if isinstance(event.get("phase"), str) else None,
                              "keys": sorted(event), "content": _truncate(event)})
        return {"experiment_id": experiment_id, "items": items[offset: offset + limit], "total": len(items),
                "offset": offset, "limit": limit,
                "note": "Runtime log events written by MatrAIx. They are not a job queue and do not count provider calls."}

    def export(self, experiment_id: str, fmt: str, job_id: str | None = None) -> tuple[bytes, str, str]:
        import csv
        import io
        import json

        run = self._run_for(experiment_id, job_id)
        differs = {r["question_id"]: r["value_differs"] for r in run["comparison_rows"]}
        columns = [
            ("experiment_id", "string", "Imported or managed experiment ID"),
            ("origin", "string", "imported | managed"),
            ("evidence_kind", "string", "live | fake | unknown"),
            ("trial_label", "string", "Trial folder label"),
            ("persona_id", "string", "Synthetic resident ID"),
            ("question_id", "string", "Instrument question ID"),
            ("value", "json", "Answer value exactly as recorded (JSON-encoded)"),
            ("label", "string|null", "Choice label from the trial's questionnaire snapshot; null when not listed"),
            ("rationale", "string|null", "Recorded rationale; null when empty or absent"),
            ("confidence", "number|null", "Recorded confidence; null when absent"),
            ("value_differs", "boolean|null", "A/B only: recomputed from the two trial results"),
            ("model", "string|null", "Model identifier as recorded"),
            ("data_label", "string", "Synthetic-data label"),
        ]
        rows = []
        for trial in run["trials"]:
            for answer in trial["answers"] or []:
                rows.append({"experiment_id": experiment_id, "origin": run["origin"], "evidence_kind": run["evidence_kind"],
                             "trial_label": trial["label"], "persona_id": trial["persona_id"], "question_id": answer["question_id"],
                             "value": json.dumps(answer["value"], ensure_ascii=False), "label": answer["label"],
                             "rationale": answer["rationale"], "confidence": answer["confidence"],
                             "value_differs": differs.get(answer["question_id"]) if run["kind"] == "legacy_ab" else None,
                             "model": run["model"], "data_label": SYNTHETIC_RESPONSE_LABEL})
        name = f"societytwin_{experiment_id.replace(':', '_')}"
        if fmt == "json":
            payload = {
                "synthetic_label": SYNTHETIC_RESPONSE_LABEL,
                "exported_at": utc_now(),
                "experiment": {k: run[k] for k in ("experiment_id", "origin", "kind", "evidence_kind", "display_state",
                                                    "raw_statuses", "model", "temperature", "task", "differing_values_recorded",
                                                    "differing_values_recomputed", "limitations")},
                "usage": run["usage"],
                "provenance": {"file_sha256": run["file_hashes"],
                               "persona_snapshots": {t["label"]: (t["persona_snapshot"] or {}).get("sha256") for t in run["trials"]},
                               "prompt_sha256": {t["label"]: {"system": (t["prompts"] or {}).get("system_sha256"),
                                                              "user": (t["prompts"] or {}).get("user_sha256")} for t in run["trials"]}},
                "schema": [{"name": n, "type": t, "description": d} for n, t, d in columns],
                "unknown_value_policy": "null means unknown or not recorded; nothing is zero-filled. Costs are estimates unless "
                                        "billed_cost_usd is set, which these runners never record.",
                "inference_note": "Descriptive record of recorded responses; not population estimates or causal effects.",
                "rows": rows,
            }
            return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json", f"{name}.json"
        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=[c[0] for c in columns], lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
            return buffer.getvalue().encode("utf-8"), "text/csv; charset=utf-8", f"{name}.csv"
        raise invalid("unsupported_format", "Supported export formats: csv, json (Parquet is not implemented).")

    def artifact(self, artifact_id: str) -> tuple[bytes, str, str, str | None]:
        from societytwin.experiments.evidence_files import MAX_ARTIFACT_BYTES, RunFiles

        candidates = [(run, self.settings.import_runs_root / run["dirname"]) for run in self.imported_runs()]
        for config in self.registry.experiments():
            for run in self._managed_runs(config["experiment_id"]):
                candidates.append((run, self.settings.state_dir / f"experiments/{config['experiment_id']}/{run['job_id']}"))
        for run, root in candidates:
            for art in run["artifacts"]:
                if art["artifact_id"] == artifact_id:
                    data = RunFiles(root).read_bytes(art["relpath"], limit=MAX_ARTIFACT_BYTES)
                    if data is None:
                        raise not_found("artifact_unavailable", "The artifact is no longer readable at its registered location.")
                    return data, art["media_type"], Path(art["relpath"]).name, art.get("caveat")
        raise not_found("unknown_artifact", "No artifact with this ID.")

    # ================================================================ capabilities
    def capabilities(self) -> dict:
        import os

        runtime = self.runtime.file_status()
        runner = runner_constants(self.settings)
        builds = self.list_builds()
        presence = {p: any(os.environ.get(k) for k in envs) for p, envs in (runner["provider_env"] or {}).items()}
        live_reasons = []
        if not self.settings.live_execution_enabled:
            live_reasons.append("Disabled by default in this release: live execution has not been exercised against a provider here "
                                "(set SOCIETYTWIN_ENABLE_LIVE_EXECUTION=1 only after reviewing docs/research-workbench.md).")
        if not runtime["ready"]:
            live_reasons.extend(runtime["reasons"])
        if not any(presence.values()):
            live_reasons.append("No provider key is present in the server environment.")
        mutation_note = "Mutations are accepted from loopback clients only." if self.settings.local_mutations else "Mutations are disabled."
        return {
            "api": {"status": "ok", "version": "v1"},
            "data": {"builds": [{"build_id": b["build_id"], "variant": b["variant"], "availability": b["availability"]["status"],
                                 "filterable_fields": b["filterable_fields"], "available_fields": b["available_fields"],
                                 "unavailable_fields": b["unavailable_fields"]} for b in builds["items"]],
                     "default_build_id": builds["default_build_id"], "load_errors": builds["load_errors"],
                     "imported_runs_root_present": self.settings.import_runs_root.is_dir()},
            "runtime": runtime,
            "credentials": {"provider_key_present": presence,
                            "note": "Booleans from the API server environment only; values are never read into responses. "
                                    "A key in the experiment .env is read by the runner itself and is not inspected here."},
            "modes": {
                "browse_offline": {"available": True, "reasons": []},
                "preflight": {"available": runtime["files_ready"], "reasons": [] if runtime["files_ready"] else runtime["reasons"]},
                "smoke": {"available": runtime["files_ready"], "reasons": [] if runtime["files_ready"] else runtime["reasons"]},
                "legacy_ab_live": {"available": not live_reasons, "reasons": live_reasons},
                "cohort_execution": {"available": False, "reasons": ["No verified runner accepts arbitrary cohorts or persona paths."]},
                "scenario_execution": {"available": False, "reasons": ["Scenarios are saved drafts only."]},
                "stratified_sampling": {"available": False, "reasons": ["No tested stratified design (allocation, empty strata, weights) is implemented."]},
                "persona_materialization": {"available": runtime["files_ready"], "reasons": [] if runtime["files_ready"] else runtime["reasons"]},
                "cancel": {"available": True, "reasons": ["Queued jobs only; running jobs are never interrupted."]},
                "reproduce": {"available": False, "reasons": ["No response cache exists; viewing or exporting history is not reproduction."]},
                "export_parquet": {"available": False, "reasons": ["Only CSV and JSON exports are implemented."]},
            },
            "mutations": {"local_only": self.settings.local_mutations, "note": mutation_note},
            "runner": {"provider_prefixes": runner["provider_prefixes"] or [], "fixed_persona_ids": runner["expected_ids"] or [],
                       "note": "Read statically from the existing A/B runner source; this list does not show that any model is available."},
        }


def _truncate(value, limit: int = 4000):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"… [{len(value) - limit} more characters]"
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v, limit) for v in value[:200]]
    return value


def _tasks_and_environments(workbench: "Workbench") -> tuple[dict, dict]:
    snapshot_sources, counts = [], set()
    for run in workbench.imported_runs():
        for trial in run["trials"]:
            if trial["questionnaire"]:
                snapshot_sources.append(f"{run['experiment_id']}/{trial['label']}")
                counts.add(len(trial["questionnaire"]["questions"]))
    content_hash = workbench.runtime.task_content_hash()
    tasks = {"items": [{
        "id": "product_feedback_v1", "instrument_id": "product_feedback_v1", "title": "Survey Product Feedback (MatrAIx example)",
        "task_path": "application/tasks/example-survey_product-feedback", "origin": "external MatrAIx checkout (not vendored)",
        "question_count_from_snapshots": counts.pop() if len(counts) == 1 else None,
        "external_content_available": content_hash is not None, "content_hash": content_hash,
        "snapshot_sources": snapshot_sources,
        "executable_modes": ["preflight", "smoke", "legacy_ab_live"],
        "notes": ["The original task YAML lives in the external MatrAIx checkout; historical runs carry Markdown snapshots of its "
                  "instruction, questionnaire and output schema.",
                  "Viewing history needs only those snapshots; a new preflight needs the external task content.",
                  "This is MatrAIx's example product survey, not a Türkiye-specific instrument."],
    }], "scenario_kinds": [
        {"kind": "none", "status": "executable", "description": "No scenario manipulation: the task is presented unchanged."},
        {"kind": "draft", "status": "draft_only", "description": "A typed scenario text saved with the draft. The fixed runner cannot apply it, so execution is disabled."},
    ]}
    envs = {"items": [
        {"name": "SURVEY", "status": "executable", "description": "Structured questionnaire answered by a persona-conditioned survey agent (MatrAIx PersonaJsonSurvey).",
         "modes": ["preflight", "smoke", "legacy_ab_live"], "reasons": []},
        {"name": "SCENARIO", "status": "draft_only", "description": "Personas respond to a controlled hypothetical situation (proposed in docs).",
         "modes": [], "reasons": ["No scenario executor exists; drafts can be saved for design review only."]},
    ]}
    return tasks, envs


Workbench.tasks_and_environments = _tasks_and_environments  # type: ignore[attr-defined]
