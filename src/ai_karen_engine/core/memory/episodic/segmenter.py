"""Deterministic-first episodic event segmentation."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from .contracts import (
    EpisodeBoundaryReason,
    EpisodeFrame,
    EpisodeObservation,
    SegmentationDecision,
)


class EventSegmenter:
    """Choose whether a runtime observation continues or starts an episode."""

    TERMINAL_OUTCOMES = {"success", "failure", "failed", "completed", "abandoned", "cancelled"}

    def __init__(self, *, time_gap_seconds: int = 1800) -> None:
        if time_gap_seconds < 1:
            raise ValueError("time_gap_seconds must be positive")
        self.time_gap = timedelta(seconds=int(time_gap_seconds))

    def decide(
        self,
        previous: EpisodeFrame | None,
        observation: EpisodeObservation,
    ) -> SegmentationDecision:
        if previous is None:
            return SegmentationDecision(
                frame=EpisodeFrame.new(observation),
                new_episode=True,
                reason=EpisodeBoundaryReason.NEW_SESSION,
            )

        reason = self._boundary_reason(previous, observation)
        if reason not in {
            EpisodeBoundaryReason.CONTINUATION,
            EpisodeBoundaryReason.CORRECTION_ATTACHED,
        }:
            return SegmentationDecision(
                frame=EpisodeFrame.new(observation),
                new_episode=True,
                reason=reason,
            )

        observed_at = observation.normalized_time()
        frame = replace(
            previous,
            updated_at=observed_at,
            goal_key=observation.goal_key or previous.goal_key,
            project_key=observation.project_key or previous.project_key,
            last_outcome_class=observation.outcome_class or previous.last_outcome_class,
            last_text=observation.text,
            turn_count=previous.turn_count + 1,
        )
        return SegmentationDecision(frame=frame, new_episode=False, reason=reason)

    def _boundary_reason(
        self,
        previous: EpisodeFrame,
        observation: EpisodeObservation,
    ) -> EpisodeBoundaryReason:
        if observation.session_id != previous.session_id:
            return EpisodeBoundaryReason.SESSION_CHANGED

        if (
            previous.project_key
            and observation.project_key
            and previous.project_key != observation.project_key
        ):
            return EpisodeBoundaryReason.PROJECT_CHANGED

        if observation.normalized_time() - previous.updated_at > self.time_gap:
            return EpisodeBoundaryReason.TIME_GAP

        if observation.correction:
            # Corrections update the current episode unless a stronger scope/time
            # boundary above has already separated the context.
            return EpisodeBoundaryReason.CORRECTION_ATTACHED

        if (
            previous.goal_key
            and observation.goal_key
            and previous.goal_key != observation.goal_key
        ):
            return EpisodeBoundaryReason.GOAL_CHANGED

        prior_outcome = str(previous.last_outcome_class or "").casefold()
        if prior_outcome in self.TERMINAL_OUTCOMES:
            return EpisodeBoundaryReason.PRIOR_OUTCOME_CLOSED

        return EpisodeBoundaryReason.CONTINUATION


__all__ = ["EventSegmenter"]
