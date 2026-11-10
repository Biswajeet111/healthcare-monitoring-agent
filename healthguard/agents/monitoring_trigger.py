from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import (
    HealthMetric,
    MonitoringEvent,
    UserProfile,
)

from healthguard.agents.monitoring_orchestrator import (
    run_monitoring_pipeline,
)

from healthguard.agents.monitoring_event_classifier import (
    classify_monitoring_event,
)

from healthguard.agents.monitoring_event_deduplicator import (
    evaluate_event_deduplication,
    generate_event_fingerprint,
)

from healthguard.database.monitoring_event_repository import (
    create_monitoring_event,
    get_notification_history,
)


class MonitoringTriggerError(ValueError):
    """Raised when automated monitoring cannot be completed."""


DEFAULT_BASELINE_WINDOW = 5
DEFAULT_RECENT_WINDOW = 3
DEFAULT_ANOMALY_THRESHOLD = 2.0
DEFAULT_COOLDOWN_MINUTES = 60


def _validate_user_id(user_id: Any) -> int:
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise MonitoringTriggerError(
            "user_id must be a positive integer."
        )

    return user_id


def _validate_metric_id(metric_id: Any) -> int:
    if (
        isinstance(metric_id, bool)
        or not isinstance(metric_id, int)
        or metric_id <= 0
    ):
        raise MonitoringTriggerError(
            "metric_id must be a positive integer."
        )

    return metric_id


def _as_utc_iso(value: datetime) -> str:
    """
    Existing project timestamps are stored as naive UTC.
    """

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        ).isoformat()

    return value.astimezone(timezone.utc).isoformat()


def _get_recent_readings(
    db: Session,
    user_id: int,
    metric_type: str,
    unit: str,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Fetch the most recent measurements for one user,
    metric type, and unit.

    Return readings in chronological order.
    """

    statement = (
        select(HealthMetric)
        .where(
            HealthMetric.user_id == user_id,
            HealthMetric.metric_type == metric_type,
            HealthMetric.unit == unit,
        )
        .order_by(
            HealthMetric.recorded_at.desc(),
            HealthMetric.id.desc(),
        )
        .limit(limit)
    )

    records = list(db.scalars(statement).all())

    records.reverse()

    return [
        {
            "id": record.id,
            "value": record.value,
            "recorded_at": _as_utc_iso(
                record.recorded_at
            ),
        }
        for record in records
    ]


def _pending_event_exists(
    db: Session,
    user_id: int,
    fingerprint: str,
) -> bool:
    """
    Prevent repeated pending events for the same
    monitoring condition.
    """

    statement = (
        select(MonitoringEvent.id)
        .where(
            MonitoringEvent.user_id == user_id,
            MonitoringEvent.fingerprint == fingerprint,
            MonitoringEvent.notification_status == "pending",
        )
        .limit(1)
    )

    return db.scalar(statement) is not None


def trigger_monitoring_for_metric(
    db: Session,
    user_id: int,
    metric_id: int,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
    recent_window: int = DEFAULT_RECENT_WINDOW,
    anomaly_threshold: float = DEFAULT_ANOMALY_THRESHOLD,
    cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
) -> dict[str, Any]:
    """
    Run monitoring after a health metric has been saved.

    The caller must commit the health measurement before
    invoking this function.

    This function may create a monitoring event but does
    not commit the transaction.

    The caller controls commit and rollback.
    """

    user_id = _validate_user_id(user_id)
    metric_id = _validate_metric_id(metric_id)

    user = db.get(UserProfile, user_id)

    if user is None:
        raise MonitoringTriggerError(
            "User does not exist."
        )

    metric = db.scalar(
        select(HealthMetric).where(
            HealthMetric.id == metric_id,
            HealthMetric.user_id == user_id,
        )
    )

    if metric is None:
        raise MonitoringTriggerError(
            "Health metric not found for this user."
        )

    required_readings = baseline_window + recent_window

    readings = _get_recent_readings(
        db=db,
        user_id=user_id,
        metric_type=metric.metric_type,
        unit=metric.unit,
        limit=required_readings,
    )

    if len(readings) < required_readings:
        return {
            "trigger_status": "skipped",
            "reason": "insufficient_readings",
            "user_id": user_id,
            "metric_id": metric_id,
            "available_readings": len(readings),
            "required_readings": required_readings,
            "event_id": None,
        }

    report = run_monitoring_pipeline(
        metric_type=metric.metric_type,
        unit=metric.unit,
        readings=readings,
        baseline_window=baseline_window,
        recent_window=recent_window,
        anomaly_threshold=anomaly_threshold,
    )

    classified_event = classify_monitoring_event(report)

    fingerprint = generate_event_fingerprint(
        user_id,
        classified_event,
    )

    if _pending_event_exists(
        db,
        user_id,
        fingerprint,
    ):
        return {
            "trigger_status": "suppressed",
            "reason": "pending_event_exists",
            "user_id": user_id,
            "metric_id": metric_id,
            "fingerprint": fingerprint,
            "event_id": None,
        }

    history = get_notification_history(
        db,
        user_id,
        fingerprint,
    )

    decision = evaluate_event_deduplication(
        user_id=user_id,
        event=classified_event,
        previous_events=history,
        cooldown_minutes=cooldown_minutes,
        current_time=datetime.now(timezone.utc),
    )

    notification_status = (
        "pending"
        if decision["notification_allowed"]
        else "suppressed"
    )

    stored_event = create_monitoring_event(
        db=db,
        user_id=user_id,
        classified_event=classified_event,
        notification_status=notification_status,
    )

    return {
        "trigger_status": (
            "event_created"
            if notification_status == "pending"
            else "suppressed"
        ),
        "reason": decision["deduplication_status"],
        "user_id": user_id,
        "metric_id": metric_id,
        "event_id": stored_event.id,
        "fingerprint": fingerprint,
        "event_type": stored_event.event_type,
        "event_level": stored_event.event_level,
        "notification_status": notification_status,
    }