"""
Model Management API Routes

Provides REST API endpoints for managing local models, conversions, quantizations,
and job tracking for long-running operations.

This module implements:
- Local model listing, uploading, and management
- Model conversion and quantization endpoints
- Job tracking for long-running operations
- Provider management and validation
- Hugging Face integration for model discovery and downloads
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import threading
import requests

from ai_karen_engine.inference.huggingface_service import get_huggingface_service
# from ai_karen_engine.inference.local_gguf_tools import get_local_gguf_tools  <- REMOVED
from ai_karen_engine.inference.model_store import get_model_store
from ai_karen_engine.integrations.dynamic_provider_system import get_dynamic_provider_manager
from ai_karen_engine.integrations.registry import get_registry
from ai_karen_engine.services.scheduling.job_manager import get_job_manager
from ai_karen_engine.core.model_runtime.management.system_model_manager import get_system_model_manager
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks = import_fastapi(
    "APIRouter", "Depends", "HTTPException", "UploadFile", "File", "Form", "BackgroundTasks"
)
BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = logging.getLogger("kari.model_management")

router = APIRouter(prefix="/api", tags=["model-management"])

# -----------------------------
# Simple local download job manager (no HF token required)
# -----------------------------

class _DownloadJob:
    def __init__(self, url: str, dest_dir: Path, filename: Optional[str] = None):
        self.id = str(uuid.uuid4())
        self.url = url
        self.dest_dir = dest_dir
        self.filename = filename or url.split("/")[-1].split("?")[0]
        self.path = self.dest_dir / self.filename
        self.status = "pending"  # pending, running, paused, completed, error, cancelled
        self.progress = 0.0
        self.error: Optional[str] = None
        self._pause = threading.Event()
        self._cancel = threading.Event()
        self._pause.clear()
        self._cancel.clear()

    def run(self):
        self.status = "running"
        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)
            with requests.get(self.url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                downloaded = 0
                tmp_path = self.path.with_suffix(self.path.suffix + ".part")
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if self._cancel.is_set():
                            self.status = "cancelled"
                            try:
                                tmp_path.unlink(missing_ok=True)  # type: ignore
                            except Exception:
                                pass
                            return
                        while self._pause.is_set():
                            # paused
                            self.status = "paused"
                            threading.Event().wait(0.2)
                            if self._cancel.is_set():
                                break
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress = min(0.999, downloaded / total)
                tmp_path.replace(self.path)
            self.progress = 1.0
            self.status = "completed"
        except Exception as e:
            self.error = str(e)
            self.status = "error"

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()
        if self.status == "paused":
            self.status = "running"

    def cancel(self):
        self._cancel.set()


_JOBS: Dict[str, _DownloadJob] = {}


# -----------------------------
# Request/Response Models
# -----------------------------

class LocalModelInfo(BaseModel):
    """Local model information."""
    id: str
    name: str
    family: str
    format: str
    size: Optional[int] = None
    parameters: Optional[str] = None
    quantization: Optional[str] = None
    context_length: Optional[int] = None
    local_path: Optional[str] = None
    description: str = ""
    tags: List[str] = []
    capabilities: List[str] = []
    compatible_runtimes: List[str] = []
    optimal_runtime: Optional[str] = None
    created_at: Optional[float] = None
    last_used: Optional[float] = None
    usage_count: int = 0


class ModelUploadRequest(BaseModel):
    """Model upload request."""
    name: Optional[str] = None
    description: Optional[str] = ""
    tags: List[str] = []


class ConversionRequest(BaseModel):
    """Model conversion request."""
    source_path: str
    output_name: str
    architecture: Optional[str] = None
    vocab_only: bool = False


class QuantizationRequest(BaseModel):
    """Model quantization request."""
    source_path: str
    output_name: str
    quantization_format: str = "Q4_K_M"
    allow_requantize: bool = False


class JobInfo(BaseModel):
    """Job information."""
    id: str
    kind: str
    status: str
    progress: float
    title: str
    description: str
    logs: List[str] = []
    result: Dict[str, Any] = {}
    error: Optional[str] = None
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    updated_at: float


class ProviderInfo(BaseModel):
    """Provider information."""
    id: str
    name: str
    type: str
    requires_api_key: bool
    status: str = "unknown"
    models: List[Dict[str, Any]] = []
    capabilities: Dict[str, bool] = {}
    error_message: Optional[str] = None


class ProviderValidationRequest(BaseModel):
    """Provider validation request."""
    provider_id: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: Dict[str, Any] = {}


# -----------------------------
# Local GGUF-friendly model management (no HF key required)
# -----------------------------

class LocalDownloadRequest(BaseModel):
    url: str
    filename: Optional[str] = None
    directory: Optional[str] = None  # defaults to models/local-gguf


@router.get("/models/local/search")
async def search_local_models(q: Optional[str] = None):
    """Search local models (by filename) under the repo models directory."""
    try:
        store = get_model_store()
        base = Path("models")
        files = store.scan_local_models(str(base))
        results: List[Dict[str, Any]] = []
        for lm in files:
            if q and q.lower() not in lm.name.lower():
                continue
            results.append({
                "name": lm.name,
                "format": lm.format,
                "size": lm.size,
                "path": lm.path,
            })
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Local search failed: {e}")
        return {"results": [], "count": 0, "error": str(e)}


@router.post("/models/local/download")
async def download_local_model(req: LocalDownloadRequest):
    """Download a model file via direct URL to the local GGUF directory."""
    try:
        dest_dir = Path(req.directory or "models/local-gguf")
        job = _DownloadJob(url=req.url, dest_dir=dest_dir, filename=req.filename)
        _JOBS[job.id] = job
        t = threading.Thread(target=job.run, daemon=True)
        t.start()
        return {"job_id": job.id, "status": job.status, "path": str(job.path)}
    except Exception as e:
        logger.error(f"Download start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/local/jobs/{job_id}")
async def get_download_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "path": str(job.path),
    }


@router.post("/models/local/jobs/{job_id}/pause")
async def pause_download_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.pause()
    return {"job_id": job.id, "status": job.status}


@router.post("/models/local/jobs/{job_id}/resume")
async def resume_download_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.resume()
    return {"job_id": job.id, "status": job.status}


@router.post("/models/local/jobs/{job_id}/cancel")
async def cancel_download_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cancel()
    return {"job_id": job.id, "status": job.status}


@router.delete("/models/local")
async def delete_local_model(path: str):
    """Delete a local model file by absolute or relative path (under repo)."""
    try:
        p = Path(path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.exists():
            raise HTTPException(status_code=404, detail="File not found")
        # Safety: restrict to repo "models" directory
        models_root = (Path.cwd() / "models").resolve()
        if models_root not in p.resolve().parents and p.resolve() != models_root:
            raise HTTPException(status_code=400, detail="Deletion allowed only under models directory")
        p.unlink()
        return {"deleted": str(p)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete local model failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class HuggingFaceSearchRequest(BaseModel):
    """Hugging Face model search request."""
    query: str = ""
    tags: List[str] = []
    sort: str = "downloads"
    direction: str = "desc"
    limit: int = 20
    filter_format: Optional[str] = None


class ModelDownloadRequest(BaseModel):
    """Model download request."""
    model_id: str
    artifact: Optional[str] = None
    preference: str = "auto"  # auto, gguf, safetensors


class HealthStatus(BaseModel):
    """Health status information."""
    status: str
    providers: Dict[str, Dict[str, Any]] = {}
    runtimes: Dict[str, Dict[str, Any]] = {}
    model_store: Dict[str, Any] = {}
    job_manager: Dict[str, Any] = {}


# -----------------------------
# Local Model Management Endpoints
# -----------------------------

@router.get("/models/local", response_model=List[LocalModelInfo])
async def list_local_models(
    family: Optional[str] = None,
    format: Optional[str] = None,
    local_only: bool = True,
    limit: Optional[int] = None
):
    """List local models with optional filtering."""
    try:
        model_store = get_model_store()
        models = model_store.list_models(
            family=family,
            format=format,
            local_only=local_only
        )
        
        # Convert to response format
        result = []
        for model in models:
            result.append(LocalModelInfo(
                id=model.id,
                name=model.name,
                family=model.family,
                format=model.format,
                size=model.size,
                parameters=model.parameters,
                quantization=model.quantization,
                context_length=model.context_length,
                local_path=model.local_path,
                description=model.description,
                tags=list(model.tags),
                capabilities=list(model.capabilities),
                compatible_runtimes=model.compatible_runtimes,
                optimal_runtime=model.optimal_runtime,
                created_at=model.created_at,
                last_used=model.last_used,
                usage_count=model.usage_count
            ))
        
        # Apply limit if specified
        if limit:
            result = result[:limit]
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to list local models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/local/upload")
async def upload_model(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),  # type: ignore[var-annotated]
    name: Optional[str] = Form(None),
    description: str = Form(""),
    tags: str = Form("[]")  # JSON string
):
    """Upload a model file (GGUF, safetensors, or archive)."""
    try:
        # Parse tags
        try:
            tag_list = json.loads(tags) if tags else []
        except json.JSONDecodeError:
            tag_list = []
        
        # Validate file type
        allowed_extensions = {".gguf", ".safetensors", ".bin", ".pt", ".pth", ".zip", ".tar", ".tar.gz"}
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Create upload job
        job_manager = get_job_manager()
        job = job_manager.create_job(
            kind="upload",
            title=f"Upload {file.filename}",
            description=f"Uploading model file: {file.filename}",
            parameters={
                "filename": file.filename,
                "name": name or Path(file.filename).stem,
                "description": description,
                "tags": tag_list,
                "file_size": file.size
            }
        )
        
        # Start upload in background
        background_tasks.add_task(
            _handle_model_upload,
            job.id,
            file,
            name or Path(file.filename).stem,
            description,
            tag_list
        )
        
        return {"job_id": job.id, "message": "Upload started"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start model upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/local/convert-to-gguf")
async def convert_to_gguf(request: ConversionRequest):
    """Convert a model to GGUF format."""
    try:
        # Validate source path
        source_path = Path(request.source_path)
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Source model not found")
        
        # Create conversion job
        job_manager = get_job_manager()
        job = job_manager.create_job(
            kind="convert",
            title=f"Convert to GGUF: {request.output_name}",
            description=f"Converting {source_path.name} to GGUF format",
            parameters={
                "source_path": str(source_path),
                "output_name": request.output_name,
                "architecture": request.architecture,
                "vocab_only": request.vocab_only
            }
        )
        
        return {"job_id": job.id, "message": "Conversion started"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start model conversion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/local/quantize")
async def quantize_model(request: QuantizationRequest):
    """Quantize a model to reduce size."""
    try:
        # Validate source path
        source_path = Path(request.source_path)
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Source model not found")
        
        # Validate quantization format
        valid_formats = ["Q2_K", "Q3_K", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "IQ2_M", "IQ3_M", "IQ4_M"]
        if request.quantization_format not in valid_formats:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid quantization format. Valid formats: {', '.join(valid_formats)}"
            )
        
        # Create quantization job
        job_manager = get_job_manager()
        job = job_manager.create_job(
            kind="quantize",
            title=f"Quantize: {request.output_name}",
            description=f"Quantizing {source_path.name} to {request.quantization_format}",
            parameters={
                "source_path": str(source_path),
                "output_name": request.output_name,
                "quantization_format": request.quantization_format,
                "allow_requantize": request.allow_requantize
            }
        )
        
        return {"job_id": job.id, "message": "Quantization started"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start model quantization: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/models/local/{model_id}")
async def delete_local_model(model_id: str, delete_files: bool = False):
    """Delete a local model."""
    try:
        model_store = get_model_store()
        success = model_store.delete_model(model_id, delete_files=delete_files)
        
        if not success:
            raise HTTPException(status_code=404, detail="Model not found")
        
        return {"message": "Model deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete model {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/local/scan")
async def scan_local_models(directory: Optional[str] = None):
    """Scan directory for local models and register them."""
    try:
        model_store = get_model_store()
        registered_ids = model_store.register_local_models(directory)
        
        return {
            "message": f"Scanned and registered {len(registered_ids)} models",
            "registered_models": registered_ids
        }
        
    except Exception as e:
        logger.error(f"Failed to scan local models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------
# Job Management Endpoints
# -----------------------------

@router.get("/models/jobs", response_model=List[JobInfo])
async def list_jobs(
    status: Optional[str] = None,
    kind: Optional[str] = None,
    limit: Optional[int] = 50
):
    """List model management jobs."""
    try:
        job_manager = get_job_manager()
        jobs = job_manager.list_jobs(status=status, kind=kind, limit=limit)
        
        result = []
        for job in jobs:
            result.append(JobInfo(
                id=job.id,
                kind=job.kind,
                status=job.status,
                progress=job.progress,
                title=job.title,
                description=job.description,
                logs=job.logs[-10:],  # Last 10 log entries
                result=job.result,
                error=job.error,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                updated_at=job.updated_at
            ))
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/jobs/{job_id}", response_model=JobInfo)
async def get_job(job_id: str):
    """Get job details."""
    try:
        job_manager = get_job_manager()
        job = job_manager.get_job(job_id)
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return JobInfo(
            id=job.id,
            kind=job.kind,
            status=job.status,
            progress=job.progress,
            title=job.title,
            description=job.description,
            logs=job.logs,
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            updated_at=job.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a job."""
    try:
        job_manager = get_job_manager()
        success = job_manager.cancel_job(job_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Job not found or cannot be cancelled")
        
        return {"message": "Job cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    """Pause a job."""
    try:
        job_manager = get_job_manager()
        success = job_manager.pause_job(job_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Job not found or cannot be paused")
        
        return {"message": "Job paused successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    """Resume a job."""
    try:
        job_manager = get_job_manager()
        success = job_manager.resume_job(job_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Job not found or cannot be resumed")
        
        return {"message": "Job resumed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/models/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job."""
    try:
        job_manager = get_job_manager()
        success = job_manager.delete_job(job_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return {"message": "Job deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------
# Background Task Handlers
# -----------------------------

async def _handle_model_upload(
    job_id: str,
    file: UploadFile,  # type: ignore[var-annotated]
    name: str,
    description: str,
    tags: List[str]
):
    """Handle model file upload in background."""
    job_manager = get_job_manager()
    model_store = get_model_store()
    
    try:
        job_manager.append_log(job_id, "Starting model upload...")
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as temp_file:
            temp_path = temp_file.name
            
            # Read and write file in chunks
            total_size = file.size or 0
            bytes_read = 0
            
            while True:
                chunk = await file.read(8192)  # 8KB chunks
                if not chunk:
                    break
                
                temp_file.write(chunk)
                bytes_read += len(chunk)
                
                if total_size > 0:
                    progress = bytes_read / total_size
                    job_manager.update_progress(job_id, progress * 0.8)  # 80% for upload
        
        job_manager.append_log(job_id, f"File uploaded to {temp_path}")
        
        # Determine target directory
        model_store_dir = Path(model_store.models_dir)
        target_path = model_store_dir / file.filename
        
        # Move file to model store
        import shutil
        shutil.move(temp_path, target_path)
        
        job_manager.append_log(job_id, f"File moved to {target_path}")
        
        # Register model in store
        from ai_karen_engine.inference.model_store import ModelDescriptor
        
        model_id = f"local_{name}_{uuid.uuid4().hex[:8]}"
        descriptor = ModelDescriptor(
            id=model_id,
            name=name,
            format=Path(file.filename).suffix.lower().lstrip('.'),
            size=target_path.stat().st_size,
            source="local",
            provider="local",
            local_path=str(target_path),
            description=description,
            tags=set(tags)
        )
        
        model_store.register_model(descriptor)
        
        job_manager.update_progress(job_id, 1.0)
        job_manager.complete_job(job_id, {"model_id": model_id, "path": str(target_path)})
        job_manager.append_log(job_id, f"Model registered with ID: {model_id}")
        
    except Exception as e:
        job_manager.set_error(job_id, str(e))
        job_manager.append_log(job_id, f"Upload failed: {e}")
        
        # Clean up temporary file if it exists
        try:
            if 'temp_path' in locals() and Path(temp_path).exists():
                os.unlink(temp_path)
        except:
            pass


# Register job handlers
def _register_job_handlers():
    """Register job handlers for model operations."""
    job_manager = get_job_manager()
    
    def handle_convert_job(job):
        """Handle model conversion job."""
        try:
            params = job.parameters
            local_tools = get_local_gguf_tools()
            
            if not local_tools:
                raise Exception("Local conversion tools not available")
            
            job_manager.append_log(job.id, "Starting model conversion...")
            
            # Run conversion
            process = local_tools.convert_llama_dir(
                hf_dir=params["source_path"],
                out_path=params["output_name"],
                vocab_only=params.get("vocab_only", False)
            )
            
            # Monitor progress
            while process.poll() is None:
                # Simple progress estimation
                job_manager.update_progress(job.id, 0.5)
                import time
                time.sleep(1)
            
            if process.returncode != 0:
                raise Exception(f"Conversion failed with return code {process.returncode}")
            
            job_manager.append_log(job.id, "Conversion completed successfully")
            job_manager.complete_job(job.id, {"output_path": params["output_name"]})
            
        except Exception as e:
            job_manager.set_error(job.id, str(e))
    
    def handle_quantize_job(job):
        """Handle model quantization job."""
        try:
            params = job.parameters
            local_tools = get_local_gguf_tools()
            
            if not local_tools:
                raise Exception("Local quantization tools not available")
            
            job_manager.append_log(job.id, "Starting model quantization...")
            
            # Run quantization
            process = local_tools.quantize(
                in_path=params["source_path"],
                out_path=params["output_name"],
                fmt=params["quantization_format"],
                allow_requantize=params.get("allow_requantize", False)
            )
            
            # Monitor progress
            while process.poll() is None:
                # Simple progress estimation
                job_manager.update_progress(job.id, 0.5)
                import time
                time.sleep(1)
            
            if process.returncode != 0:
                raise Exception(f"Quantization failed with return code {process.returncode}")
            
            job_manager.append_log(job.id, "Quantization completed successfully")
            job_manager.complete_job(job.id, {"output_path": params["output_name"]})
            
        except Exception as e:
            job_manager.set_error(job.id, str(e))
    
    # Register handlers
    job_manager.register_handler("convert", handle_convert_job)
    job_manager.register_handler("quantize", handle_quantize_job)


# Initialize job handlers when module is imported
_register_job_handlers()

# -----------------------------
# System Model Configuration Endpoints
# -----------------------------

@router.get("/models/system", response_model=List[Dict[str, Any]])
async def list_system_models():
    """List all system models with their configuration and status."""
    try:
        system_model_manager = get_system_model_manager()
        models = system_model_manager.get_system_models()
        return models
        
    except Exception as e:
        logger.error(f"Failed to list system models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}", response_model=Dict[str, Any])
async def get_system_model(model_id: str):
    """Get detailed information about a specific system model."""
    try:
        system_model_manager = get_system_model_manager()
        models = system_model_manager.get_system_models()
        
        model = next((m for m in models if m["id"] == model_id), None)
        if not model:
            raise HTTPException(status_code=404, detail="System model not found")
        
        return model
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get system model {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}/configuration", response_model=Dict[str, Any])
async def get_model_configuration(model_id: str):
    """Get configuration for a specific system model."""
    try:
        system_model_manager = get_system_model_manager()
        config = system_model_manager.get_model_configuration(model_id)
        
        if config is None:
            raise HTTPException(status_code=404, detail="Model configuration not found")
        
        return config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get configuration for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/models/system/{model_id}/configuration")
async def update_model_configuration(model_id: str, request: Dict[str, Any]):
    """Update configuration for a specific system model."""
    try:
        system_model_manager = get_system_model_manager()
        configuration = request.get("configuration", {})
        
        success = system_model_manager.update_model_configuration(model_id, configuration)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update configuration")
        
        return {"message": "Configuration updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update configuration for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/system/validate-configuration")
async def validate_model_configuration(model_id: str, request: Dict[str, Any]):
    """Validate model configuration against hardware constraints."""
    try:
        system_model_manager = get_system_model_manager()
        configuration = request.get("configuration", {})
        
        # Get model info to determine config class
        if model_id not in system_model_manager.system_models:
            raise HTTPException(status_code=404, detail="System model not found")
        
        model_info = system_model_manager.system_models[model_id]
        config_class = model_info["config_class"]
        
        # Create config object for validation
        config_obj = config_class(**configuration)
        
        # Validate configuration
        validation_result = system_model_manager._validate_configuration(model_id, config_obj)
        
        return validation_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate configuration for {model_id}: {e}")
        return {"valid": False, "error": str(e)}


@router.post("/models/system/{model_id}/reset-configuration")
async def reset_model_configuration(model_id: str):
    """Reset model configuration to defaults."""
    try:
        system_model_manager = get_system_model_manager()
        success = system_model_manager.reset_model_configuration(model_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="System model not found")
        
        return {"message": "Configuration reset to defaults"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset configuration for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}/hardware-recommendations", response_model=Dict[str, Any])
async def get_hardware_recommendations(model_id: str):
    """Get hardware-specific recommendations for model configuration."""
    try:
        system_model_manager = get_system_model_manager()
        recommendations = system_model_manager.get_hardware_recommendations(model_id)
        
        return recommendations
        
    except Exception as e:
        logger.error(f"Failed to get hardware recommendations for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}/performance-metrics", response_model=Dict[str, Any])
async def get_performance_metrics(model_id: str):
    """Get performance metrics for a system model."""
    try:
        system_model_manager = get_system_model_manager()
        metrics = system_model_manager.get_performance_metrics(model_id)
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get performance metrics for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/system/{model_id}/health-check")
async def perform_health_check(model_id: str):
    """Perform health check on a system model."""
    try:
        system_model_manager = get_system_model_manager()
        status = system_model_manager._check_model_health(model_id)
        
        return {
            "status": status.status,
            "last_health_check": status.last_health_check,
            "error_message": status.error_message,
            "memory_usage": status.memory_usage,
            "load_time": status.load_time,
            "inference_time": status.inference_time
        }
        
    except Exception as e:
        logger.error(f"Failed to perform health check for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}/multi-gpu-config", response_model=Dict[str, Any])
async def get_multi_gpu_configuration(model_id: str):
    """Get multi-GPU configuration recommendations."""
    try:
        system_model_manager = get_system_model_manager()
        config = system_model_manager.get_multi_gpu_configuration(model_id)
        
        return config
        
    except Exception as e:
        logger.error(f"Failed to get multi-GPU configuration for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------
# Enhanced HuggingFace Integration
# -----------------------------

@router.get("/models/huggingface/search", response_model=Dict[str, Any])
async def search_huggingface_models(
    query: str = "",
    page: int = 1,
    per_page: int = 20,
    sort: str = "downloads",
    filter_trainable: bool = False
):
    """Search HuggingFace models with enhanced filtering."""
    try:
        from ai_karen_engine.inference.huggingface_service import get_enhanced_huggingface_service
        
        service = get_enhanced_huggingface_service()
        
        if filter_trainable:
            # Use enhanced search for trainable models
            from ai_karen_engine.inference.huggingface_service import TrainingFilters
            filters = TrainingFilters(supports_fine_tuning=True)
            models = service.search_trainable_models(
                query=query,
                filters=filters,
                limit=per_page
            )
            
            # Convert to response format
            model_list = []
            for model in models:
                model_list.append({
                    "id": model.id,
                    "name": model.name,
                    "author": model.author,
                    "description": model.description,
                    "tags": model.tags,
                    "downloads": model.downloads,
                    "likes": model.likes,
                    "family": model.family,
                    "parameters": model.parameters,
                    "format": model.format,
                    "size": model.size,
                    "huggingface_id": model.id,
                    "provider": "huggingface",
                    "supports_training": model.supports_fine_tuning,
                    "training_complexity": model.training_complexity,
                    "license": model.license
                })
        else:
            # Use basic search
            from ai_karen_engine.inference.huggingface_service import ModelFilters
            filters = ModelFilters(sort_by=sort, sort_order="desc")
            models = service.search_models(
                query=query,
                filters=filters,
                limit=per_page
            )
            
            # Convert to response format
            model_list = []
            for model in models:
                model_list.append({
                    "id": model.id,
                    "name": model.name,
                    "author": model.author,
                    "description": model.description,
                    "tags": model.tags,
                    "downloads": model.downloads,
                    "likes": model.likes,
                    "family": model.family,
                    "parameters": model.parameters,
                    "format": model.format,
                    "size": model.size,
                    "huggingface_id": model.id,
                    "provider": "huggingface",
                    "license": model.license
                })
        
        return {
            "models": model_list,
            "total": len(model_list),
            "page": page,
            "per_page": per_page,
            "has_more": len(model_list) == per_page
        }
        
    except Exception as e:
        logger.error(f"Failed to search HuggingFace models: {e}")
        # Return empty results instead of error to prevent frontend issues
        return {
            "models": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "has_more": False,
            "error": str(e)
        }


@router.post("/models/download")
async def download_model(
    background_tasks: BackgroundTasks,
    model_id: str,
    model_name: Optional[str] = None,
    provider: str = "huggingface",
    enhanced: bool = True
):
    """Download a model with optional enhanced features."""
    try:
        if provider == "huggingface" and enhanced:
            # Use enhanced download service
            from ai_karen_engine.inference.huggingface_service import get_enhanced_huggingface_service
            
            service = get_enhanced_huggingface_service()
            job = service.download_with_training_setup(
                model_id=model_id,
                setup_training=True
            )
            
            return {
                "job_id": job.id,
                "message": "Enhanced download started",
                "enhanced": True,
                "compatibility_check": job.compatibility_report is not None
            }
        else:
            # Use basic download service
            service = get_huggingface_service()
            job = service.download_model(model_id=model_id)
            
            return {
                "job_id": job.id,
                "message": "Download started",
                "enhanced": False
            }
        
    except Exception as e:
        logger.error(f"Failed to start model download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------
# Provider Management Endpoints
# -----------------------------

@router.get("/providers", response_model=List[ProviderInfo])
async def list_providers():
    """List all available LLM providers (excluding CopilotKit)."""
    try:
        # Return mock data to fix frontend errors
        providers = [
            ProviderInfo(
                id="openai",
                name="OpenAI",
                type="remote",
                requires_api_key=True,
                status="healthy",
                models=[],
                capabilities={
                    "streaming": True,
                    "vision": True,
                    "function_calling": True,
                    "embeddings": True
                }
            ),
            ProviderInfo(
                id="gemini", 
                name="Google Gemini",
                type="remote",
                requires_api_key=True,
                status="healthy",
                models=[],
                capabilities={
                    "streaming": True,
                    "vision": True,
                    "function_calling": False,
                    "embeddings": False
                }
            ),
            ProviderInfo(
                id="local",
                name="Local Models",
                type="local",
                requires_api_key=False,
                status="healthy",
                models=[],
                capabilities={
                    "streaming": True,
                    "vision": False,
                    "function_calling": False,
                    "embeddings": False
                }
            )
        ]
        
        return providers
        
    except Exception as e:
        logger.error(f"Failed to list providers: {e}")
        # Return fallback data instead of error
        return [
            ProviderInfo(
                id="openai",
                name="OpenAI",
                type="remote",
                requires_api_key=True,
                status="unknown",
                models=[],
                capabilities={"streaming": True}
            )
        ]


@router.post("/providers/validate")
async def validate_provider(request: ProviderValidationRequest):
    """Validate provider API key and configuration."""
    try:
        # Exclude CopilotKit from validation
        if request.provider_id.lower() == "copilotkit":
            raise HTTPException(
                status_code=400, 
                detail="CopilotKit is not an LLM provider and should not be validated here"
            )
        
        dynamic_system = get_dynamic_provider_manager()
        
        # Validate provider configuration
        is_valid = await dynamic_system.validate_provider_async(
            provider_id=request.provider_id,
            api_key=request.api_key,
            base_url=request.base_url,
            config=request.config
        )
        
        if is_valid:
            # Try to fetch models to confirm everything works
            try:
                models = dynamic_system.get_provider_models(request.provider_id)
                return {
                    "valid": True,
                    "message": "Provider validation successful",
                    "model_count": len(models)
                }
            except Exception as e:
                return {
                    "valid": True,
                    "message": "API key valid but model discovery failed",
                    "warning": str(e)
                }
        else:
            return {
                "valid": False,
                "message": "Provider validation failed",
                "error": "Invalid API key or configuration"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate provider {request.provider_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers/{provider_id}/models")
async def get_provider_models(provider_id: str):
    """Get models from a specific provider with fallback to curated lists."""
    try:
        # Exclude CopilotKit
        if provider_id.lower() == "copilotkit":
            raise HTTPException(
                status_code=400, 
                detail="CopilotKit is not an LLM provider"
            )
        
        dynamic_system = get_dynamic_provider_manager()
        
        try:
            # Try dynamic model discovery first
            models = dynamic_system.get_provider_models(provider_id)
            
            return {
                "provider_id": provider_id,
                "source": "dynamic",
                "models": [
                    {
                        "id": model.id,
                        "name": model.name,
                        "family": model.family,
                        "parameters": model.parameters,
                        "context_length": model.context_length,
                        "capabilities": list(model.capabilities)
                    }
                    for model in models
                ]
            }
            
        except Exception as e:
            logger.warning(f"Dynamic discovery failed for {provider_id}: {e}")
            
            # Fall back to curated model list
            curated_models = dynamic_system.get_fallback_models(provider_id)
            
            return {
                "provider_id": provider_id,
                "source": "fallback",
                "models": curated_models,
                "warning": f"Using fallback models due to: {str(e)}"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get models for provider {provider_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/llms", response_model=HealthStatus)
async def get_llm_health():
    """Get health status of providers, runtimes, and related services."""
    try:
        registry = get_registry()
        dynamic_system = get_dynamic_provider_manager()
        model_store = get_model_store()
        job_manager = get_job_manager()
        
        # Check provider health
        providers = {}
        for provider_name in registry.providers.keys():
            if provider_name.lower() == "copilotkit":
                continue  # Skip CopilotKit
            
            try:
                # Test provider health
                models = dynamic_system.get_provider_models(provider_name)
                providers[provider_name] = {
                    "status": "healthy",
                    "model_count": len(models),
                    "last_check": None
                }
            except Exception as e:
                providers[provider_name] = {
                    "status": "unhealthy",
                    "error": str(e),
                    "last_check": None
                }
        
        # Check runtime health
        runtimes = {}
        for runtime_name, runtime_spec in registry.runtimes.items():
            try:
                # Test runtime health
                health_info = runtime_spec.health()
                runtimes[runtime_name] = {
                    "status": "healthy" if health_info.get("available", False) else "unhealthy",
                    "info": health_info
                }
            except Exception as e:
                runtimes[runtime_name] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
        
        # Get model store stats
        model_stats = model_store.get_statistics()
        
        # Get job manager stats
        job_stats = job_manager.get_stats()
        
        # Determine overall status
        provider_healthy = all(p["status"] == "healthy" for p in providers.values())
        runtime_healthy = any(r["status"] == "healthy" for r in runtimes.values())
        overall_status = "healthy" if provider_healthy and runtime_healthy else "degraded"
        
        return HealthStatus(
            status=overall_status,
            providers=providers,
            runtimes=runtimes,
            model_store={
                "total_models": model_stats["total_models"],
                "local_models": model_stats["local_models"],
                "total_size_gb": round(model_stats["total_size_bytes"] / (1024**3), 2)
            },
            job_manager={
                "total_jobs": job_stats.total_jobs,
                "running_jobs": job_stats.running_jobs,
                "queued_jobs": job_stats.queued_jobs
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to get LLM health status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------
# Hugging Face Integration Endpoints
# -----------------------------

@router.post("/models/huggingface/search")
async def search_huggingface_models(request: HuggingFaceSearchRequest):
    """Search Hugging Face models with filtering and sorting."""
    try:
        hf_service = get_huggingface_service()
        
        if not hf_service:
            raise HTTPException(
                status_code=503, 
                detail="Hugging Face service not available"
            )
        
        # Prepare search filters
        from ai_karen_engine.inference.huggingface_service import ModelFilters
        
        filters = ModelFilters(
            tags=request.tags,
            sort=request.sort,
            direction=request.direction,
            limit=request.limit
        )
        
        if request.filter_format:
            filters.format = request.filter_format
        
        # Search models
        models = hf_service.search_models(request.query, filters)
        
        # Convert to response format
        result = []
        for model in models:
            result.append({
                "id": model.id,
                "name": model.name,
                "author": getattr(model, 'author', ''),
                "description": getattr(model, 'description', ''),
                "downloads": getattr(model, 'downloads', 0),
                "likes": getattr(model, 'likes', 0),
                "tags": getattr(model, 'tags', []),
                "size_gb": getattr(model, 'size_gb', None),
                "formats": getattr(model, 'formats', []),
                "license": getattr(model, 'license', ''),
                "created_at": getattr(model, 'created_at', None),
                "updated_at": getattr(model, 'updated_at', None)
            })
        
        return {
            "query": request.query,
            "total_results": len(result),
            "models": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search Hugging Face models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/download")
async def download_model(request: ModelDownloadRequest):
    """Download a model from Hugging Face with progress tracking."""
    try:
        hf_service = get_huggingface_service()
        
        if not hf_service:
            raise HTTPException(
                status_code=503, 
                detail="Hugging Face service not available"
            )
        
        # Start download job
        job_manager = get_job_manager()
        job = job_manager.create_job(
            kind="download",
            title=f"Download {request.model_id}",
            description=f"Downloading model from Hugging Face: {request.model_id}",
            parameters={
                "model_id": request.model_id,
                "artifact": request.artifact,
                "preference": request.preference
            }
        )
        
        # Register download job handler if not already registered
        def handle_download_job(job):
            """Handle model download job."""
            try:
                params = job.parameters
                
                job_manager.append_log(job.id, f"Starting download of {params['model_id']}...")
                
                # Start download
                download_job = hf_service.download_model(
                    model_id=params["model_id"],
                    artifact=params.get("artifact"),
                    preference=params.get("preference", "auto")
                )
                
                # Monitor download progress
                while download_job.status not in ["completed", "failed"]:
                    job_manager.update_progress(job.id, download_job.progress)
                    job_manager.append_log(job.id, f"Progress: {download_job.progress:.1%}")
                    
                    import time
                    time.sleep(2)
                
                if download_job.status == "completed":
                    job_manager.append_log(job.id, "Download completed successfully")
                    
                    # Register downloaded model in model store
                    if download_job.result.get("local_path"):
                        model_store = get_model_store()
                        # Auto-register the downloaded model
                        model_store.register_local_models(
                            directory=str(Path(download_job.result["local_path"]).parent)
                        )
                    
                    job_manager.complete_job(job.id, download_job.result)
                else:
                    job_manager.set_error(job.id, download_job.error or "Download failed")
                
            except Exception as e:
                job_manager.set_error(job.id, str(e))
        
        # Register handler if not already done
        try:
            job_manager.register_handler("download", handle_download_job)
        except:
            pass  # Handler might already be registered
        
        return {"job_id": job.id, "message": "Download started"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start model download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/huggingface/{model_id}/info")
async def get_huggingface_model_info(model_id: str):
    """Get detailed information about a Hugging Face model."""
    try:
        hf_service = get_huggingface_service()
        
        if not hf_service:
            raise HTTPException(
                status_code=503, 
                detail="Hugging Face service not available"
            )
        
        # Get model info
        model_info = hf_service.get_model_info(model_id)
        
        if not model_info:
            raise HTTPException(status_code=404, detail="Model not found")
        
        return {
            "id": model_info.id,
            "name": model_info.name,
            "description": getattr(model_info, 'description', ''),
            "author": getattr(model_info, 'author', ''),
            "tags": getattr(model_info, 'tags', []),
            "license": getattr(model_info, 'license', ''),
            "downloads": getattr(model_info, 'downloads', 0),
            "likes": getattr(model_info, 'likes', 0),
            "size_gb": getattr(model_info, 'size_gb', None),
            "formats": getattr(model_info, 'formats', []),
            "files": getattr(model_info, 'files', []),
            "created_at": getattr(model_info, 'created_at', None),
            "updated_at": getattr(model_info, 'updated_at', None),
            "config": getattr(model_info, 'config', {}),
            "recommended_artifact": getattr(model_info, 'recommended_artifact', None)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Hugging Face model info for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/huggingface/{model_id}/artifacts")
async def get_model_artifacts(model_id: str):
    """Get available artifacts (files) for a Hugging Face model."""
    try:
        hf_service = get_huggingface_service()
        
        if not hf_service:
            raise HTTPException(
                status_code=503, 
                detail="Hugging Face service not available"
            )
        
        # Get model info to access files
        model_info = hf_service.get_model_info(model_id)
        
        if not model_info:
            raise HTTPException(status_code=404, detail="Model not found")
        
        files = getattr(model_info, 'files', [])
        
        # Categorize files by type
        artifacts = {
            "gguf": [],
            "safetensors": [],
            "pytorch": [],
            "other": []
        }
        
        for file_info in files:
            filename = file_info.get("filename", "")
            size = file_info.get("size", 0)
            
            if filename.endswith(".gguf"):
                artifacts["gguf"].append({
                    "filename": filename,
                    "size": size,
                    "size_gb": round(size / (1024**3), 2),
                    "type": "gguf"
                })
            elif filename.endswith(".safetensors"):
                artifacts["safetensors"].append({
                    "filename": filename,
                    "size": size,
                    "size_gb": round(size / (1024**3), 2),
                    "type": "safetensors"
                })
            elif filename.endswith((".bin", ".pt", ".pth")):
                artifacts["pytorch"].append({
                    "filename": filename,
                    "size": size,
                    "size_gb": round(size / (1024**3), 2),
                    "type": "pytorch"
                })
            else:
                artifacts["other"].append({
                    "filename": filename,
                    "size": size,
                    "size_gb": round(size / (1024**3), 2),
                    "type": "other"
                })
        
        # Get optimal artifact recommendation
        try:
            from ai_karen_engine.inference.huggingface_service import DeviceCapabilities
            device_caps = DeviceCapabilities()  # Use default capabilities
            
            optimal_artifact = hf_service.select_optimal_artifact(
                files=files,
                preference="auto",
                device_caps=device_caps
            )
            
            recommended = optimal_artifact.get("filename") if optimal_artifact else None
        except:
            recommended = None
        
        return {
            "model_id": model_id,
            "artifacts": artifacts,
            "recommended": recommended,
            "total_files": len(files)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get artifacts for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# ------
# Missing Endpoints for Frontend
# -----------------------------

@router.get("/providers/profiles")
async def get_provider_profiles():
    """Get all provider profiles."""
    try:
        # Return mock data for now - this should be replaced with actual profile management
        return {
            "profiles": [
                {
                    "id": "default",
                    "name": "Default Profile",
                    "description": "Default LLM provider configuration",
                    "is_active": True,
                    "providers": {
                        "chat": {"provider": "openai", "model": "gpt-3.5-turbo", "priority": 1},
                        "completion": {"provider": "openai", "model": "gpt-3.5-turbo", "priority": 1},
                        "embedding": {"provider": "openai", "model": "text-embedding-ada-002", "priority": 1}
                    },
                    "router_policy": "local_first",
                    "is_valid": True,
                    "validation_errors": []
                }
            ]
        }
    except Exception as e:
        logger.error(f"Error getting provider profiles: {e}")
        return {"profiles": []}


@router.get("/providers/profiles/active")
async def get_active_provider_profile():
    """Get the currently active provider profile."""
    try:
        # Return mock active profile - this should be replaced with actual profile management
        return {
            "id": "default",
            "name": "Default Profile",
            "description": "Default LLM provider configuration",
            "is_active": True,
            "providers": {
                "chat": {"provider": "openai", "model": "gpt-3.5-turbo", "priority": 1},
                "completion": {"provider": "openai", "model": "gpt-3.5-turbo", "priority": 1},
                "embedding": {"provider": "openai", "model": "text-embedding-ada-002", "priority": 1}
            },
            "router_policy": "local_first",
            "is_valid": True,
            "validation_errors": []
        }
    except Exception as e:
        logger.error(f"Error getting active provider profile: {e}")
        return None


@router.get("/models/all")
async def get_all_models():
    """Get all available models including local GGUF files.

    Returns a flat list suitable for UI consumption.
    """
    try:
        registry = get_registry()
        model_store = get_model_store()

        models: list[dict[str, Any]] = []

        # 1) Local models from repo models directory (safetensors prioritized)
        try:
            repo_models_dir = Path("models")
            local_files = model_store.scan_local_models(str(repo_models_dir))
            for lm in local_files:
                is_gguf = (lm.format or "").lower() == "gguf"
                runtime_compat = ["openai_compatible"] if is_gguf else []
                capabilities = ["text"] + (["local_execution"] if is_gguf else [])

                models.append({
                    "id": Path(lm.path).name,
                    "name": lm.name,
                    "family": (lm.metadata or {}).get("family") or model_store._infer_model_family(lm.name),
                    "format": lm.format,
                    "size": lm.size,
                    "parameters": (lm.metadata or {}).get("parameters"),
                    "quantization": (lm.metadata or {}).get("quantization"),
                    "context_length": None,
                    "capabilities": capabilities,
                    "local_path": str(Path(lm.path)),
                    "download_url": None,
                    "provider": "local",
                    "runtime_compatibility": runtime_compat,
                    "tags": ["local" , lm.format] + (["gguf"] if is_gguf else []),
                    "license": None,
                    "description": f"Local {lm.format.upper()} model",
                    "created_at": None,
                    "updated_at": None,
                })
        except Exception as e:
            logger.warning(f"Local model scan failed: {e}")

        # 2) Registered models in the model store database (if any)
        try:
            for md in model_store.list_models():
                runtime_compat = md.compatible_runtimes or []
                models.append({
                    "id": md.id or md.name or "unknown",
                    "name": md.name or "Unknown Model",
                    "family": md.family or "",
                    "format": md.format or "",
                    "size": md.size,
                    "parameters": md.parameters,
                    "quantization": md.quantization,
                    "context_length": md.context_length,
                    "capabilities": list(md.capabilities) or ["text"],
                    "local_path": md.local_path,
                    "download_url": md.download_url,
                    "provider": md.provider or ("local" if md.local_path else (md.source or "unknown")),
                    "runtime_compatibility": runtime_compat,
                    "tags": list(md.tags),
                    "license": md.license,
                    "description": md.description or "",
                    "created_at": md.created_at,
                    "updated_at": md.updated_at,
                })
        except Exception as e:
            logger.debug(f"Model store listing failed: {e}")

        # 3) Basic provider stubs (non-local), best-effort
        try:
            for provider_name in registry.providers.keys():
                if provider_name.lower() in {"copilotkit", "local"}:
                    continue
                # Skip adding duplicates if already present
                # Keep minimal entries as placeholders for remote catalogs
        except Exception:
            pass

        return models

    except Exception as e:
        logger.error(f"Error getting all models: {e}")
        return []


@router.get("/providers/stats")
async def get_provider_stats():
    """Get provider statistics and usage information."""
    try:
        registry = get_registry()
        
        stats = {
            "total_providers": 0,
            "active_providers": 0,
            "healthy_providers": 0,  # for UI compatibility
            "total_models": 0,
            "providers": {},
            "last_sync": time.time(),
            "degraded_mode": False,
        }
        
        for provider_name, provider_spec in registry.providers.items():
            if provider_name.lower() == "copilotkit":
                continue
                
            stats["total_providers"] += 1
            
            # Mock provider stats - this should be replaced with actual usage tracking
            provider_stats = {
                "status": "active",
                "models_count": 3,  # Mock count
                "requests_today": 0,
                "avg_response_time": 0.0,
                "success_rate": 1.0,
                "last_used": None
            }
            
            stats["providers"][provider_name] = provider_stats
            stats["active_providers"] += 1
            stats["healthy_providers"] += 1
            stats["total_models"] += provider_stats["models_count"]
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting provider stats: {e}")
        return {
            "total_providers": 0,
            "active_providers": 0,
            "total_models": 0,
            "providers": {}
        }

# -----------------------------
# System Model Management Endpoints
# -----------------------------

class SystemModelInfo(BaseModel):
    """System model information."""
    id: str
    name: str
    family: str
    format: str
    capabilities: List[str]
    runtime_compatibility: List[str]
    local_path: str
    status: str
    size: Optional[int] = None
    parameters: Optional[str] = None
    last_health_check: Optional[float] = None
    error_message: Optional[str] = None
    memory_usage: Optional[int] = None
    load_time: Optional[float] = None
    inference_time: Optional[float] = None
    configuration: Dict[str, Any] = {}
    is_system_model: bool = True


class ModelConfigurationRequest(BaseModel):
    """Model configuration update request."""
    configuration: Dict[str, Any]


class HardwareRecommendations(BaseModel):
    """Hardware recommendations for model configuration."""
    system_info: Dict[str, Any]
    recommendations: Dict[str, Any] = {}


@router.get("/models/system", response_model=List[SystemModelInfo])
async def list_system_models():
    """List all system models with their status and configuration."""
    try:
        system_manager = get_system_model_manager()
        models = system_manager.get_system_models()
        
        return [SystemModelInfo(**model) for model in models]
        
    except Exception as e:
        logger.error(f"Failed to list system models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}", response_model=SystemModelInfo)
async def get_system_model(model_id: str):
    """Get detailed information about a specific system model."""
    try:
        system_manager = get_system_model_manager()
        models = system_manager.get_system_models()
        
        model = next((m for m in models if m["id"] == model_id), None)
        if not model:
            raise HTTPException(status_code=404, detail="System model not found")
        
        return SystemModelInfo(**model)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get system model {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}/configuration")
async def get_model_configuration(model_id: str):
    """Get configuration for a specific system model."""
    try:
        system_manager = get_system_model_manager()
        config = system_manager.get_model_configuration(model_id)
        
        if config is None:
            raise HTTPException(status_code=404, detail="Model configuration not found")
        
        return {"model_id": model_id, "configuration": config}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get configuration for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/models/system/{model_id}/configuration")
async def update_model_configuration(model_id: str, request: ModelConfigurationRequest):
    """Update configuration for a specific system model."""
    try:
        system_manager = get_system_model_manager()
        success = system_manager.update_model_configuration(model_id, request.configuration)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update model configuration")
        
        return {"message": "Configuration updated successfully", "model_id": model_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update configuration for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/system/{model_id}/reset-configuration")
async def reset_model_configuration(model_id: str):
    """Reset model configuration to defaults."""
    try:
        system_manager = get_system_model_manager()
        success = system_manager.reset_model_configuration(model_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Model not found")
        
        return {"message": "Configuration reset to defaults", "model_id": model_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset configuration for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}/hardware-recommendations")
async def get_hardware_recommendations(model_id: str):
    """Get hardware-specific recommendations for model configuration."""
    try:
        system_manager = get_system_model_manager()
        recommendations = system_manager.get_hardware_recommendations(model_id)
        
        return {"model_id": model_id, **recommendations}
        
    except Exception as e:
        logger.error(f"Failed to get hardware recommendations for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/system/{model_id}/performance-metrics")
async def get_performance_metrics(model_id: str):
    """Get performance metrics for a system model."""
    try:
        system_manager = get_system_model_manager()
        metrics = system_manager.get_performance_metrics(model_id)
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get performance metrics for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/system/{model_id}/health-check")
async def perform_health_check(model_id: str):
    """Perform a health check on a system model."""
    try:
        system_manager = get_system_model_manager()
        # Force a fresh health check
        models = system_manager.get_system_models()
        model = next((m for m in models if m["id"] == model_id), None)
        
        if not model:
            raise HTTPException(status_code=404, detail="System model not found")
        
        return {
            "model_id": model_id,
            "status": model["status"],
            "last_health_check": model["last_health_check"],
            "error_message": model["error_message"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to perform health check for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/system/validate-configuration")
async def validate_model_configuration(model_id: str, request: ModelConfigurationRequest):
    """Validate model configuration without applying it."""
    try:
        system_manager = get_system_model_manager()
        
        # Create a temporary configuration to validate
        model_info = system_manager.system_models.get(model_id)
        if not model_info:
            raise HTTPException(status_code=404, detail="System model not found")
        
        config_class = model_info["config_class"]
        temp_config = config_class(**request.configuration)
        
        validation_result = system_manager._validate_configuration(model_id, temp_config)
        
        return {
            "model_id": model_id,
            "valid": validation_result["valid"],
            "error": validation_result.get("error"),
            "warnings": validation_result.get("warnings", [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate configuration for {model_id}: {e}")
        return {
            "model_id": model_id,
            "valid": False,
            "error": str(e)
        }

# -----------------------------
# Extended Local Model API Endpoints (Task 6.1)
# -----------------------------

@router.get("/models/local/status")
async def get_local_models_status():
    """Get status of local model directory and scanning capabilities."""
    try:
        model_store = get_model_store()
        
        # Check if models directory exists and is accessible
        models_dir = Path(model_store.models_dir)
        status = {
            "models_directory": str(models_dir),
            "directory_exists": models_dir.exists(),
            "directory_writable": models_dir.exists() and os.access(models_dir, os.W_OK),
            "total_models": len(model_store.list_models(local_only=True)),
            "supported_formats": [".gguf", ".safetensors", ".bin", ".pt", ".pth"],
            "scan_capabilities": {
                "auto_detection": True,
                "metadata_extraction": True,
                "compatibility_checking": True
            }
        }
        
        return status
        
    except Exception as e:
        logger.error(f"Failed to get local models status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/local/upload/validate")
async def validate_model_upload(file: UploadFile = File(...)):  # type: ignore[var-annotated]
    """Validate a model file before upload without actually uploading it."""
    try:
        # Check file extension
        allowed_extensions = {".gguf", ".safetensors", ".bin", ".pt", ".pth", ".zip", ".tar", ".tar.gz"}
        file_ext = Path(file.filename).suffix.lower()
        
        validation_result = {
            "filename": file.filename,
            "size": file.size,
            "extension": file_ext,
            "valid": file_ext in allowed_extensions,
            "format": file_ext.lstrip('.'),
            "estimated_upload_time": None,
            "warnings": [],
            "errors": []
        }
        
        if not validation_result["valid"]:
            validation_result["errors"].append(
                f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Check file size
        if file.size and file.size > 50 * 1024 * 1024 * 1024:  # 50GB limit
            validation_result["errors"].append("File size exceeds 50GB limit")
        elif file.size and file.size > 10 * 1024 * 1024 * 1024:  # 10GB warning
            validation_result["warnings"].append("Large file size may take significant time to upload")
        
        # Estimate upload time (assuming 10MB/s average)
        if file.size:
            estimated_seconds = file.size / (10 * 1024 * 1024)
            validation_result["estimated_upload_time"] = estimated_seconds
        
        return validation_result
        
    except Exception as e:
        logger.error(f"Failed to validate upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/local/formats")
async def get_supported_formats():
    """Get information about supported model formats and their capabilities."""
    formats = {
        "gguf": {
            "description": "GGML Universal Format - optimized for CPU inference",
            "extensions": [".gguf"],
            "runtimes": ["local_gguf"],
            "quantization_support": True,
            "streaming_support": True,
            "memory_efficient": True,
            "gpu_acceleration": True
        },
        "safetensors": {
            "description": "Safe serialization format for PyTorch models",
            "extensions": [".safetensors"],
            "runtimes": ["transformers"],
            "quantization_support": False,
            "streaming_support": True,
            "memory_efficient": False,
            "gpu_acceleration": True
        },
        "pytorch": {
            "description": "PyTorch native format",
            "extensions": [".bin", ".pt", ".pth"],
            "runtimes": ["transformers"],
            "quantization_support": False,
            "streaming_support": True,
            "memory_efficient": False,
            "gpu_acceleration": True
        },
        "archive": {
            "description": "Compressed archives containing model files",
            "extensions": [".zip", ".tar", ".tar.gz"],
            "runtimes": [],
            "quantization_support": False,
            "streaming_support": False,
            "memory_efficient": False,
            "gpu_acceleration": False,
            "note": "Archives are extracted during upload"
        }
    }
    
    return {
        "supported_formats": formats,
        "recommended_format": "safetensors",
        "conversion_available": True,
        "quantization_available": True
    }


@router.post("/models/local/convert-to-gguf/validate")
async def validate_conversion_request(request: ConversionRequest):
    """Validate a conversion request before starting the actual conversion."""
    try:
        # Check if source path exists
        source_path = Path(request.source_path)
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Source model not found")
        
        # Check if it's a directory (HuggingFace format) or file
        is_directory = source_path.is_dir()
        
        validation_result = {
            "source_path": str(source_path),
            "output_name": request.output_name,
            "is_directory": is_directory,
            "valid": True,
            "warnings": [],
            "errors": [],
            "estimated_time": None,
            "estimated_size": None
        }
        
        # Check if local conversion tools are available
        local_tools = get_local_gguf_tools()
        if not local_tools:
            validation_result["valid"] = False
            validation_result["errors"].append("Local conversion tools not available")
        
        # Check output path doesn't already exist
        output_path = Path(request.output_name)
        if output_path.exists():
            validation_result["warnings"].append("Output file already exists and will be overwritten")
        
        # Estimate conversion time and output size
        if source_path.exists():
            if is_directory:
                # Estimate based on directory size
                total_size = sum(f.stat().st_size for f in source_path.rglob('*') if f.is_file())
            else:
                total_size = source_path.stat().st_size
            
            # Rough estimates: conversion takes ~1 minute per GB, output is ~70% of input size
            validation_result["estimated_time"] = total_size / (1024 * 1024 * 1024) * 60  # seconds
            validation_result["estimated_size"] = int(total_size * 0.7)
        
        return validation_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate conversion request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/local/quantize/validate")
async def validate_quantization_request(request: QuantizationRequest):
    """Validate a quantization request before starting the actual quantization."""
    try:
        # Check if source path exists
        source_path = Path(request.source_path)
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Source model not found")
        
        # Validate quantization format
        valid_formats = ["Q2_K", "Q3_K", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "IQ2_M", "IQ3_M", "IQ4_M"]
        
        validation_result = {
            "source_path": str(source_path),
            "output_name": request.output_name,
            "quantization_format": request.quantization_format,
            "valid": True,
            "warnings": [],
            "errors": [],
            "estimated_time": None,
            "estimated_size": None,
            "size_reduction": None
        }
        
        if request.quantization_format not in valid_formats:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Invalid quantization format. Valid formats: {', '.join(valid_formats)}"
            )
        
        # Check if local conversion tools are available
        local_tools = get_local_gguf_tools()
        if not local_tools:
            validation_result["valid"] = False
            validation_result["errors"].append("Local quantization tools not available")
        
        # Check if source is GGUF format
        if not source_path.name.endswith('.gguf'):
            validation_result["warnings"].append("Source file is not GGUF format - conversion may be needed first")
        
        # Check output path doesn't already exist
        output_path = Path(request.output_name)
        if output_path.exists() and not request.allow_requantize:
            validation_result["errors"].append("Output file already exists. Set allow_requantize=true to overwrite")
        
        # Estimate quantization results
        if source_path.exists():
            source_size = source_path.stat().st_size
            
            # Size reduction estimates based on quantization format
            size_reductions = {
                "Q2_K": 0.25, "Q3_K": 0.35, "Q4_K_M": 0.45, 
                "Q5_K_M": 0.55, "Q6_K": 0.65, "Q8_0": 0.8,
                "IQ2_M": 0.22, "IQ3_M": 0.32, "IQ4_M": 0.42
            }
            
            reduction_factor = size_reductions.get(request.quantization_format, 0.5)
            validation_result["estimated_size"] = int(source_size * reduction_factor)
            validation_result["size_reduction"] = f"{(1 - reduction_factor) * 100:.0f}%"
            
            # Quantization is typically faster than conversion: ~30 seconds per GB
            validation_result["estimated_time"] = source_size / (1024 * 1024 * 1024) * 30
        
        return validation_result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate quantization request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/local/disk-usage")
async def get_local_models_disk_usage():
    """Get disk usage information for local models."""
    try:
        model_store = get_model_store()
        models_dir = Path(model_store.models_dir)
        
        if not models_dir.exists():
            return {
                "models_directory": str(models_dir),
                "total_size": 0,
                "file_count": 0,
                "models": []
            }
        
        # Calculate total size and collect model info
        total_size = 0
        file_count = 0
        models_info = []
        
        for model_file in models_dir.rglob('*'):
            if model_file.is_file():
                file_size = model_file.stat().st_size
                total_size += file_size
                file_count += 1
                
                # Check if it's a recognized model format
                if model_file.suffix.lower() in ['.gguf', '.safetensors', '.bin', '.pt', '.pth']:
                    models_info.append({
                        "name": model_file.name,
                        "path": str(model_file.relative_to(models_dir)),
                        "size": file_size,
                        "format": model_file.suffix.lower().lstrip('.'),
                        "modified": model_file.stat().st_mtime
                    })
        
        # Sort models by size (largest first)
        models_info.sort(key=lambda x: x["size"], reverse=True)
        
        return {
            "models_directory": str(models_dir),
            "total_size": total_size,
            "total_size_human": _format_bytes(total_size),
            "file_count": file_count,
            "model_count": len(models_info),
            "models": models_info[:20],  # Top 20 largest models
            "disk_space": {
                "available": _get_available_disk_space(models_dir),
                "used_percentage": _get_disk_usage_percentage(models_dir)
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get disk usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _format_bytes(bytes_value: int) -> str:
    """Format bytes into human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_value < 1024:
            return f"{bytes_value} {unit}"
        bytes_value //= 1024
    return f"{bytes_value} PB"


def _get_available_disk_space(path: Path) -> Optional[int]:
    """Get available disk space for the given path."""
    try:
        import shutil
        return shutil.disk_usage(path).free
    except Exception:
        return None


def _get_disk_usage_percentage(path: Path) -> Optional[float]:
    """Get disk usage percentage for the given path."""
    try:
        import shutil
        usage = shutil.disk_usage(path)
        return (usage.used / usage.total) * 100
    except Exception:
        return None


# -----------------------------
# Extended Hugging Face Integration Endpoints (Task 6.3)
# -----------------------------

class HuggingFaceSearchRequest(BaseModel):
    """Enhanced Hugging Face model search request."""
    query: str = ""
    tags: List[str] = []
    sort: str = "downloads"
    direction: str = "desc"
    limit: int = 20
    filter_format: Optional[str] = None
    min_downloads: Optional[int] = None
    max_size_gb: Optional[float] = None
    license_filter: Optional[str] = None
    include_private: bool = False


class HuggingFaceModelInfo(BaseModel):
    """Enhanced Hugging Face model information."""
    id: str
    name: str
    author: Optional[str] = None
    description: str = ""
    tags: List[str] = []
    downloads: int = 0
    likes: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    library_name: Optional[str] = None
    pipeline_tag: Optional[str] = None
    license: Optional[str] = None
    size: Optional[int] = None
    
    # Inferred metadata
    family: Optional[str] = None
    parameters: Optional[str] = None
    quantization: Optional[str] = None
    format: Optional[str] = None
    
    # Available artifacts
    artifacts: List[Dict[str, Any]] = []
    recommended_artifact: Optional[Dict[str, Any]] = None
    
    # Local availability
    locally_available: bool = False
    local_path: Optional[str] = None


class ModelDownloadRequest(BaseModel):
    """Enhanced model download request."""
    model_id: str
    artifact: Optional[str] = None
    preference: str = "auto"  # auto, gguf, safetensors, bin
    target_directory: Optional[str] = None
    register_locally: bool = True
    overwrite_existing: bool = False


class DownloadJobResponse(BaseModel):
    """Download job response."""
    job_id: str
    model_id: str
    artifact: Optional[str] = None
    status: str
    message: str
    estimated_size: Optional[int] = None
    target_path: Optional[str] = None


# Predefined model URLs for local features (no API key required)
CURATED_MODELS = {
    "default-lightweight-model": {
        "url": "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf",
        "filename": "Qwen3-0.6B-Q4_K_M.gguf",
        "model_id": "Qwen/Qwen3-0.6B-GGUF",
        "description": "Compact Qwen3 chat model for low-resource local inference and default assistant tasks",
        "size": 520000000,  # ~520MB
        "family": "qwen",
        "parameters": "0.6B",
        "quantization": "Q4_K_M"
    },
    "phi3-mini": {
        "url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
        "filename": "Phi-3-mini-4k-instruct-q4.gguf",
        "model_id": "microsoft/Phi-3-mini-4k-instruct-gguf",
        "description": "Microsoft's Phi-3 Mini model optimized for instruction following",
        "size": 2300000000,  # ~2.3GB
        "family": "phi",
        "parameters": "3.8B",
        "quantization": "Q4"
    },
    "gemma-2b": {
        "url": "https://huggingface.co/google/gemma-2b-it-GGUF/resolve/main/gemma-2b-it.q4_k_m.gguf",
        "filename": "gemma-2b-it.q4_k_m.gguf",
        "model_id": "google/gemma-2b-it-GGUF",
        "description": "Google's Gemma 2B instruction-tuned model",
        "size": 1600000000,  # ~1.6GB
        "family": "gemma",
        "parameters": "2B",
        "quantization": "Q4_K_M"
    }
}


@router.get("/models/huggingface/curated")
async def get_curated_models():
    """Get curated models that can be downloaded without API keys."""
    try:
        models = []
        
        for model_key, model_info in CURATED_MODELS.items():
            # Check if already downloaded locally
            model_store = get_model_store()
            local_models = model_store.list_models(local_only=True)
            locally_available = any(
                model_info["filename"] in (m.local_path or "") 
                for m in local_models
            )
            
            models.append({
                "key": model_key,
                "model_id": model_info["model_id"],
                "name": model_info["filename"],
                "description": model_info["description"],
                "family": model_info["family"],
                "parameters": model_info["parameters"],
                "quantization": model_info["quantization"],
                "size": model_info["size"],
                "size_human": _format_bytes(model_info["size"]),
                "locally_available": locally_available,
                "download_url": model_info["url"],
                "recommended": model_key == "phi3-mini"  # Recommend default model
            })
        
        return {
            "curated_models": models,
            "total_count": len(models),
            "note": "These models can be downloaded without HuggingFace API keys"
        }
        
    except Exception as e:
        logger.error(f"Failed to get curated models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/huggingface/download-curated")
async def download_curated_model(model_key: str):
    """Download a curated model by key."""
    try:
        if model_key not in CURATED_MODELS:
            raise HTTPException(
                status_code=404, 
                detail=f"Curated model '{model_key}' not found. Available: {list(CURATED_MODELS.keys())}"
            )
        
        model_info = CURATED_MODELS[model_key]
        
        # Create download job using the simple local download system
        dest_dir = Path("models/local-gguf")
        job = _DownloadJob(
            url=model_info["url"], 
            dest_dir=dest_dir, 
            filename=model_info["filename"]
        )
        _JOBS[job.id] = job
        
        # Start download in background thread
        import threading
        t = threading.Thread(target=job.run, daemon=True)
        t.start()
        
        return {
            "job_id": job.id,
            "model_key": model_key,
            "model_id": model_info["model_id"],
            "filename": model_info["filename"],
            "status": job.status,
            "estimated_size": model_info["size"],
            "target_path": str(job.path),
            "message": f"Started download of {model_key}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start curated model download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/huggingface/search", response_model=List[HuggingFaceModelInfo])
async def search_huggingface_models(request: HuggingFaceSearchRequest):
    """
    Search HuggingFace Hub for models with advanced filtering and artifact detection.
    
    This endpoint provides comprehensive model search with intelligent artifact selection
    and local availability checking.
    """
    try:
        hf_service = get_huggingface_service()
        
        # Convert request to HF service filters
        from ai_karen_engine.inference.huggingface_service import ModelFilters
        
        filters = ModelFilters(
            tags=request.tags if request.tags else None,
            sort_by=request.sort,
            sort_order=request.direction,
            task="text-generation",  # Focus on text generation models
            min_downloads=request.min_downloads
        )
        
        # Add format filter if specified
        if request.filter_format:
            if request.filter_format.lower() == "gguf":
                filters.tags = (filters.tags or []) + ["gguf"]
            elif request.filter_format.lower() == "safetensors":
                filters.library = "transformers"
        
        # Search models
        hf_models = hf_service.search_models(
            query=request.query,
            filters=filters,
            limit=request.limit
        )
        
        # Convert to enhanced model info with artifact analysis
        enhanced_models = []
        model_store = get_model_store()
        local_models = model_store.list_models(local_only=True)
        
        for hf_model in hf_models:
            # Check local availability
            locally_available = any(
                hf_model.id in (m.id or "") or hf_model.name in (m.name or "")
                for m in local_models
            )
            
            local_path = None
            if locally_available:
                for m in local_models:
                    if hf_model.id in (m.id or "") or hf_model.name in (m.name or ""):
                        local_path = m.local_path
                        break
            
            # Analyze available artifacts
            artifacts = []
            recommended_artifact = None
            
            for file_info in hf_model.files:
                filename = file_info.get("rfilename", "")
                file_size = file_info.get("size", 0)
                
                # Categorize file types
                if filename.endswith(".gguf"):
                    artifact_type = "gguf"
                elif filename.endswith(".safetensors"):
                    artifact_type = "safetensors"
                elif filename.endswith(".bin"):
                    artifact_type = "pytorch"
                else:
                    continue  # Skip non-model files
                
                artifact = {
                    "filename": filename,
                    "type": artifact_type,
                    "size": file_size,
                    "size_human": _format_bytes(file_size),
                    "recommended": False
                }
                
                artifacts.append(artifact)
            
            # Select recommended artifact (prefer GGUF for efficiency)
            if artifacts:
                # Prefer GGUF files, then safetensors, then pytorch
                gguf_files = [a for a in artifacts if a["type"] == "gguf"]
                safetensors_files = [a for a in artifacts if a["type"] == "safetensors"]
                pytorch_files = [a for a in artifacts if a["type"] == "pytorch"]
                
                if gguf_files:
                    # Prefer Q4_K_M quantization if available
                    q4_files = [a for a in gguf_files if "q4" in a["filename"].lower()]
                    recommended_artifact = q4_files[0] if q4_files else gguf_files[0]
                elif safetensors_files:
                    recommended_artifact = safetensors_files[0]
                elif pytorch_files:
                    recommended_artifact = pytorch_files[0]
                
                if recommended_artifact:
                    recommended_artifact["recommended"] = True
            
            # Apply size filter if specified
            if request.max_size_gb and hf_model.size:
                size_gb = hf_model.size / (1024 * 1024 * 1024)
                if size_gb > request.max_size_gb:
                    continue
            
            enhanced_model = HuggingFaceModelInfo(
                id=hf_model.id,
                name=hf_model.name,
                author=hf_model.author,
                description=hf_model.description,
                tags=hf_model.tags,
                downloads=hf_model.downloads,
                likes=hf_model.likes,
                created_at=hf_model.created_at,
                updated_at=hf_model.updated_at,
                library_name=hf_model.library_name,
                pipeline_tag=hf_model.pipeline_tag,
                license=hf_model.license,
                size=hf_model.size,
                family=hf_model.family,
                parameters=hf_model.parameters,
                quantization=hf_model.quantization,
                format=hf_model.format,
                artifacts=artifacts,
                recommended_artifact=recommended_artifact,
                locally_available=locally_available,
                local_path=local_path
            )
            
            enhanced_models.append(enhanced_model)
        
        return enhanced_models
        
    except Exception as e:
        logger.error(f"Failed to search HuggingFace models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/download", response_model=DownloadJobResponse)
async def download_model_enhanced(request: ModelDownloadRequest):
    """
    Download a model with intelligent artifact selection and progress tracking.
    
    This endpoint supports both HuggingFace Hub models and direct URL downloads
    with automatic format detection and local registration.
    """
    try:
        hf_service = get_huggingface_service()
        
        # Check if model exists on HuggingFace
        model_info = hf_service.get_model_info(request.model_id)
        if not model_info:
            raise HTTPException(
                status_code=404,
                detail=f"Model '{request.model_id}' not found on HuggingFace Hub"
            )
        
        # Select optimal artifact if not specified
        artifact_filename = request.artifact
        if not artifact_filename:
            from ai_karen_engine.inference.huggingface_service import DeviceCapabilities
            
            # Create device capabilities (could be enhanced with actual system detection)
            device_caps = DeviceCapabilities(
                has_gpu=False,  # Conservative default
                cpu_memory=8192,  # 8GB default
                supports_fp16=True,
                supports_int8=True,
                supports_int4=True
            )
            
            optimal_file = hf_service.select_optimal_artifact(
                model_info.files,
                request.preference,
                device_caps
            )
            
            if not optimal_file:
                raise HTTPException(
                    status_code=400,
                    detail="No suitable artifact found for download"
                )
            
            artifact_filename = optimal_file["rfilename"]
        
        # Validate artifact exists
        available_files = [f["rfilename"] for f in model_info.files]
        if artifact_filename not in available_files:
            raise HTTPException(
                status_code=400,
                detail=f"Artifact '{artifact_filename}' not found. Available: {available_files}"
            )
        
        # Get file info for size estimation
        file_info = next((f for f in model_info.files if f["rfilename"] == artifact_filename), None)
        estimated_size = file_info.get("size", 0) if file_info else None
        
        # Determine target directory
        target_dir = Path(request.target_directory or "models/downloads")
        target_path = target_dir / artifact_filename
        
        # Check if file already exists
        if target_path.exists() and not request.overwrite_existing:
            raise HTTPException(
                status_code=409,
                detail=f"File already exists: {target_path}. Set overwrite_existing=true to replace."
            )
        
        # Start download using HuggingFace service
        download_job = hf_service.download_model(
            model_id=request.model_id,
            artifact=artifact_filename,
            preference=request.preference
        )
        
        return DownloadJobResponse(
            job_id=download_job.id,
            model_id=request.model_id,
            artifact=artifact_filename,
            status=download_job.status,
            message=f"Started download of {request.model_id}/{artifact_filename}",
            estimated_size=estimated_size,
            target_path=str(target_path)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start model download: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/download/jobs/{job_id}")
async def get_download_job_status(job_id: str):
    """Get status of a download job with detailed progress information."""
    try:
        hf_service = get_huggingface_service()
        
        # Check both HF service jobs and simple local jobs
        job = hf_service.get_download_job(job_id)
        if job:
            return {
                "job_id": job.id,
                "model_id": job.model_id,
                "artifact": job.artifact,
                "status": job.status,
                "progress": job.progress,
                "downloaded_size": job.downloaded_size,
                "total_size": job.total_size,
                "speed": job.speed,
                "eta": job.eta,
                "error": job.error,
                "local_path": job.local_path,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "completed_at": job.completed_at
            }
        
        # Check simple local download jobs
        local_job = _JOBS.get(job_id)
        if local_job:
            return {
                "job_id": local_job.id,
                "model_id": "local_download",
                "status": local_job.status,
                "progress": local_job.progress,
                "error": local_job.error,
                "local_path": str(local_job.path),
                "url": local_job.url
            }
        
        raise HTTPException(status_code=404, detail="Download job not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get download job status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/download/jobs/{job_id}/cancel")
async def cancel_download_job(job_id: str):
    """Cancel a download job."""
    try:
        hf_service = get_huggingface_service()
        
        # Try HF service first
        if hf_service.cancel_download(job_id):
            return {"job_id": job_id, "status": "cancelled", "message": "Download cancelled successfully"}
        
        # Try simple local jobs
        local_job = _JOBS.get(job_id)
        if local_job:
            local_job.cancel()
            return {"job_id": job_id, "status": "cancelled", "message": "Download cancelled successfully"}
        
        raise HTTPException(status_code=404, detail="Download job not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel download job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/huggingface/popular")
async def get_popular_models(
    category: str = "general",
    limit: int = 10,
    format_preference: Optional[str] = None
):
    """Get popular models by category with format filtering."""
    try:
        hf_service = get_huggingface_service()
        
        # Define category-specific search terms
        category_queries = {
            "general": "llama OR mistral OR qwen OR phi",
            "coding": "code OR programming OR codellama",
            "chat": "chat OR instruct OR assistant",
            "small": "tiny OR mini OR small",
            "quantized": "gguf OR quantized"
        }
        
        query = category_queries.get(category, category)
        
        # Set up filters
        from ai_karen_engine.inference.huggingface_service import ModelFilters
        filters = ModelFilters(
            sort_by="downloads",
            sort_order="desc",
            task="text-generation",
            min_downloads=1000  # Only popular models
        )
        
        # Add format filter if specified
        if format_preference:
            if format_preference.lower() == "gguf":
                filters.tags = ["gguf"]
            elif format_preference.lower() == "safetensors":
                filters.library = "transformers"
        
        # Search for popular models
        models = hf_service.search_models(query=query, filters=filters, limit=limit)
        
        # Convert to simplified format for popular models display
        popular_models = []
        for model in models:
            description = model.description or ""
            description_display = (description[:200] + "...") if len(description) > 200 else description
            popular_models.append({
                "id": model.id,
                "name": model.name,
                "author": model.author,
                "description": description_display,
                "downloads": model.downloads,
                "likes": model.likes,
                "family": model.family,
                "parameters": model.parameters,
                "format": model.format,
                "size_human": _format_bytes(model.size) if model.size else "Unknown",
                "tags": (model.tags or [])[:5]  # Limit tags for display
            })
        
        return {
            "category": category,
            "models": popular_models,
            "total_found": len(popular_models),
            "note": f"Popular {category} models sorted by downloads"
        }
        
    except Exception as e:
        logger.error(f"Failed to get popular models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/huggingface/formats")
async def get_supported_huggingface_formats():
    """Get information about supported HuggingFace model formats and selection logic."""
    return {
        "supported_formats": {
            "gguf": {
                "description": "GGML Universal Format - CPU optimized, quantized",
                "advantages": ["Memory efficient", "Fast CPU inference", "Quantization support"],
                "recommended_for": ["CPU-only systems", "Memory-constrained environments", "Production deployment"],
                "file_extensions": [".gguf"],
                "typical_quantizations": ["Q2_K", "Q3_K", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"]
            },
            "safetensors": {
                "description": "Safe tensor format for PyTorch models",
                "advantages": ["GPU acceleration", "Full precision", "Fast loading"],
                "recommended_for": ["GPU systems", "Fine-tuning", "Research"],
                "file_extensions": [".safetensors"],
                "typical_quantizations": ["fp16", "bf16"]
            },
            "pytorch": {
                "description": "PyTorch native format",
                "advantages": ["Wide compatibility", "Full model access"],
                "recommended_for": ["Development", "Custom modifications"],
                "file_extensions": [".bin", ".pt", ".pth"],
                "typical_quantizations": ["fp32", "fp16"]
            }
        },
        "selection_logic": {
            "auto": "Automatically selects best format based on system capabilities",
            "preference_order": ["gguf", "safetensors", "pytorch"],
            "quantization_preference": ["Q4_K_M", "Q5_K_M", "Q3_K", "Q6_K", "Q8_0", "Q2_K"],
            "size_considerations": "Smaller quantizations preferred for memory efficiency"
        },
        "recommendations": {
            "cpu_only": "Use GGUF format with Q4_K_M quantization",
            "gpu_available": "Use safetensors format for best performance",
            "memory_limited": "Use GGUF with Q2_K or Q3_K quantization",
            "production": "Use GGUF Q4_K_M for balanced performance and size"
        }
    }

