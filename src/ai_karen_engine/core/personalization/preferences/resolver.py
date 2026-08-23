"""
Preference resolver for AI-Karen personalization.

Resolves which preferences apply to a given task/context.
Does NOT decide actions - only determines known preferences.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..contracts import (
    PreferenceRecord,
    PreferenceScope,
    ResolvedPreferences,
)


class PreferenceResolver:
    """Resolves preferences for a specific task context."""

    def resolve(
        self,
        snapshot: Any,  # UserStateSnapshot to avoid circular import
        task_context: Dict[str, Any],
        requested_scope: Optional[PreferenceScope] = None,
    ) -> ResolvedPreferences:
        resolved: Dict[str, Any] = {}
        scopes_used: List[PreferenceScope] = []

        all_prefs = list(snapshot.stable_preferences) + list(snapshot.tentative_preferences)

        for pref in all_prefs:
            if self._applies(pref, task_context, requested_scope):
                resolved[pref.key] = pref.value
                if pref.scope not in scopes_used:
                    scopes_used.append(pref.scope)

        confidence = self._compute_confidence(snapshot)
        applied_scope = self._most_specific_scope(scopes_used)

        return ResolvedPreferences(
            user_id=snapshot.user_id,
            tenant_id=snapshot.tenant_id,
            task_context=task_context,
            resolved=resolved,
            confidence=confidence,
            applied_scope=applied_scope,
        )

    def _applies(
        self,
        pref: PreferenceRecord,
        task_context: Dict[str, Any],
        requested_scope: Optional[PreferenceScope],
    ) -> bool:
        if requested_scope and pref.scope != requested_scope:
            if pref.scope != PreferenceScope.GLOBAL:
                return False
        domain = task_context.get("domain") or task_context.get("domains", [None])[0]
        if pref.scope == PreferenceScope.DOMAIN and domain:
            return domain in pref.key or pref.metadata.get("domain") == domain
        if pref.scope == PreferenceScope.TASK_TYPE:
            task_type = task_context.get("task_type") or task_context.get("intent")
            return task_type and (task_type in pref.key or pref.metadata.get("task_type") == task_type)
        if pref.scope == PreferenceScope.PROJECT:
            project = task_context.get("project")
            return project and pref.metadata.get("project") == project
        return True

    def _compute_confidence(self, snapshot: Any) -> float:
        if not snapshot.stable_preferences and not snapshot.tentative_preferences:
            return 0.0
        all_prefs = snapshot.stable_preferences + snapshot.tentative_preferences
        return sum(p.confidence for p in all_prefs) / len(all_prefs)

    def _most_specific_scope(self, scopes: List[PreferenceScope]) -> PreferenceScope:
        order = [
            PreferenceScope.GLOBAL,
            PreferenceScope.TASK_TYPE,
            PreferenceScope.DOMAIN,
            PreferenceScope.PROJECT,
            PreferenceScope.SESSION,
            PreferenceScope.CONVERSATION,
        ]
        for s in order:
            if s in scopes:
                return s
        return PreferenceScope.GLOBAL


__all__ = ["PreferenceResolver"]
