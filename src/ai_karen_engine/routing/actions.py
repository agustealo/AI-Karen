"""
KIRE routing actions registered as CORTEX predictors.

Intents:
- routing.select: choose provider+model for a task/query
- routing.profile: inspect active routing profile
- routing.health: summarize provider availability for routing
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from ai_karen_engine.core.cortex.predictors import register_predictor
from ai_karen_engine.routing.kire_router import KIRERouter
from ai_karen_engine.routing.types import RouteRequest
from ai_karen_engine.integrations.llm_registry import get_registry
from ai_karen_engine.routing.decision_logger import get_decision_logger
from ai_karen_engine.monitoring.kire_metrics import KIRE_ACTIONS_TOTAL


@dataclass
class TaskAnalysis:
    """Minimal stub for legacy routing compatibility."""

    task_type: str = "chat"
    required_capabilities: List[str] = field(default_factory=list)
    khrp_step_hint: Optional[str] = None
    hints: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.75
    user_need_state: Dict[str, Any] = field(default_factory=dict)


def _analyze_task(query: str, context: Optional[Dict[str, Any]] = None) -> TaskAnalysis:
    """Lightweight task analysis stub for legacy routing."""
    return TaskAnalysis(task_type=_task_from_query(query))


_router = KIRERouter(llm_registry=get_registry())
_logger = get_decision_logger()

_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_CALLS = 45
_rate_limit_lock = threading.Lock()
_rate_limit_counters: Dict[str, Deque[float]] = {}


def _require_admin(user_ctx: Dict[str, Any]) -> None:
    roles = set((user_ctx or {}).get("roles", []))
    scopes = set((user_ctx or {}).get("scopes", []))
    if "admin" in roles or "admin:write" in scopes:
        return
    raise PermissionError("RBAC_DENIED: admin privileges required")


def _task_from_query(query: str) -> str:
    q = query.lower()
    if any(k in q for k in ("code", "python", "typescript", "bug", "debug")):
        return "code"
    if any(k in q for k in ("summarize", "summary")):
        return "summarization"
    if any(k in q for k in ("reason", "think", "analyz")):
        return "reasoning"
    return "chat"


async def routing_select_handler(user_ctx: Dict[str, Any], query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_id = user_ctx.get("user_id", "anon")
    try:
        _require_routing_access(user_ctx)
        _enforce_rate_limit(user_id)
    except PermissionError:
        KIRE_ACTIONS_TOTAL.labels(action="routing.select", status="forbidden").inc()
        raise

    analysis = _analyze_task(query, context=context)
    task_type = (context or {}).get("task_type") or analysis.task_type
    khrp_step = (context or {}).get("khrp_step")
    requirements = (context or {}).get("requirements", {})

    # Emit start-like marker
    req_id = hashlib.md5(f"{user_id}:{time.time()}".encode()).hexdigest()[:10]
    _router.logger.log_start(req_id, user_id, "routing.select", {"task_type": task_type, "khrp_step": khrp_step})

    try:
        decision = await _router.route_provider_selection(
            RouteRequest(user_id=user_id, task_type=task_type, query=query, khrp_step=khrp_step, context=context or {}, requirements=requirements)
        )
        KIRE_ACTIONS_TOTAL.labels(action="routing.select", status="success").inc()
    except Exception as e:
        KIRE_ACTIONS_TOTAL.labels(action="routing.select", status="error").inc()
        raise

    return {
        "provider": decision.provider,
        "model": decision.model,
        "reasoning": decision.reasoning,
        "confidence": decision.confidence,
        "kire_metadata": {
            "task_type": task_type,
            "khrp_step": khrp_step,
            "fallback_chain": decision.fallback_chain,
            **(decision.metadata or {}),
            "task_analysis": {
                "required_capabilities": analysis.required_capabilities,
                "confidence": analysis.confidence,
                "step_hint": analysis.khrp_step_hint,
            },
        },
    }


async def routing_profile_handler(user_ctx: Dict[str, Any], query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Surface active profile + basic validation
    pr = _router.profile_resolver.get_user_profile(user_ctx.get("user_id", "anon"))
    if not pr:
        return {"active_profile": None, "valid": False, "errors": ["No active profile"]}
    errs = _router.profile_resolver.validate_profile(pr)
    out = {
        "active_profile": pr.name,
        "assignments": {k: {"provider": v.provider, "model": v.model} for k, v in pr.assignments.items()},
        "fallback_chain": pr.fallback_chain,
        "valid": len(errs) == 0,
        "errors": errs,
    }
    KIRE_ACTIONS_TOTAL.labels(action="routing.profile", status="success").inc()
    return out


async def routing_health_handler(user_ctx: Dict[str, Any], query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    reg = get_registry()
    providers = reg.list_providers()
    results = {name: reg.health_check(name) for name in providers}
    available = [name for name, h in results.items() if h.get("status") in ("healthy", "unknown")]
    KIRE_ACTIONS_TOTAL.labels(action="routing.health", status="success").inc()
    return {"results": results, "available": available}


# Mutable routing/profile ops with RBAC gates
async def routing_profile_set_handler(user_ctx: Dict[str, Any], query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _require_admin(user_ctx)
    profile_id = (context or {}).get("profile_id") or (user_ctx or {}).get("desired_profile")
    if not profile_id:
        raise ValueError("profile_id required")
    try:
        from ai_karen_engine.config.profile_manager import get_profile_manager
        pm = get_profile_manager()
        prof = pm.set_active_profile(profile_id, user_id=user_ctx.get("user_id"))
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.set", status="success").inc()
        return {"ok": True, "active_profile": prof.id}
    except Exception as ex:
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.set", status="error").inc()
        return {"ok": False, "error": str(ex)}


async def routing_profile_reload_handler(user_ctx: Dict[str, Any], query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _require_admin(user_ctx)
    try:
        from ai_karen_engine.config.profile_manager import get_profile_manager
        pm = get_profile_manager()
        pm.reload_profiles()
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.reload", status="success").inc()
        return {"ok": True}
    except Exception as ex:
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.reload", status="error").inc()
        return {"ok": False, "error": str(ex)}


# Audit + Dry-run utilities
async def routing_audit_history_handler(user_ctx: Dict[str, Any], query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    limit = int((context or {}).get("limit", 100))
    user_id = (context or {}).get("user_id")
    KIRE_ACTIONS_TOTAL.labels(action="routing.audit", status="success").inc()
    return {"events": _logger.get_history(limit=limit, user_id=user_id)}


async def routing_dry_run_handler(user_ctx: Dict[str, Any], query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    analysis = _analyze_task(query, context=context)
    # Do not call providers; only compute decision inputs
    KIRE_ACTIONS_TOTAL.labels(action="routing.dry-run", status="success").inc()
    return {
        "dry_run": True,
        "analysis": {
            "task_type": analysis.task_type,
            "required_capabilities": analysis.required_capabilities,
            "khrp_step_hint": analysis.khrp_step_hint,
            "confidence": analysis.confidence,
        },
    }


# Register predictors on import
register_predictor("routing.select", routing_select_handler)
register_predictor("routing.profile", routing_profile_handler)
register_predictor("routing.health", routing_health_handler)
register_predictor("routing.profile.set", routing_profile_set_handler)
register_predictor("routing.profile.reload", routing_profile_reload_handler)
register_predictor("routing.audit", routing_audit_history_handler)
register_predictor("routing.dry-run", routing_dry_run_handler)

# ------------------------------
# Profile management (list/validate/export/import)
# ------------------------------

async def routing_profile_list_handler(user_ctx: Dict[str, Any], payload: Dict[str, Any] | None = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from ai_karen_engine.config.user_profiles import get_user_profiles_manager
        upm = get_user_profiles_manager()
        profiles = upm.list_profiles()
        active = upm.get_active_profile()
        out = {
            "active_profile": active.id if active else None,
            "profiles": [
                {
                    "id": p.id,
                    "name": p.name,
                    "is_active": bool(active and p.id == active.id),
                    "assignments_count": len(p.assignments or {}),
                    "fallback_chain": p.fallback_chain,
                }
                for p in profiles
            ],
        }
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.list", status="success").inc()
        return out
    except Exception as ex:
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.list", status="error").inc()
        return {"error": str(ex)}


async def routing_profile_validate_handler(user_ctx: Dict[str, Any], payload: Dict[str, Any] | None = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        profile_id = (payload or {}).get("profile_id")
        from ai_karen_engine.config.user_profiles import get_user_profiles_manager
        upm = get_user_profiles_manager()
        prof = upm.get_profile(profile_id) if profile_id else upm.get_active_profile()
        if not prof:
            return {"ok": False, "errors": ["Profile not found"]}
        errs = upm.validate_profile(prof)
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.validate", status="success").inc()
        return {"ok": len(errs) == 0, "errors": errs, "profile_id": prof.id}
    except Exception as ex:
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.validate", status="error").inc()
        return {"ok": False, "error": str(ex)}


async def routing_profile_export_handler(user_ctx: Dict[str, Any], payload: Dict[str, Any] | None = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from ai_karen_engine.config.user_profiles import get_user_profiles_manager
        upm = get_user_profiles_manager()
        pid = (payload or {}).get("profile_id")
        if pid:
            prof = upm.get_profile(pid)
            if not prof:
                return {"ok": False, "error": "Profile not found"}
            data = prof.to_json()
        else:
            data = [p.to_json() for p in upm.list_profiles()]
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.export", status="success").inc()
        return {"ok": True, "data": data}
    except Exception as ex:
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.export", status="error").inc()
        return {"ok": False, "error": str(ex)}


async def routing_profile_import_handler(user_ctx: Dict[str, Any], payload: Dict[str, Any] | None = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Admin only
    _require_admin(user_ctx)
    try:
        from ai_karen_engine.config.user_profiles import get_user_profiles_manager, UserProfile, ModelAssignment
        upm = get_user_profiles_manager()
        data = (payload or {}).get("data")
        set_active = (payload or {}).get("set_active")
        if not data:
            return {"ok": False, "error": "No data provided"}
        imported = []
        items = data if isinstance(data, list) else [data]
        for item in items:
            # Convert to UserProfile
            assignments = {}
            for tt, ma in (item.get("assignments") or {}).items():
                assignments[tt] = ModelAssignment(task_type=tt, provider=ma.get("provider", ""), model=ma.get("model", ""), parameters=ma.get("parameters", {}))
            prof = UserProfile(
                id=item["id"],
                name=item.get("name", item["id"]),
                assignments=assignments,
                fallback_chain=item.get("fallback_chain", []),
                is_active=False,
            )
            existing = upm.get_profile(prof.id)
            if existing:
                upm.update_profile(prof)
            else:
                upm.create_profile(prof)
            imported.append(prof.id)
        if set_active and imported:
            upm.set_active_profile(imported[0])
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.import", status="success").inc()
        return {"ok": True, "imported": imported, "active": upm.get_active_profile().id if upm.get_active_profile() else None}
    except Exception as ex:
        KIRE_ACTIONS_TOTAL.labels(action="routing.profile.import", status="error").inc()
        return {"ok": False, "error": str(ex)}


register_predictor("routing.profile.list", routing_profile_list_handler)
register_predictor("routing.profile.validate", routing_profile_validate_handler)
register_predictor("routing.profile.export", routing_profile_export_handler)
register_predictor("routing.profile.import", routing_profile_import_handler)
def _require_routing_access(user_ctx: Dict[str, Any]) -> None:
    roles = {r.lower() for r in (user_ctx or {}).get("roles", [])}
    scopes = {s.lower() for s in (user_ctx or {}).get("scopes", [])}
    if roles.intersection({"admin", "routing", "ops"}) or scopes.intersection({"routing:select", "routing:*", "llm:route"}):
        return
    raise PermissionError("RBAC_DENIED: routing.select requires routing role or scope")


def _enforce_rate_limit(user_id: str) -> None:
    key = user_id or "anon"
    now = time.time()
    with _rate_limit_lock:
        bucket = _rate_limit_counters.setdefault(key, deque())
        while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT_MAX_CALLS:
            raise PermissionError("RATE_LIMIT_EXCEEDED: routing.select throttle hit")
        bucket.append(now)
