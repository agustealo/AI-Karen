from ai_karen_engine.core.intelligence.reward import RewardProjector


def _execution(
    trajectory: str,
    *,
    status: str = "success",
    persistence: bool = True,
    latency_ms: float = 1000.0,
    fallback_count: int = 0,
    schema_valid: bool | None = True,
) -> dict:
    return {
        "source": "runtime.execution",
        "trajectory_id": trajectory,
        "status": status,
        "response_completed": status == "success",
        "persistence_success": persistence,
        "latency_ms": latency_ms,
        "fallback_count": fallback_count,
        "schema_valid": schema_valid,
        "recorded_at": f"2026-10-03T12:00:{trajectory[-2:]:0>2}",
    }


def test_reward_projection_uses_evidence_not_message_volume() -> None:
    snapshot = RewardProjector().project(
        [_execution("t01"), {"source": "unrelated", "trajectory_id": "noise"}]
    )
    assert snapshot.evidence_count == 1
    assert snapshot.level == "Foundation"
    assert snapshot.average_quality > 0.0


def test_unknown_user_feedback_is_not_invented() -> None:
    snapshot = RewardProjector().project([_execution("t01")])
    evidence = snapshot.recent_evidence[0]
    assert "user_feedback" not in evidence.dimensions
    assert "user_feedback_unavailable" in evidence.reason_codes
    assert snapshot.dimension_coverage["user_feedback"] == 0.0


def test_explicit_feedback_increases_coverage() -> None:
    records = [
        _execution("t01"),
        {
            "source": "user.feedback",
            "trajectory_id": "t01",
            "feedback_type": "thumbs_up",
            "recorded_at": "2026-10-03T12:01:00",
        },
    ]
    snapshot = RewardProjector().project(records)
    assert snapshot.dimension_coverage["user_feedback"] == 1.0
    assert snapshot.recent_evidence[0].dimensions["user_feedback"] == 1.0


def test_daily_login_or_raw_interaction_streaks_do_not_exist() -> None:
    payload = RewardProjector().project([_execution("t01")]).to_dict()
    assert payload["principles"]["engagement_volume_rewarded"] is False
    assert payload["principles"]["daily_login_streaks_rewarded"] is False


def test_quality_run_requires_quality_and_confidence() -> None:
    records = [_execution(f"t{i:02d}") for i in range(1, 6)]
    snapshot = RewardProjector().project(records)
    assert snapshot.quality_run == 5
    milestone = next(item for item in snapshot.milestones if item.milestone_id == "quality_run_5")
    assert milestone.unlocked is True
