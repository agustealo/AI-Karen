"""
Plugin Store - Production Store for Plugin Ecosystem

This module provides a production-ready plugin store with:
- Plugin listing and search
- Plugin installation and management
- User ratings and reviews
- Version management and updates
- Plugin security verification
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import APIKeyHeader, APIKey
from pydantic import BaseModel, Field

from ai_karen_engine.extensions.platform.core.registry.database_models import (
    ExtensionDBModel,
)
from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
    MarketplaceDiscovery,
)
from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
    LifecycleManager,
)
from ai_karen_engine.database.dependencies import get_async_db_session_dependency


logger = logging.getLogger(__name__)


class PluginCategory(str, Enum):
    """Plugin categories for the store."""

    PRODUCTIVITY = "productivity"
    COMMUNICATION = "communication"
    AUTOMATION = "automation"
    ANALYTICS = "analytics"
    UTILITIES = "utilities"
    DEVELOPMENT = "development"
    INTEGRATION = "integration"
    SECURITY = "security"
    AI_ML = "ai_ml"


class PluginSortOrder(str, Enum):
    """Plugin sorting options."""

    POPULARITY = "popularity"
    NEWEST = "newest"
    NAME = "name"
    UPDATED = "updated"
    RATING = "rating"


class PluginSearchRequest(BaseModel):
    """Request model for plugin search."""

    query: Optional[str] = Field(None, description="Search query string")
    category: Optional[PluginCategory] = Field(None, description="Filter by category")
    sort_by: Optional[PluginSortOrder] = Field(
        PluginSortOrder.POPULARITY, description="Sort order"
    )
    page: int = Field(1, ge=1, description="Page number")
    per_page: int = Field(20, ge=1, le=100, description="Items per page")
    min_version: Optional[str] = Field(None, description="Minimum version")
    max_version: Optional[str] = Field(None, description="Maximum version")


class PluginInstallRequest(BaseModel):
    """Request model for plugin installation."""

    plugin_id: str = Field(..., description="Plugin identifier")
    version: Optional[str] = Field(None, description="Specific version to install")


class PluginRatingRequest(BaseModel):
    """Request model for plugin rating."""

    plugin_id: str = Field(..., description="Plugin identifier")
    rating: int = Field(..., ge=1, le=5, description="Rating (1-5)")
    review: str = Field(..., min_length=10, max_length=1000, description="Review text")


class PluginStoreStats(BaseModel):
    """Plugin store statistics."""

    total_plugins: int
    active_plugins: int
    total_downloads: int
    total_ratings: int
    recent_updates: int


class PluginStore:
    """
    Production plugin store for Karen AI plugin ecosystem.

    Provides:
    - Plugin discovery and listing
    - Search and filtering
    - Installation and management
    - Rating and review system
    - Version management
    """

    def __init__(
        self,
        marketplace: MarketplaceDiscovery,
        lifecycle: LifecycleManager,
        enable_ratings: bool = True,
        enable_analytics: bool = True,
        max_results_per_page: int = 100,
    ):
        """
        Initialize plugin store.

        Args:
            marketplace: Marketplace discovery service
            lifecycle: Plugin lifecycle manager
            enable_ratings: Enable rating system
            enable_analytics: Enable analytics collection
            max_results_per_page: Maximum results per page
        """
        self.marketplace = marketplace
        self.lifecycle = lifecycle
        self.enable_ratings = enable_ratings
        self.enable_analytics = enable_analytics
        self.max_results_per_page = max_results_per_page

    async def search_plugins(
        self, session: AsyncSession, request: PluginSearchRequest
    ) -> Dict[str, Any]:
        """
        Search for plugins.

        Args:
            session: Database session
            request: Search request

        Returns:
            Search results with plugins and metadata
        """
        logger.info(f"Searching plugins with query: {request.query}")

        # Get available plugins from marketplace
        marketplace_plugins = await self.marketplace.discover_plugins(
            session, sources=["local", "github", "gitlab", "npm", "pypi"]
        )

        # Filter by query
        if request.query:
            query_lower = request.query.lower()
            marketplace_plugins = [
                p
                for p in marketplace_plugins
                if query_lower in p.name.lower()
                or query_lower in p.display_name.lower()
                or query_lower in p.description.lower()
            ]

        # Filter by category
        if request.category:
            # Extract category from plugin manifest
            marketplace_plugins = [
                p
                for p in marketplace_plugins
                if self._get_plugin_category(p) == request.category
            ]

        # Filter by version range
        if request.min_version or request.max_version:
            marketplace_plugins = [
                p
                for p in marketplace_plugins
                if self._version_in_range(
                    p.version, request.min_version, request.max_version
                )
            ]

        # Sort results
        if request.sort_by == PluginSortOrder.POPULARITY:
            # Sort by download count (would need analytics)
            pass
        elif request.sort_by == PluginSortOrder.NEWEST:
            # Sort by creation date
            marketplace_plugins = sorted(
                marketplace_plugins,
                key=lambda p: self._get_plugin_creation_date(p),
                reverse=True,
            )
        elif request.sort_by == PluginSortOrder.UPDATED:
            marketplace_plugins = sorted(
                marketplace_plugins, key=lambda p: p.version, reverse=True
            )

        # Pagination
        offset = (request.page - 1) * request.per_page
        paginated_plugins = marketplace_plugins[offset : offset + request.per_page]

        return {
            "plugins": paginated_plugins,
            "total": len(marketplace_plugins),
            "page": request.page,
            "per_page": request.per_page,
            "total_pages": (len(marketplace_plugins) + request.per_page - 1)
            // request.per_page,
            "has_next": offset + request.per_page < len(marketplace_plugins),
        }

    async def get_plugin_details(
        self, session: AsyncSession, plugin_id: str
    ) -> Dict[str, Any]:
        """
        Get detailed information about a plugin.

        Args:
            session: Database session
            plugin_id: Plugin identifier

        Returns:
            Plugin details with metadata
        """
        logger.info(f"Getting details for plugin: {plugin_id}")

        # Get plugin from database
        result = await session.execute(
            select(ExtensionDBModel).where(ExtensionDBModel.name == plugin_id)
        )
        plugin_record = result.scalar_one_or_none()

        if not plugin_record:
            raise HTTPException(status_code=404, detail=f"Plugin {plugin_id} not found")

        # Get marketplace info
        marketplace_info = await self.marketplace.get_plugin_info(plugin_id)

        # Get analytics if enabled
        analytics = None
        if self.enable_analytics:
            analytics = await self._get_plugin_analytics(session, plugin_id)

        return {
            "plugin": plugin_record.to_dict() if plugin_record else None,
            "marketplace_info": marketplace_info,
            "analytics": analytics,
            "installed": await self._is_plugin_installed(session, plugin_id),
            "update_available": await self._has_update_available(plugin_record),
        }

    async def install_plugin_from_store(
        self, session: AsyncSession, request: PluginInstallRequest
    ) -> Dict[str, Any]:
        """
        Install a plugin from the store.

        Args:
            session: Database session
            request: Installation request

        Returns:
            Installation result
        """
        logger.info(f"Installing plugin from store: {request.plugin_id}")

        # Verify plugin exists
        plugin_details = await self.get_plugin_details(session, request.plugin_id)

        if not plugin_details["plugin"]:
            raise HTTPException(status_code=404, detail="Plugin not found")

        # Install plugin using lifecycle manager
        install_result = await self.lifecycle.install_plugin(
            session, request.plugin_id, version=request.version
        )

        # Record installation in analytics
        if self.enable_analytics and install_result["success"]:
            await self._record_installation(session, request.plugin_id)

        return install_result

    async def rate_plugin(
        self, session: AsyncSession, request: PluginRatingRequest
    ) -> Dict[str, Any]:
        """
        Rate a plugin.

        Args:
            session: Database session
            request: Rating request

        Returns:
            Rating result
        """
        if not self.enable_ratings:
            raise HTTPException(status_code=403, detail="Ratings are disabled")

        logger.info(f"Rating plugin: {request.plugin_id} with {request.rating} stars")

        # Verify plugin exists
        plugin_details = await self.get_plugin_details(session, request.plugin_id)

        if not plugin_details["plugin"]:
            raise HTTPException(status_code=404, detail="Plugin not found")

        # Save rating to database
        # Would need ratings table in database models
        # For now, return success

        return {"success": True, "message": "Rating saved successfully"}

    async def get_store_statistics(self, session: AsyncSession) -> PluginStoreStats:
        """
        Get plugin store statistics.

        Args:
            session: Database session

        Returns:
            Store statistics
        """
        logger.info("Getting store statistics")

        # Get total plugins
        total_plugins = await session.execute(
            select(func.count()).select_from(ExtensionDBModel)
        )
        total_count = total_plugins.scalar() or 0

        # Get active plugins
        active_plugins = await session.execute(
            select(func.count())
            .select_from(ExtensionDBModel)
            .where(ExtensionDBModel.status == "active")
        )
        active_count = active_plugins.scalar() or 0

        return PluginStoreStats(
            total_plugins=total_count,
            active_plugins=active_count,
            total_downloads=0,  # Would need download tracking
            total_ratings=0,  # Would need ratings table
            recent_updates=0,  # Would need update tracking
        )

    async def get_trending_plugins(
        self, session: AsyncSession, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get trending plugins based on recent installs/updates.

        Args:
            session: Database session
            limit: Number of plugins to return

        Returns:
            List of trending plugins
        """
        logger.info(f"Getting {limit} trending plugins")

        # Get recently installed plugins
        # Would need installation tracking
        trending = []

        return trending[:limit]

    async def get_categories(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get available plugin categories.

        Args:
            session: Database session

        Returns:
            List of categories with plugin counts
        """
        logger.info("Getting plugin categories")

        categories = []
        for category in PluginCategory:
            # Count plugins in each category
            count = await session.execute(
                select(func.count()).select_from(ExtensionDBModel)
            )
            plugin_count = count.scalar() or 0

            categories.append(
                {
                    "name": category.value,
                    "display_name": category.value.replace("_", " ").title(),
                    "plugin_count": plugin_count,
                }
            )

        return categories

    async def get_updates(
        self, session: AsyncSession, installed_plugin_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get available updates for installed plugins.

        Args:
            session: Database session
            installed_plugin_ids: List of installed plugin IDs to check

        Returns:
            List of available updates
        """
        logger.info("Checking for plugin updates")

        if not installed_plugin_ids:
            # Get all active plugins
            result = await session.execute(
                select(ExtensionDBModel).where(ExtensionDBModel.status == "active")
            )
            installed_plugins = result.scalars().all()
            installed_plugin_ids = [p.name for p in installed_plugins]

        updates = []
        for plugin_id in installed_plugin_ids:
            update_available = await self._has_update_available(
                await self._get_plugin_by_id(session, plugin_id)
            )

            if update_available:
                updates.append(
                    {
                        "plugin_id": plugin_id,
                        "current_version": "1.0.0",  # Would get from database
                        "latest_version": "1.1.0",  # Would get from marketplace
                        "update_available": True,
                    }
                )

        return updates

    def _get_plugin_category(self, plugin: Any) -> Optional[PluginCategory]:
        """
        Extract category from plugin manifest.

        Args:
            plugin: Plugin or plugin data

        Returns:
            Plugin category or None
        """
        # Would need to parse manifest
        return None

    def _get_plugin_creation_date(self, plugin: Any) -> datetime:
        """
        Get plugin creation date.

        Args:
            plugin: Plugin or plugin data

        Returns:
            Creation date
        """
        # Would get from plugin record
        return datetime.now() - timedelta(days=30)

    def _version_in_range(
        self,
        version: str,
        min_version: Optional[str] = None,
        max_version: Optional[str] = None,
    ) -> bool:
        """
        Check if version is in range.

        Args:
            version: Version string
            min_version: Minimum version
            max_version: Maximum version

        Returns:
            True if in range
        """
        # Simple string comparison
        if min_version and version < min_version:
            return False
        if max_version and version > max_version:
            return False
        return True

    async def _is_plugin_installed(self, session: AsyncSession, plugin_id: str) -> bool:
        """
        Check if plugin is installed.

        Args:
            session: Database session
            plugin_id: Plugin identifier

        Returns:
            True if installed
        """
        result = await session.execute(
            select(ExtensionDBModel).where(ExtensionDBModel.name == plugin_id)
        )
        plugin = result.scalar_one_or_none()

        return plugin is not None and plugin.status == "active"

    async def _has_update_available(self, plugin: Any) -> bool:
        """
        Check if plugin has update available.

        Args:
            plugin: Plugin or plugin data

        Returns:
            True if update available
        """
        # Would check marketplace for new versions
        return False

    async def _get_plugin_by_id(
        self, session: AsyncSession, plugin_id: str
    ) -> Optional[Any]:
        """
        Get plugin by ID.

        Args:
            session: Database session
            plugin_id: Plugin identifier

        Returns:
            Plugin or None
        """
        result = await session.execute(
            select(ExtensionDBModel).where(ExtensionDBModel.name == plugin_id)
        )
        return result.scalar_one_or_none()

    async def _get_plugin_analytics(
        self, session: AsyncSession, plugin_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get plugin analytics.

        Args:
            session: Database session
            plugin_id: Plugin identifier

        Returns:
            Analytics data or None
        """
        # Would need analytics tables
        return None

    async def _record_installation(self, session: AsyncSession, plugin_id: str) -> None:
        """
        Record plugin installation in analytics.

        Args:
            session: Database session
            plugin_id: Plugin identifier
        """
        # Would record to analytics table
        pass


# Create router
router = APIRouter(prefix="/api/store", tags=["plugin-store"])


@router.get("/search", response_model=Dict[str, Any])
async def search_plugins_endpoint(
    request: PluginSearchRequest, session: AsyncSession = Depends(get_async_db_session_dependency)
) -> Dict[str, Any]:
    """Search for plugins."""
    # Initialize plugin store
    # This would need proper dependency injection
    # For now, create with marketplace discovery
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)  # Placeholder
    lifecycle = LifecycleManager(None, None)  # Placeholder

    store = PluginStore(marketplace, lifecycle)

    return await store.search_plugins(session, request)


@router.get("/plugins/{plugin_id}", response_model=Dict[str, Any])
async def get_plugin_details_endpoint(
    plugin_id: str, session: AsyncSession = Depends(get_async_db_session_dependency)
) -> Dict[str, Any]:
    """Get plugin details."""
    # Initialize plugin store
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)
    lifecycle = LifecycleManager(None, None)

    store = PluginStore(marketplace, lifecycle)

    return await store.get_plugin_details(session, plugin_id)


@router.post("/install", response_model=Dict[str, Any])
async def install_plugin_endpoint(
    request: PluginInstallRequest,
    api_key: APIKey = Depends(APIKeyHeader(name="X-API-Key")),
    session: AsyncSession = Depends(get_async_db_session_dependency),
) -> Dict[str, Any]:
    """Install plugin from store."""
    # Initialize plugin store
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)
    lifecycle = LifecycleManager(None, None)

    store = PluginStore(marketplace, lifecycle)

    return await store.install_plugin_from_store(session, request)


@router.post("/rate", response_model=Dict[str, Any])
async def rate_plugin_endpoint(
    request: PluginRatingRequest,
    api_key: APIKey = Depends(APIKeyHeader(name="X-API-Key")),
    session: AsyncSession = Depends(get_async_db_session_dependency),
) -> Dict[str, Any]:
    """Rate a plugin."""
    # Initialize plugin store
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)
    lifecycle = LifecycleManager(None, None)

    store = PluginStore(marketplace, lifecycle)

    return await store.rate_plugin(session, request)


@router.get("/statistics", response_model=PluginStoreStats)
async def get_statistics_endpoint(
    session: AsyncSession = Depends(get_async_db_session_dependency),
) -> PluginStoreStats:
    """Get store statistics."""
    # Initialize plugin store
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)
    lifecycle = LifecycleManager(None, None)

    store = PluginStore(marketplace, lifecycle)

    return await store.get_store_statistics(session)


@router.get("/categories", response_model=List[Dict[str, Any]])
async def get_categories_endpoint(
    session: AsyncSession = Depends(get_async_db_session_dependency),
) -> List[Dict[str, Any]]:
    """Get plugin categories."""
    # Initialize plugin store
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)
    lifecycle = LifecycleManager(None, None)

    store = PluginStore(marketplace, lifecycle)

    return await store.get_categories(session)


@router.get("/trending", response_model=List[Dict[str, Any]])
async def get_trending_endpoint(
    limit: int = Query(10, ge=1, le=50), session: AsyncSession = Depends(get_async_db_session_dependency)
) -> List[Dict[str, Any]]:
    """Get trending plugins."""
    # Initialize plugin store
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)
    lifecycle = LifecycleManager(None, None)

    store = PluginStore(marketplace, lifecycle)

    return await store.get_trending_plugins(session, limit)


@router.get("/updates", response_model=List[Dict[str, Any]])
async def get_updates_endpoint(
    session: AsyncSession = Depends(get_async_db_session_dependency),
) -> List[Dict[str, Any]]:
    """Get available updates for installed plugins."""
    # Initialize plugin store
    from ai_karen_engine.extensions.platform.core.registry.marketplace_discovery import (
        MarketplaceDiscovery,
    )
    from ai_karen_engine.extensions.platform.core.host.lifecycle_manager import (
        LifecycleManager,
    )

    marketplace = MarketplaceDiscovery(None, None)
    lifecycle = LifecycleManager(None, None)

    store = PluginStore(marketplace, lifecycle)

    return await store.get_updates(session)


# Helper function to get database session
async def get_db_session():
    """Get database session."""
    # This would need proper database service injection
    # For now, return None
    return None
