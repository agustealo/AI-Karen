from __future__ import annotations

from typing import Any
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException, Query
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
from ai_karen_engine.core.intelligence.ml.training.artifact_reconciliation import TrainingArtifactReconciler

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.training.dataset_import import (
    DatasetImportError, import_jsonl_dataset, list_tenant_dataset_versions,
)
from ai_karen_engine.core.intelligence.ml.training.workbench import AdvancedTrainingWorkbench
from ai_karen_engine.auth.rbac_middleware import Permission, require_permission
from ai_karen_engine.services.admin.admin_training_control_service import (
    AdminTrainingControlService,
)

router = APIRouter(prefix="/admin/training", tags=["admin-training"])

_WORKER_REQUIREMENTS = {
    "transformers": ("torch", "transformers", "peft", "accelerate", "safetensors"),
    "timeseries": ("numpy", "sklearn"),
    "spacy": ("spacy",),
    "sklearn": ("sklearn",),
}


class TrainingControlPlaneResponse(BaseModel):
    architecture: dict[str, Any]
    prediction_tasks: list[str]
    lanes: list[dict[str, Any]]
    registry: dict[str, Any]
    governance: dict[str, Any]


class TrainingCapabilityResponse(BaseModel):
    lane_id: str
    title: str
    category: str
    authority: str
    module: str
    mode: str
    description: str
    human_like_role: str
    prediction_task: str | None = None
    available: bool
    model_count: int = 0
    active_model_count: int = 0
    shadow_model_count: int = 0
    candidate_model_count: int = 0


def get_admin_training_control_service() -> AdminTrainingControlService:
    return AdminTrainingControlService()


@router.get("/control-plane", response_model=TrainingControlPlaneResponse)
async def get_training_control_plane(
    current_user: dict[str, Any] = Depends(
        require_permission(Permission.TRAINING_READ)
    ),
    service: AdminTrainingControlService = Depends(
        get_admin_training_control_service
    ),
) -> TrainingControlPlaneResponse:
    del current_user
    return TrainingControlPlaneResponse(**service.snapshot())


@router.get("/capabilities", response_model=list[TrainingCapabilityResponse])
async def list_training_capabilities(
    current_user: dict[str, Any] = Depends(
        require_permission(Permission.TRAINING_READ)
    ),
    service: AdminTrainingControlService = Depends(
        get_admin_training_control_service
    ),
) -> list[TrainingCapabilityResponse]:
    del current_user
    snapshot = service.snapshot()
    return [TrainingCapabilityResponse(**lane) for lane in snapshot["lanes"]]


class AdvancedPreflightRequest(BaseModel):
    engine: str = Field(min_length=1, max_length=40)
    task: str = Field(min_length=1, max_length=80)
    dataset_version: str = Field(min_length=1, max_length=128)
    dataset_scope: str = Field(default="legacy", pattern="^(legacy|tenant)$")
    test_split: float = 0.2
    max_samples: int = 10000
    seed: int = 42
    max_iter: int = 1000
    class_weight: str = "balanced"
    optimizer: str = "lbfgs"
    precision: str = "fp64"
    base_model_path: str | None = None
    license_id: str | None = None
    license_accepted: bool = False
    license_model_path: str | None = None
    epochs: int = Field(1, ge=1, le=10)
    sequence_length: int = Field(256, ge=32, le=2048)
    lora_rank: int = 8
    allow_cpu_training: bool = False
    lags: int = Field(5, ge=2, le=128)
    horizon: int = Field(1, ge=1, le=32)


def get_advanced_workbench() -> AdvancedTrainingWorkbench:
    return AdvancedTrainingWorkbench()


