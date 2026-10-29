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
    PreferenceState,
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

        # Narrower, applicable preferences override broad defaults.
        # Stable values take precedence over tentative values at equal scope.
        priority = {
            PreferenceScope.GLOBAL: 0,
            PreferenceScope.DOMAIN: 1,
            PreferenceScope.TASK_TYPE: 2,
            PreferenceScope.PROJECT: 3,
            PreferenceScope.SESSION: 4,
            PreferenceScope.CONVERSATION: 5,
        }
        all_prefs = list(snapshot.tentative_preferences) + list(snapshot.stable_preferences)
        all_prefs.sort(
            key=lambda pref: (
                priority.get(pref.scope, -1),
                pref.state == PreferenceState.STABLE,
                pref.version,
                pref.preference_id,
            )
        )
        applied = []
        for pref in all_prefs:
            if self._applies(pref, task_context, requested_scope):
                resolved[pref.key] = pref.value
                applied.append(pref)
                if pref.scope not in scopes_used:
                    scopes_used.append(pref.scope)

        confidence = (
            sum(pref.confidence for pref in applied) / len(applied)
            if applied else 0.0
        )
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
        if requested_scope and pref.scope not in (requested_scope, PreferenceScope.GLOBAL):
            return False

        # The runtime must supply an authenticated persona context; neither
        # client metadata nor quoted user messages are authorization.
        persona_id = pref.metadata.get("persona_id")
        if persona_id and task_context.get("persona_id") != persona_id:
            return False

        if pref.scope == PreferenceScope.GLOBAL:
            return True

        selectors = {
            PreferenceScope.DOMAIN: "domain",
            PreferenceScope.TASK_TYPE: "task_type",
            PreferenceScope.PROJECT: "project",
            PreferenceScope.SESSION: "session_id",
            PreferenceScope.CONVERSATION: "conversation_id",
        }
        field = selectors.get(pref.scope)
        if field is None:
            return False

        current = task_context.get(field)
        if pref.scope == PreferenceScope.DOMAIN and current is None:
            current = task_context.get("domains")
        if pref.scope == PreferenceScope.TASK_TYPE and current is None:
            current = task_context.get("intent")
        expected = pref.metadata.get(field)
        if current is None or expected is None or expected == "":
            return False
        if isinstance(current, (list, tuple)):
            return bool(current) and any(item == expected for item in current)
        return current == expected

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
        for s in reversed(order):
            if s in scopes:
                return s
        return PreferenceScope.GLOBAL


__all__ = ["PreferenceResolver"]
