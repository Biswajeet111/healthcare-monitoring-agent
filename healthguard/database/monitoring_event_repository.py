import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import MonitoringEvent, UserProfile
from healthguard.agents.monitoring_event_deduplicator import (
    generate_event_fingerprint,
    MonitoringEventDeduplicationError,
)


class MonitoringEventRepositoryError(ValueError):
    """Raised when monitoring event persistence fails validation."""


def _validate_user_id(user_id: Any) -> int:
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise MonitoringEventRepositoryError(
            "user_id must be a positive integer."
        )

    return user_id


def _utc_naive(value: datetime) -> datetime:
    """
    Convert aware timestamps to naive UTC for compatibility
    with the project's existing SQLite DateTime columns.
    """

    if not isinstance(value, datetime):
        raise MonitoringEventRepositoryError(
            "Expected datetime value."
        )

    if value.tzinfo is None or value.utcoffset() is None:
        raise MonitoringEventRepositoryError(
            "Datetime must be timezone-aware."
        )

    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None

    return value.replace(
        tzinfo=timezone.utc
    ).isoformat()


def create_monitoring_event(
    db: Session,
    user_id: int,
    classified_event: dict[str, Any],
    notification_status: str = "pending",
) -> MonitoringEvent:
    """
    Persist a trusted, classified monitoring event.

    Does not commit the transaction.

    The caller controls commit/rollback.
    """

    user_id = _validate_user_id(user_id)

    if not isinstance(classified_event, dict):
        raise MonitoringEventRepositoryError(
            "classified_event must be a dictionary."
        )

    if notification_status not in {
        "pending",
        "suppressed",
    }:
        raise MonitoringEventRepositoryError(
            "New events must begin as pending or suppressed."
        )

    user = db.get(UserProfile, user_id)

    if user is None:
        raise MonitoringEventRepositoryError(
            "User does not exist."
        )

    try:
        fingerprint = generate_event_fingerprint(
            user_id,
            classified_event,
        )
    except MonitoringEventDeduplicationError as exc:
        raise MonitoringEventRepositoryError(
            str(exc)
        ) from exc

    message = classified_event.get("message")

    if not isinstance(message, str) or not message.strip():
        raise MonitoringEventRepositoryError(
            "Event message is required."
        )

    evidence = classified_event.get("evidence")

    if evidence is not None:
        if not isinstance(evidence, dict):
            raise MonitoringEventRepositoryError(
                "Event evidence must be a dictionary."
            )

        try:
            evidence_json = json.dumps(
                evidence,
                allow_nan=False,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise MonitoringEventRepositoryError(
                "Event evidence is not valid JSON."
            ) from exc
    else:
        evidence_json = None

    event = MonitoringEvent(
        user_id=user_id,
        fingerprint=fingerprint,
        metric_type=classified_event["metric_type"],
        unit=classified_event["unit"],
        event_type=classified_event["event_type"],
        event_level=classified_event["event_level"],
        monitoring_priority=classified_event[
            "monitoring_priority"
        ],
        statistical_status=classified_event[
            "statistical_status"
        ],
        message=message.strip(),
        evidence_json=evidence_json,
        notification_status=notification_status,
        created_at=datetime.utcnow(),
    )

    db.add(event)
    db.flush()

    return event


def get_monitoring_events(
    db: Session,
    user_id: int,
    limit: int = 100,
) -> list[MonitoringEvent]:
    """
    Return monitoring events belonging to one user.
    """

    user_id = _validate_user_id(user_id)

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 500
    ):
        raise MonitoringEventRepositoryError(
            "limit must be between 1 and 500."
        )

    statement = (
        select(MonitoringEvent)
        .where(MonitoringEvent.user_id == user_id)
        .order_by(
            MonitoringEvent.created_at.desc(),
            MonitoringEvent.id.desc(),
        )
        .limit(limit)
    )

    return list(db.scalars(statement).all())


def get_notification_history(
    db: Session,
    user_id: int,
    fingerprint: str,
) -> list[dict[str, Any]]:
    """
    Return delivered notification history in the format
    expected by the Phase 3.3.2 deduplication engine.
    """

    user_id = _validate_user_id(user_id)

    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(
            char not in "0123456789abcdef"
            for char in fingerprint
        )
    ):
        raise MonitoringEventRepositoryError(
            "Invalid event fingerprint."
        )

    statement = (
        select(MonitoringEvent)
        .where(
            MonitoringEvent.user_id == user_id,
            MonitoringEvent.fingerprint == fingerprint,
            MonitoringEvent.notification_status == "delivered",
            MonitoringEvent.notified_at.is_not(None),
        )
        .order_by(
            MonitoringEvent.notified_at.desc(),
            MonitoringEvent.id.desc(),
        )
    )

    events = db.scalars(statement).all()

    return [
        {
            "user_id": event.user_id,
            "fingerprint": event.fingerprint,
            "notified_at": _as_utc_iso(event.notified_at),
        }
        for event in events
    ]


def mark_notification_delivered(
    db: Session,
    event_id: int,
    user_id: int,
    delivered_at: datetime | None = None,
) -> MonitoringEvent:
    """
    Mark a notification delivered after confirmed delivery.

    Does not send a notification or commit the transaction.
    """

    user_id = _validate_user_id(user_id)

    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
    ):
        raise MonitoringEventRepositoryError(
            "event_id must be a positive integer."
        )

    statement = select(MonitoringEvent).where(
        MonitoringEvent.id == event_id,
        MonitoringEvent.user_id == user_id,
    )

    event = db.scalar(statement)

    if event is None:
        raise MonitoringEventRepositoryError(
            "Monitoring event not found."
        )

    if event.notification_status != "pending":
        raise MonitoringEventRepositoryError(
            "Only pending notifications can be marked delivered."
        )

    if delivered_at is None:
        delivered_at = datetime.now(timezone.utc)

    event.notification_status = "delivered"
    event.notified_at = _utc_naive(delivered_at)

    db.flush()

    return event


def mark_notification_failed(
    db: Session,
    event_id: int,
    user_id: int,
) -> MonitoringEvent:
    """
    Mark a pending notification as failed.
    """

    user_id = _validate_user_id(user_id)

    statement = select(MonitoringEvent).where(
        MonitoringEvent.id == event_id,
        MonitoringEvent.user_id == user_id,
    )

    event = db.scalar(statement)

    if event is None:
        raise MonitoringEventRepositoryError(
            "Monitoring event not found."
        )

    if event.notification_status != "pending":
        raise MonitoringEventRepositoryError(
            "Only pending notifications can be marked failed."
        )

    event.notification_status = "failed"

    db.flush()

    return event