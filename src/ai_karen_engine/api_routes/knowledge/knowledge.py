"""
Knowledge API Routes

API endpoints for knowledge search and retrieval functionality
supporting the enhanced code screen knowledge panel.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
try:
    from pydantic import BaseModel, ConfigDict
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict
import logging

from ai_karen_engine.services.knowledge.index_hub import (
    IndexHub,
    Department,
    Team,
    KnowledgeQuery,
    KnowledgeBackendUnavailableError,
)
from ai_karen_engine.services.knowledge.organizational_hierarchy import OrganizationalHierarchy
from ai_karen_engine.auth.session import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# Global instances (should be dependency injected in production)
_index_hub = None
_org_hierarchy = None

def get_index_hub():
    global _index_hub
    if _index_hub is None:
        _index_hub = IndexHub()
    return _index_hub

def get_org_hierarchy():
    global _org_hierarchy
    if _org_hierarchy is None:
        _org_hierarchy = OrganizationalHierarchy()
    return _org_hierarchy


class KnowledgeSearchRequest(BaseModel):
    """Request model for knowledge search."""
    query: str
    department: Optional[str] = None
    team: Optional[str] = None
    source_types: Optional[List[str]] = None
    max_results: int = 10
    min_confidence: float = 0.5


class CitationResponse(BaseModel):
    """Response model for citations."""
    source_id: str
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    confidence_score: float
    context_snippet: Optional[str] = None


class KnowledgeResultResponse(BaseModel):
    """Response model for knowledge search results."""
    content: str
    citations: List[CitationResponse]
    confidence_score: float
    source_metadata: Dict[str, Any]
    conceptual_relationships: List[str]


class KnowledgeSearchResponse(BaseModel):
    """Response model for knowledge search."""
    results: List[KnowledgeResultResponse]
    total_count: int
    query_info: Dict[str, Any]
    routing_info: Optional[Dict[str, Any]] = None


class DepartmentStatsResponse(BaseModel):
    """Response model for department statistics."""
    total_indices: int
    total_sources: int
    departments: Dict[str, int]
    teams: Dict[str, int]


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    user = Depends(get_current_user)
):
    """
    Search the knowledge base with organizational context.
    """
    try:
        # Convert string enums to proper enums
        department = None
        if request.department:
            try:
                department = Department(request.department.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid department: {request.department}")
        
        team = None
        if request.team:
            try:
                team = Team(request.team.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid team: {request.team}")
        
        # Create knowledge query
        knowledge_query = KnowledgeQuery(
            text=request.query,
            department=department,
            team=team,
            source_types=request.source_types,
            max_results=request.max_results,
            min_confidence=request.min_confidence,
            require_citations=True
        )
        
        # Perform search with organizational routing
        route, results = await get_org_hierarchy().process_query_with_routing(
            request.query, 
            get_index_hub()
        )
        
        # Convert results to response format
        result_responses = []
        for result in results:
            citations = [
                CitationResponse(
                    source_id=citation.source_id,
                    file_path=citation.file_path,
                    line_start=citation.line_start,
                    line_end=citation.line_end,
                    table_name=citation.table_name,
                    column_name=citation.column_name,
                    confidence_score=citation.confidence_score,
                    context_snippet=citation.context_snippet
                )
                for citation in result.citations
            ]
            
            result_responses.append(KnowledgeResultResponse(
                content=result.content,
                citations=citations,
                confidence_score=result.confidence_score,
                source_metadata=result.source_metadata,
                conceptual_relationships=result.conceptual_relationships
            ))
        
        return KnowledgeSearchResponse(
            results=result_responses,
            total_count=len(result_responses),
            query_info={
                "original_query": request.query,
                "processed_query": knowledge_query.text,
                "department": department.value if department else None,
                "team": team.value if team else None
            },
            routing_info={
                "routed_department": route.department.value,
                "routed_team": route.team.value if route.team else None,
                "intent_type": route.intent_type.value,
                "confidence": route.confidence,
                "reasoning": route.reasoning
            }
        )
    
    except HTTPException:
        raise
    except KnowledgeBackendUnavailableError:
        logger.warning("knowledge_search_backend_unavailable")
        raise HTTPException(status_code=503, detail="Knowledge search unavailable") from None
    except Exception:
        logger.exception("knowledge_search_failed")
        raise HTTPException(status_code=503, detail="Knowledge search unavailable") from None


@router.get("/departments", response_model=List[str])
async def get_departments(user = Depends(get_current_user)):
    """Get list of available departments."""
    return [dept.value for dept in Department]


@router.get("/teams", response_model=List[str])
async def get_teams(
    department: Optional[str] = Query(None, description="Filter teams by department"),
    user = Depends(get_current_user)
):
    """Get list of available teams, optionally filtered by department."""
    all_teams = [team.value for team in Team]
    
    if not department:
        return all_teams
    
    # Filter teams by department (simplified mapping)
    department_teams = {
        "engineering": ["frontend", "backend", "devops", "qa"],
        "operations": ["infrastructure", "security", "monitoring"],
        "business": ["product", "marketing", "sales"]
    }
    
    return department_teams.get(department.lower(), all_teams)


@router.get("/stats", response_model=DepartmentStatsResponse)
async def get_knowledge_stats(user = Depends(get_current_user)):
    """Get knowledge base statistics by department and team."""
    try:
        stats = await get_index_hub().get_department_statistics()
        return DepartmentStatsResponse(**stats)
    
    except KnowledgeBackendUnavailableError:
        logger.warning("knowledge_stats_backend_unavailable")
        raise HTTPException(status_code=503, detail="Knowledge statistics unavailable") from None
    except Exception:
        logger.exception("knowledge_stats_failed")
        raise HTTPException(status_code=503, detail="Knowledge statistics unavailable") from None


@router.get("/health")
async def knowledge_health_check(user = Depends(get_current_user)):
    """Health check for knowledge services."""
    try:
        health = await get_index_hub().health_check()
        org_hierarchy = get_org_hierarchy()
        return {
            "status": "healthy" if health.get("status") == "healthy" else "unavailable",
            "index_hub": health,
            "organizational_hierarchy": {
                "status": "healthy",
                "intent_patterns": len(org_hierarchy.intent_patterns),
                "routing_rules": len(org_hierarchy.routing_rules)
            }
        }
    
    except Exception:
        logger.exception("knowledge_health_check_failed")
        return {
            "status": "unavailable",
            "index_hub": {"status": "unavailable"},
        }


@router.post("/suggest")
async def get_contextual_suggestions(
    current_file: Optional[str] = None,
    current_operation: Optional[str] = None,
    user = Depends(get_current_user)
):
    """
    Get contextual suggestions based on current file/operation.
    """
    try:
        suggestions = []
        
        if current_file:
            # Generate file-based suggestions
            file_ext = current_file.split('.')[-1] if '.' in current_file else ''
            
            if file_ext in ['py', 'python']:
                suggestions.extend([
                    "Show Python best practices",
                    "Find similar functions",
                    "Check for code patterns",
                    "Review error handling"
                ])
            elif file_ext in ['js', 'ts', 'jsx', 'tsx']:
                suggestions.extend([
                    "Show React patterns",
                    "Find component examples",
                    "Check TypeScript usage",
                    "Review async patterns"
                ])
            elif file_ext in ['sql']:
                suggestions.extend([
                    "Show query optimization",
                    "Find schema references",
                    "Check indexing strategies",
                    "Review performance patterns"
                ])
        
        if current_operation:
            # Generate operation-based suggestions
            if "debug" in current_operation.lower():
                suggestions.extend([
                    "Common debugging patterns",
                    "Error handling examples",
                    "Logging best practices"
                ])
            elif "test" in current_operation.lower():
                suggestions.extend([
                    "Test patterns and examples",
                    "Mocking strategies",
                    "Coverage improvements"
                ])
        
        # Default suggestions if no context
        if not suggestions:
            suggestions = [
                "Search code patterns",
                "Find documentation",
                "Review architecture",
                "Check best practices"
            ]
        
        return {
            "suggestions": suggestions[:8],  # Limit to 8 suggestions
            "context": {
                "file": current_file,
                "operation": current_operation
            }
        }
    
    except Exception as e:
        logger.error(f"Error generating suggestions: {e}")
        return {"suggestions": [], "error": str(e)}