@router.get("/advanced/catalog")
async def get_advanced_training_catalog(
    current_user: dict[str, Any] = Depends(require_permission(Permission.TRAINING_READ)),
    workbench: AdvancedTrainingWorkbench = Depends(get_advanced_workbench),
    ledger: TrainingJobLedger = Depends(lambda: TrainingJobLedger()),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    catalog = workbench.catalog()
    tenant_catalog = AdvancedTrainingWorkbench.for_tenant(tenant).catalog()
    catalog["datasets"].extend({**item, "scope": "tenant"} for item in tenant_catalog["datasets"])
    for item in catalog["datasets"]:
        item.setdefault("scope", "legacy")
    evidence = ledger.worker_capabilities(tenant_id=tenant)

    for engine in catalog["engines"]:
        needed = _WORKER_REQUIREMENTS[engine["id"]]
        ready_workers = []
        for worker in evidence["workers"]:
            dependencies = worker["capabilities"].get("dependencies", {})
            if all(dependencies.get(package) is True for package in needed):
                ready_workers.append(worker["worker_id"])
        engine["supported"] = bool(ready_workers)
        engine["status"] = "ready" if ready_workers else (
            "worker_offline" if not evidence["workers"] else "missing_dependencies"
        )
        engine["missing_dependencies"] = (
            [] if not evidence["workers"] else [
                package for package in needed
                if not any(
                    worker["capabilities"].get("dependencies", {}).get(package) is True
                    for worker in evidence["workers"]
                )
            ]
        )
        engine["worker_status"] = evidence["worker_status"]
        engine["details"] += " Execution availability is determined by the tenant-scoped training worker."
    catalog["worker_status"] = evidence["worker_status"]
    return catalog


def _worker_dependencies(ledger: TrainingJobLedger, *, tenant: str, engine: str) -> dict[str, bool]:
    """Only an online worker satisfying one complete dependency set can admit work."""
    needed = _WORKER_REQUIREMENTS.get(engine, ())
    workers = ledger.worker_capabilities(tenant_id=tenant)["workers"]
    for worker in workers:
        dependencies = worker["capabilities"].get("dependencies", {})
        if needed and all(dependencies.get(item) is True for item in needed):
            return {**{item: True for item in needed}, "cuda_available": worker["capabilities"].get("cuda_available") is True}
    return {**{item: False for item in needed}, "cuda_available": False}


@router.post("/advanced/preflight")
async def preflight_advanced_training(
    body: AdvancedPreflightRequest,
    current_user: dict[str, Any] = Depends(require_permission(Permission.TRAINING_READ)),
    workbench: AdvancedTrainingWorkbench = Depends(get_advanced_workbench),
    ledger: TrainingJobLedger = Depends(lambda: TrainingJobLedger()),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    scoped_workbench = (AdvancedTrainingWorkbench.for_tenant(tenant)
                        if body.dataset_scope == "tenant" else workbench)
    payload = body.model_dump(exclude={"dataset_scope"})
    return scoped_workbench.preflight(
        **payload,
        dependency_availability=_worker_dependencies(ledger, tenant=tenant, engine=body.engine),
    )


class DatasetImportRequest(BaseModel):
    version: str = Field(min_length=1, max_length=128)
    content_jsonl: str = Field(min_length=1, max_length=32 * 1024 * 1024)


@router.get("/advanced/datasets")
async def list_scoped_training_datasets(
    current_user: Any = Depends(require_permission(Permission.TRAINING_READ)),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    root = Path(get_ml_registry_dir()) / "datasets"
    return {"datasets": list_tenant_dataset_versions(root=root, tenant_id=tenant)}


@router.post("/advanced/datasets/import", status_code=201)
async def import_scoped_training_dataset(
    body: DatasetImportRequest,
    current_user: Any = Depends(require_permission(Permission.TRAINING_EXECUTE)),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    root = Path(get_ml_registry_dir()) / "datasets"
    try:
        return import_jsonl_dataset(
            source=BytesIO(body.content_jsonl.encode("utf-8")),
            root=root,
            tenant_id=tenant,
            version=body.version,
        )
    except DatasetImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def get_training_job_ledger() -> TrainingJobLedger:
    return TrainingJobLedger()


def _identity(current_user: Any) -> tuple[str, str]:
    tenant = str((current_user.get("tenant_id") if isinstance(current_user, dict) else getattr(current_user, "tenant_id", "")) or "")
    user = str((current_user.get("user_id") if isinstance(current_user, dict) else getattr(current_user, "user_id", "")) or "")
    if not tenant or tenant == "default" or not user:
        raise HTTPException(status_code=403, detail="Explicit user and tenant context required")
    return tenant, user


@router.get("/advanced/execution-status")
async def get_training_execution_status(
    current_user: Any = Depends(require_permission(Permission.TRAINING_READ)),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    return ledger.execution_status(tenant_id=tenant)


@router.get("/advanced/jobs")
async def list_advanced_training_jobs(
    limit: int = Query(50, ge=1, le=100),
    current_user: Any = Depends(require_permission(Permission.TRAINING_READ)),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    return {"jobs": ledger.list(tenant_id=tenant, limit=limit)}


@router.get("/advanced/jobs-interrupted")
async def list_interrupted_advanced_training_jobs(
    current_user: Any = Depends(require_permission(Permission.TRAINING_READ)),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    """Operator diagnostic only. No implicit retries or unsafe job takeover."""
    tenant, _ = _identity(current_user)
    return {"jobs": ledger.interrupted(tenant_id=tenant)}


@router.get("/advanced/jobs-expired")
async def list_expired_training_leases(
    current_user: Any = Depends(require_permission(Permission.TRAINING_READ)),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    return {"jobs": ledger.expired(tenant_id=tenant)}


@router.get("/advanced/artifact-reconciliation")
async def inspect_training_artifacts(
    current_user: Any = Depends(require_permission(Permission.TRAINING_READ)),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    return TrainingArtifactReconciler(ledger=ledger).inspect(tenant_id=tenant)


@router.get("/advanced/jobs/{job_id}")
async def get_advanced_training_job(
    job_id: str,
    current_user: Any = Depends(require_permission(Permission.TRAINING_READ)),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    result = ledger.get(job_id, tenant_id=tenant)
    if result is None:
        raise HTTPException(status_code=404, detail="Training job not found")
    return result


@router.post("/advanced/jobs", status_code=201)
async def enqueue_advanced_training_job(
    body: AdvancedPreflightRequest,
    current_user: Any = Depends(require_permission(Permission.TRAINING_EXECUTE)),
    workbench: AdvancedTrainingWorkbench = Depends(get_advanced_workbench),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    tenant, user = _identity(current_user)
    scoped_workbench = (AdvancedTrainingWorkbench.for_tenant(tenant)
                        if body.dataset_scope == "tenant" else workbench)
    payload = body.model_dump(exclude={"dataset_scope"})
    check = scoped_workbench.preflight(
        **payload,
        dependency_availability=_worker_dependencies(ledger, tenant=tenant, engine=body.engine),
    )
    if not check["ready"]:
        raise HTTPException(status_code=422, detail={
            "message": "Training preflight did not pass",
            "checks": check["checks"],
        })
    job = TrainingJob(
        job_id=uuid4().hex,
        task=body.task,
        base_model=body.engine,
        dataset_version=body.dataset_version,
        seed=body.seed,
        metadata={
            "advanced_config": body.model_dump(),
            "dataset_scope": body.dataset_scope,
            "submitted_by": user,
            "tenant_id": tenant,
            "preflight": check["evidence"],
        },
    )
    return ledger.submit(job, tenant_id=tenant, user_id=user)


@router.post("/advanced/jobs/{job_id}/cancel")
async def cancel_advanced_training_job(
    job_id: str,
    current_user: Any = Depends(require_permission(Permission.TRAINING_EXECUTE)),
    ledger: TrainingJobLedger = Depends(get_training_job_ledger),
) -> dict[str, Any]:
    tenant, _ = _identity(current_user)
    if not ledger.cancel(job_id, tenant_id=tenant):
        raise HTTPException(status_code=409, detail="Job cannot be cancelled or is not queued")
    return {"job_id": job_id, "status": "CANCELLED"}



@router.post("/advanced/candidates/{model_id}/evaluate")
async def evaluate_training_candidate(
    model_id: str,
    current_user: Any = Depends(require_permission(Permission.TRAINING_EXECUTE)),
) -> dict[str, Any]:
    """Authenticated ingress delegates benchmark execution to canonical ML."""
    from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
    from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkConfig
    from ai_karen_engine.core.intelligence.ml.evaluation.runner import BenchmarkRunner
    from ai_karen_engine.core.intelligence.ml.predictors.registry_classifier import RegistryBackedClassifier
    from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
    import hashlib

    tenant, _ = _identity(current_user)
    prefix = "tenant-" + hashlib.sha256(tenant.encode("utf-8")).hexdigest()[:16] + "-"
    if not model_id.startswith(prefix):
        raise HTTPException(status_code=404, detail="Candidate not found")
    registry = MLModelRegistry()
    manifest = registry.get(model_id)
    if manifest is None or manifest.status != "CANDIDATE":
        raise HTTPException(status_code=404, detail="Candidate not found")
    if manifest.metrics.get("executor") in {"timeseries", "transformers"}:
        raise HTTPException(
            status_code=409,
            detail="Engine-specific predictor and benchmark required before promotion",
        )
    try:
        task = PredictionTask(manifest.purpose)
    except ValueError:
        raise HTTPException(status_code=422, detail="Unsupported benchmark task")
    if manifest.architecture == "spacy":
        if manifest.metrics.get("mode") != "textcat":
            raise HTTPException(
                status_code=422,
                detail="NER candidates require an entity-span benchmark, not classification evaluation",
            )
        from ai_karen_engine.core.intelligence.ml.predictors.registry_spacy import (
            SpacyCandidateBenchmarkPredictor,
        )
        predictor = SpacyCandidateBenchmarkPredictor(
            task=task, registry=registry, tenant_id=tenant,
            candidate_model_id=model_id,
        )
    else:
        predictor = RegistryBackedClassifier(
            task, registry=registry, tenant_id=tenant, candidate_model_id=model_id,
        )
    try:
        result, receipt = await BenchmarkRunner().run_and_record(
            predictor,
            BenchmarkConfig(
                model_id=model_id,
                model_version=manifest.model_version,
                task=task,
            ),
            registry=registry,
            actor=current_user,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Evaluation not permitted")
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="Candidate or evaluation evidence is not eligible",
        )
    return {
        "model_id": model_id,
        "receipt_id": receipt,
        "sample_count": result.sample_count,
        "error_count": result.error_count,
    }
