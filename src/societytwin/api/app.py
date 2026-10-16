"""FastAPI application. Handlers validate input, call the workbench and shape errors; nothing else."""


import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from societytwin import __version__
from societytwin.api import schemas as S
from societytwin.common import redact, utc_now
from societytwin.config import Settings, load_settings
from societytwin.errors import WorkbenchError
from societytwin.experiments.models import (
    CohortCreateRequest,
    CohortPreviewRequest,
    ExecuteRequest,
    ExperimentDraftRequest,
)
from societytwin.sampling.filters import AgeGroup, FilterSpec, Gender, MaritalStatus
from societytwin.sampling.query import MAX_PAGE_SIZE, SortField
from societytwin.workbench import Workbench

STATUS_FOR_KIND = {"not_found": 404, "invalid": 422, "conflict": 409, "unavailable": 503, "not_implemented": 501, "forbidden": 403}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ERRORS = {code: {"model": S.ErrorResponse} for code in (403, 404, 409, 422, 501, 503)}


def _error(request: Request, status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": redact(message, max_length=1000),
                      "request_id": getattr(request.state, "request_id", "unknown")}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status, headers={"X-Request-ID": body["error"]["request_id"]})


def create_app(settings: Settings | None = None, workbench: Workbench | None = None,
               start_worker: bool | None = None, loopback_hosts: tuple[str, ...] = ("127.0.0.1", "::1")) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        wb = workbench or Workbench(settings)
        app.state.workbench = wb
        worker = None
        if settings.start_worker if start_worker is None else start_worker:
            from societytwin.worker import LocalWorker

            worker = LocalWorker(wb)
            worker.start()
        app.state.worker = worker
        try:
            yield
        finally:
            if worker:
                worker.stop()
            if workbench is None:
                wb.close()

    app = FastAPI(
        title="SocietyTwin research workbench API",
        version=__version__,
        description=("Local development service. Read endpoints work offline from the supplied fixtures and recorded runs. "
                     "Mutations are accepted from loopback clients only; this is not an authenticated deployment. "
                     "Synthetic personas and AI-generated responses. Not real people. Not a prediction of real behaviour."),
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.frontend_origins), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"], allow_credentials=False)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:16]
        if request.method in MUTATING:
            if not settings.local_mutations:
                return _error(request, 403, "mutations_disabled", "This service is configured read-only.")
            host = request.client.host if request.client else None
            if host not in loopback_hosts:
                return _error(request, 403, "mutations_local_only", "Mutations are accepted from loopback clients only.")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(WorkbenchError)
    async def workbench_error(request: Request, exc: WorkbenchError):
        return _error(request, STATUS_FOR_KIND[exc.kind], exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"loc": [str(x) for x in e.get("loc", ())], "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _error(request, 422, "invalid_request", "The request did not validate.", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        return _error(request, 500, "internal_error", "Unexpected server error; see the server log for this request ID.")

    def wb(request: Request) -> Workbench:
        return request.app.state.workbench

    WB = Annotated[Workbench, Depends(wb)]

    def filter_params(
        person_id: Annotated[list[str] | None, Query(description="Exact resident ID; repeat for several")] = None,
        age_group: Annotated[list[AgeGroup] | None, Query()] = None,
        gender: Annotated[list[Gender] | None, Query(description="Administrative sex category")] = None,
        marital_status: Annotated[list[MaritalStatus] | None, Query(description="Source TÜİK label (v2 only)")] = None,
    ) -> FilterSpec:
        try:
            return FilterSpec(person_ids=person_id, age_groups=age_group, genders=gender, marital_statuses=marital_status)
        except ValueError as exc:
            raise WorkbenchError("invalid", "invalid_filter", "Invalid filter", [str(exc)]) from exc

    Filters = Annotated[FilterSpec, Depends(filter_params)]
    v1 = "/api/v1"

    @app.get(f"{v1}/health", response_model=S.Health, tags=["system"])
    def health():
        return {"status": "ok", "version": __version__, "time": utc_now(),
                "note": "API liveness only. Data, catalog, task, runtime and credential readiness are in /capabilities."}

    @app.get(f"{v1}/capabilities", response_model=S.Capabilities, tags=["system"])
    def capabilities(w: WB):
        return w.capabilities()

    @app.post(f"{v1}/runtime/probe", response_model=S.ProbeStatus, responses=ERRORS, tags=["system"])
    def runtime_probe(w: WB):
        status = w.runtime.file_status()
        if not status["files_ready"]:
            raise WorkbenchError("unavailable", "runtime_unavailable", "Runtime files are not ready.", {"reasons": status["reasons"]})
        return w.runtime.probe()

    @app.get(f"{v1}/builds", response_model=S.BuildList, tags=["population"])
    def builds(w: WB):
        return w.list_builds()

    @app.get(f"{v1}/builds/{{build_id}}", response_model=S.BuildDescriptor, responses=ERRORS, tags=["population"])
    def build(build_id: str, w: WB):
        return w.get_build(build_id)

    @app.get(f"{v1}/builds/{{build_id}}/records", response_model=S.RecordsPage, responses=ERRORS, tags=["population"])
    def records(build_id: str, w: WB, filters: Filters, sort: SortField = "person_id",
                direction: Literal["asc", "desc"] = "asc", offset: Annotated[int, Query(ge=0)] = 0,
                limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50):
        return w.records(build_id, filters, sort, direction, offset, limit)

    @app.get(f"{v1}/builds/{{build_id}}/summary", response_model=S.Summary, responses=ERRORS, tags=["population"])
    def summary(build_id: str, w: WB, filters: Filters,
                group_by: Annotated[list[Literal["age_group", "gender", "marital_status", "marital_status_conditioning"]] | None, Query()] = None,
                crosstab: bool = False):
        return w.summary(build_id, filters, group_by, crosstab)

    @app.get(f"{v1}/builds/{{build_id}}/validation", response_model=S.ValidationReport, responses=ERRORS, tags=["validation"])
    def validation(build_id: str, w: WB):
        return w.validation(build_id)

    @app.post(f"{v1}/cohorts/preview", response_model=S.CohortPreview, responses=ERRORS, tags=["cohorts"])
    def cohort_preview(body: CohortPreviewRequest, w: WB):
        return w.preview_cohort(body.build_id, body.filters)

    @app.post(f"{v1}/cohorts", response_model=S.CohortManifest, status_code=201, responses=ERRORS, tags=["cohorts"])
    def cohort_create(body: CohortCreateRequest, w: WB):
        return w.create_cohort(body)

    @app.get(f"{v1}/cohorts", response_model=S.CohortList, tags=["cohorts"])
    def cohort_list(w: WB):
        return w.cohorts()

    @app.get(f"{v1}/cohorts/{{cohort_id}}", response_model=S.CohortManifest, responses=ERRORS, tags=["cohorts"])
    def cohort_get(cohort_id: str, w: WB):
        return w.cohort(cohort_id)

    @app.get(f"{v1}/personas/{{build_id}}", response_model=S.PersonaIndex, responses=ERRORS, tags=["personas"])
    def persona_index(build_id: str, w: WB):
        return w.persona_index(build_id)

    @app.get(f"{v1}/personas/{{build_id}}/{{record_id}}", response_model=S.PersonaView, responses=ERRORS, tags=["personas"])
    def persona(build_id: str, record_id: str, w: WB):
        return w.persona_view(build_id, record_id)

    @app.post(f"{v1}/personas/{{build_id}}/{{record_id}}/materialize", response_model=S.PersonaView, responses=ERRORS, tags=["personas"])
    def persona_materialize(build_id: str, record_id: str, w: WB):
        return w.materialize_persona(build_id, record_id)

    @app.get(f"{v1}/tasks", response_model=S.TaskList, tags=["experiments"])
    def tasks(w: WB):
        return w.tasks_and_environments()[0]

    @app.get(f"{v1}/environments", response_model=S.EnvironmentList, tags=["experiments"])
    def environments(w: WB):
        return w.tasks_and_environments()[1]

    @app.get(f"{v1}/datasets", response_model=S.Datasets, tags=["validation"])
    def datasets(w: WB):
        return w.datasets()

    @app.post(f"{v1}/experiments", response_model=S.ExperimentDetail, status_code=201, responses=ERRORS, tags=["experiments"],
              description="Creates a saved draft only. Unlike the proposed docs' create-and-queue, nothing is queued or run here.")
    def experiment_create(body: ExperimentDraftRequest, w: WB):
        return w.create_draft(body)

    @app.get(f"{v1}/experiments", response_model=S.ExperimentList, tags=["experiments"])
    def experiment_list(w: WB):
        return w.experiments()

    @app.get(f"{v1}/experiments/{{experiment_id}}", response_model=S.ExperimentDetail, responses=ERRORS, tags=["experiments"])
    def experiment_get(experiment_id: str, w: WB):
        return w.experiment_detail(experiment_id)

    @app.post(f"{v1}/experiments/{{experiment_id}}/preflight", response_model=S.Preflight, status_code=201, responses=ERRORS, tags=["experiments"],
              description="Validates the draft and records an immutable reviewed plan. Makes zero provider calls.")
    def experiment_preflight(experiment_id: str, w: WB):
        return w.preflight(experiment_id)

    @app.post(f"{v1}/experiments/{{experiment_id}}/execute", response_model=S.ExecuteResponse, status_code=202, responses=ERRORS, tags=["experiments"])
    def experiment_execute(experiment_id: str, body: ExecuteRequest, w: WB):
        return w.execute(experiment_id, body)

    @app.post(f"{v1}/experiments/{{experiment_id}}/jobs/{{job_id}}/cancel", response_model=S.CancelResponse, responses=ERRORS, tags=["experiments"])
    def experiment_cancel(experiment_id: str, job_id: str, w: WB):
        return w.cancel(experiment_id, job_id)

    @app.post(f"{v1}/experiments/{{experiment_id}}/reproduce", responses={501: {"model": S.ErrorResponse}}, tags=["experiments"])
    def experiment_reproduce(experiment_id: str):
        raise WorkbenchError("not_implemented", "reproduce_unavailable",
                             "No response cache exists, so exact replay is impossible. Viewing or exporting history is not reproduction.")

    @app.get(f"{v1}/experiments/{{experiment_id}}/trials", response_model=S.Trials, responses=ERRORS, tags=["results"])
    def experiment_trials(experiment_id: str, w: WB, job_id: str | None = None):
        return w.trials(experiment_id, job_id)

    @app.get(f"{v1}/experiments/{{experiment_id}}/results", response_model=S.Results, responses=ERRORS, tags=["results"])
    def experiment_results(experiment_id: str, w: WB, job_id: str | None = None):
        return w.results(experiment_id, job_id)

    @app.get(f"{v1}/experiments/{{experiment_id}}/events", response_model=S.Events, responses=ERRORS, tags=["results"])
    def experiment_events(experiment_id: str, w: WB, trial: str | None = None, job_id: str | None = None,
                          offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50):
        return w.events(experiment_id, trial, offset, limit, job_id)

    @app.get(f"{v1}/experiments/{{experiment_id}}/export", responses={200: {"content": {"text/csv": {}, "application/json": {}}}, **ERRORS},
             tags=["results"], response_class=Response)
    def experiment_export(experiment_id: str, w: WB, format: Literal["csv", "json"] = "csv", job_id: str | None = None):
        data, media_type, filename = w.export(experiment_id, format, job_id)
        return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                                              "X-SocietyTwin-Data-Label": "synthetic"})

    @app.get(f"{v1}/artifacts/{{artifact_id}}", responses={200: {"content": {"application/octet-stream": {}}}, **ERRORS},
             tags=["results"], response_class=Response)
    def artifact(artifact_id: str, w: WB, download: bool = False):
        data, media_type, filename, caveat = w.artifact(artifact_id)
        headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
                   "Content-Disposition": f'{"attachment" if download or media_type == "application/pdf" else "inline"}; filename="{filename}"'}
        if caveat:
            headers["X-SocietyTwin-Caveat"] = "historical-descriptive-report"
        return Response(data, media_type=media_type, headers=headers)

    return app


def app_factory() -> FastAPI:  # used by `uvicorn --factory societytwin.api.app:app_factory`
    return create_app()
