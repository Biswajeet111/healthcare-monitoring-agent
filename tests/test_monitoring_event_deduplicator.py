from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from healthguard.agents.monitoring_event_deduplicator import (
    generate_event_fingerprint,
    evaluate_event_deduplication,
    MonitoringEventDeduplicationError,
)


NOW = datetime(
    2026, 11, 10, 12, 0,
    tzinfo=timezone.utc,
)


def make_event(
    event_type="statistical_deviation",
    metric_type="blood_glucose",
    unit="mg/dL",
):
    configurations = {
        "statistical_deviation": (
            "review",
            "review_recommended",
            "statistical_deviation_detected",
        ),
        "insufficient_baseline_variability": (
            "informational",
            "more_data_needed",
            "insufficient_baseline_variability",
        ),
        "routine_monitoring": (
            "routine",
            "routine_tracking",
            "within_configured_threshold",
        ),
    }

    level, priority, status = configurations[event_type]

    return {
        "event_type": event_type,
        "event_level": level,
        "metric_type": metric_type,
        "unit": unit,
        "monitoring_priority": priority,
        "statistical_status": status,
        "classification_status": "completed",
        "created_at": NOW.isoformat(),
    }


def previous_record(
    user_id,
    fingerprint,
    minutes_ago,
):
    return {
        "user_id": user_id,
        "fingerprint": fingerprint,
        "notified_at": (
            NOW - timedelta(minutes=minutes_ago)
        ).isoformat(),
    }


# ============================================================
# FINGERPRINT TESTS
# ============================================================

def test_fingerprint_is_deterministic():
    event = make_event()

    first = generate_event_fingerprint(1, event)
    second = generate_event_fingerprint(1, event)

    assert first == second
    assert len(first) == 64


def test_fingerprint_ignores_timestamp():
    event = make_event()
    modified = deepcopy(event)

    modified["created_at"] = (
        NOW + timedelta(hours=2)
    ).isoformat()

    assert (
        generate_event_fingerprint(1, event)
        == generate_event_fingerprint(1, modified)
    )


def test_fingerprint_ignores_measurement_evidence():
    event = make_event()
    modified = deepcopy(event)

    event["evidence"] = {"latest_value": 110}
    modified["evidence"] = {"latest_value": 150}

    assert (
        generate_event_fingerprint(1, event)
        == generate_event_fingerprint(1, modified)
    )


def test_fingerprint_differs_by_user():
    event = make_event()

    assert (
        generate_event_fingerprint(1, event)
        != generate_event_fingerprint(2, event)
    )


def test_fingerprint_differs_by_metric():
    first = make_event(metric_type="blood_glucose")
    second = make_event(metric_type="heart_rate")

    assert (
        generate_event_fingerprint(1, first)
        != generate_event_fingerprint(1, second)
    )


def test_fingerprint_differs_by_unit():
    first = make_event(unit="mg/dL")
    second = make_event(unit="mmol/L")

    assert (
        generate_event_fingerprint(1, first)
        != generate_event_fingerprint(1, second)
    )


def test_fingerprint_differs_by_event_type():
    first = make_event("statistical_deviation")
    second = make_event("routine_monitoring")

    assert (
        generate_event_fingerprint(1, first)
        != generate_event_fingerprint(1, second)
    )


# ============================================================
# DEDUPLICATION TESTS
# ============================================================

def test_new_event_is_allowed():
    result = evaluate_event_deduplication(
        user_id=1,
        event=make_event(),
        previous_events=[],
        current_time=NOW,
    )

    assert result["notification_allowed"] is True
    assert result["deduplication_status"] == "new_event"


def test_duplicate_within_cooldown_is_suppressed():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    result = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[
            previous_record(1, fingerprint, 10)
        ],
        cooldown_minutes=60,
        current_time=NOW,
    )

    assert result["notification_allowed"] is False
    assert (
        result["deduplication_status"]
        == "duplicate_suppressed"
    )


def test_cooldown_expired_is_allowed():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    result = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[
            previous_record(1, fingerprint, 61)
        ],
        cooldown_minutes=60,
        current_time=NOW,
    )

    assert result["notification_allowed"] is True
    assert (
        result["deduplication_status"]
        == "cooldown_expired"
    )


def test_exact_cooldown_boundary_is_allowed():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    result = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[
            previous_record(1, fingerprint, 60)
        ],
        cooldown_minutes=60,
        current_time=NOW,
    )

    assert result["notification_allowed"] is True


def test_one_second_before_boundary_is_suppressed():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    result = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[
            {
                "user_id": 1,
                "fingerprint": fingerprint,
                "notified_at": (
                    NOW - timedelta(
                        minutes=60,
                        seconds=-1,
                    )
                ).isoformat(),
            }
        ],
        cooldown_minutes=60,
        current_time=NOW,
    )

    assert result["notification_allowed"] is False


def test_latest_matching_notification_is_used():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    result = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[
            previous_record(1, fingerprint, 120),
            previous_record(1, fingerprint, 10),
            previous_record(1, fingerprint, 90),
        ],
        cooldown_minutes=60,
        current_time=NOW,
    )

    assert result["notification_allowed"] is False

    assert result["last_notified_at"] == (
        NOW - timedelta(minutes=10)
    ).isoformat()


