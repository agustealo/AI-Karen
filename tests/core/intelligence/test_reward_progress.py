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


def test_unknown_durability_is_not_rewarded_as_success() -> None:
    record = _execution("t01")
    record["persistence_success"] = None
    snapshot = RewardProjector().project([record])
    evidence = snapshot.recent_evidence[0]
    assert "durability" not in evidence.dimensions
    assert snapshot.dimension_coverage["durability"] == 0.0


def test_latest_feedback_supersedes_prior_feedback_without_erasing_audit_history() -> None:
    records = [
        _execution("t01"),
        {
            "source": "user.feedback",
            "trajectory_id": "t01",
            "feedback_type": "thumbs_down",
            "recorded_at": "2026-10-03T12:01:00",
        },
        {
            "source": "user.feedback",
            "trajectory_id": "t01",
            "feedback_type": "thumbs_up",
            "recorded_at": "2026-10-03T12:02:00",
        },
    ]
    snapshot = RewardProjector().project(records)
    assert snapshot.recent_evidence[0].dimensions["user_feedback"] == 1.0


def test_failed_executions_do_not_create_growth_progress() -> None:
    failures = [
        _execution(f"f{i:02d}", status="failure")
        for i in range(1, 26)
    ]
    snapshot = RewardProjector().project(failures)
    assert snapshot.observed_outcome_count == 25
    assert snapshot.completed_outcome_count == 0
    assert snapshot.evidence_count == 0
    assert snapshot.progress_index == 0.0
    assert snapshot.average_quality == 0.0
    assert snapshot.level == "Foundation"
    assert snapshot.recent_evidence == ()


def test_failed_attempts_do_not_increase_level_depth() -> None:
    records = [_execution("t01"), *[
        _execution(f"f{i:02d}", status="failure")
        for i in range(2, 30)
    ]]
    snapshot = RewardProjector().project(records)
    assert snapshot.completed_outcome_count == 1
    assert snapshot.observed_outcome_count == 29
    assert snapshot.level == "Foundation"



def test_partial_successes_do_not_unlock_quality_run() -> None:
    records = [
        _execution(f"p{i:02d}", status="partial_success")
        for i in range(1, 6)
    ]
    snapshot = RewardProjector().project(records)
    assert snapshot.completed_outcome_count == 0
    assert snapshot.quality_run == 0
    milestone = next(
        item for item in snapshot.milestones
        if item.milestone_id == "quality_run_5"
    )
    assert milestone.unlocked is False


def test_failed_attempt_after_completed_work_does_not_erase_completed_quality_run() -> None:
    records = [
        *[_execution(f"t{i:02d}") for i in range(1, 6)],
        _execution("f06", status="failure"),
    ]
    snapshot = RewardProjector().project(records)
    assert snapshot.completed_outcome_count == 5
    assert snapshot.quality_run == 5