def test_different_event_type_is_independent():
    current_event = make_event(
        "statistical_deviation"
    )

    previous_event = make_event(
        "routine_monitoring"
    )

    previous_fingerprint = generate_event_fingerprint(
        1,
        previous_event,
    )

    result = evaluate_event_deduplication(
        user_id=1,
        event=current_event,
        previous_events=[
            previous_record(
                1,
                previous_fingerprint,
                5,
            )
        ],
        current_time=NOW,
    )

    assert result["notification_allowed"] is True
    assert result["deduplication_status"] == "new_event"


def test_custom_cooldown():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    result = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[
            previous_record(1, fingerprint, 30)
        ],
        cooldown_minutes=20,
        current_time=NOW,
    )

    assert result["notification_allowed"] is True


def test_next_allowed_timestamp():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    result = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[
            previous_record(1, fingerprint, 10)
        ],
        cooldown_minutes=60,
        current_time=NOW,
    )

    expected = (
        NOW + timedelta(minutes=50)
    ).isoformat()

    assert result["next_allowed_at"] == expected


def test_previous_events_not_modified():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    records = [
        previous_record(1, fingerprint, 10)
    ]

    original = deepcopy(records)

    evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=records,
        current_time=NOW,
    )

    assert records == original


def test_event_not_modified():
    event = make_event()
    original = deepcopy(event)

    evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[],
        current_time=NOW,
    )

    assert event == original


# ============================================================
# VALIDATION TESTS
# ============================================================

@pytest.mark.parametrize(
    "user_id",
    [0, -1, True, 1.5, "1", None],
)
def test_invalid_user_id(user_id):
    with pytest.raises(MonitoringEventDeduplicationError):
        generate_event_fingerprint(
            user_id,
            make_event(),
        )


@pytest.mark.parametrize(
    "cooldown",
    [0, -1, 10081, True, 1.5, "60", None],
)
def test_invalid_cooldown(cooldown):
    with pytest.raises(MonitoringEventDeduplicationError):
        evaluate_event_deduplication(
            user_id=1,
            event=make_event(),
            previous_events=[],
            cooldown_minutes=cooldown,
            current_time=NOW,
        )


def test_invalid_event_type():
    event = make_event()
    event["event_type"] = "emergency"

    with pytest.raises(MonitoringEventDeduplicationError):
        generate_event_fingerprint(1, event)


def test_incomplete_classification():
    event = make_event()
    event["classification_status"] = "failed"

    with pytest.raises(MonitoringEventDeduplicationError):
        generate_event_fingerprint(1, event)


def test_event_level_mismatch():
    event = make_event()
    event["event_level"] = "critical"

    with pytest.raises(MonitoringEventDeduplicationError):
        generate_event_fingerprint(1, event)


def test_priority_mismatch():
    event = make_event()
    event["monitoring_priority"] = "routine_tracking"

    with pytest.raises(MonitoringEventDeduplicationError):
        generate_event_fingerprint(1, event)


def test_invalid_previous_event_structure():
    with pytest.raises(MonitoringEventDeduplicationError):
        evaluate_event_deduplication(
            user_id=1,
            event=make_event(),
            previous_events="invalid",
            current_time=NOW,
        )


def test_cross_user_previous_event_rejected():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    with pytest.raises(MonitoringEventDeduplicationError):
        evaluate_event_deduplication(
            user_id=1,
            event=event,
            previous_events=[
                previous_record(2, fingerprint, 10)
            ],
            current_time=NOW,
        )


def test_invalid_previous_fingerprint():
    with pytest.raises(MonitoringEventDeduplicationError):
        evaluate_event_deduplication(
            user_id=1,
            event=make_event(),
            previous_events=[
                {
                    "user_id": 1,
                    "fingerprint": "invalid",
                    "notified_at": NOW.isoformat(),
                }
            ],
            current_time=NOW,
        )


def test_future_notification_timestamp_rejected():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    with pytest.raises(MonitoringEventDeduplicationError):
        evaluate_event_deduplication(
            user_id=1,
            event=event,
            previous_events=[
                {
                    "user_id": 1,
                    "fingerprint": fingerprint,
                    "notified_at": (
                        NOW + timedelta(minutes=5)
                    ).isoformat(),
                }
            ],
            current_time=NOW,
        )


def test_naive_current_time_rejected():
    with pytest.raises(MonitoringEventDeduplicationError):
        evaluate_event_deduplication(
            user_id=1,
            event=make_event(),
            previous_events=[],
            current_time=datetime(2026, 11, 10, 12, 0),
        )


def test_naive_previous_timestamp_rejected():
    event = make_event()
    fingerprint = generate_event_fingerprint(1, event)

    with pytest.raises(MonitoringEventDeduplicationError):
        evaluate_event_deduplication(
            user_id=1,
            event=event,
            previous_events=[
                {
                    "user_id": 1,
                    "fingerprint": fingerprint,
                    "notified_at": "2026-11-10T11:00:00",
                }
            ],
            current_time=NOW,
        )


def test_utc_timestamp_with_z_suffix():
    result = evaluate_event_deduplication(
        user_id=1,
        event=make_event(),
        previous_events=[],
        current_time="2026-11-10T12:00:00Z",
    )

    assert result["notification_allowed"] is True
    assert result["evaluated_at"] == NOW.isoformat()


def test_deterministic_results_with_fixed_time():
    event = make_event()

    first = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[],
        current_time=NOW,
    )

    second = evaluate_event_deduplication(
        user_id=1,
        event=event,
        previous_events=[],
        current_time=NOW,
    )

    assert first == second