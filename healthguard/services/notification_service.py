from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import MonitoringEvent
from healthguard.database.monitoring_event_repository import (
    mark_notification_delivered,
)


class NotificationServiceError(ValueError):
    """Raised when notification processing cannot be completed."""


NOTIFIABLE_EVENT_TYPES = {
    "statistical_deviation",
    "insufficient_baseline_variability",
}


def _validate_positive_id(value: Any, field_name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise NotificationServiceError(
            f"{field_name} must be a positive integer."
        )

    return value


def process_in_app_notification(
    db: Session,
    user_id: int,
    event_id: int,
) -> dict[str, Any]:
    """
    Process one existing monitoring event for in-app delivery.

    Does not commit the transaction.

    The caller controls commit/rollback.

    Delivery means the notification is made available through
    the application's persistent authenticated notification feed.

    It does not mean the user has read or acknowledged it.
    """

    user_id = _validate_positive_id(user_id, "user_id")
    event_id = _validate_positive_id(event_id, "event_id")

    monitoring_event = db.scalar(
        select(MonitoringEvent).where(
            MonitoringEvent.id == event_id,
            MonitoringEvent.user_id == user_id,
        )
    )

    if monitoring_event is None:
        raise NotificationServiceError(
            "Monitoring event not found for this user."
        )

    current_status = monitoring_event.notification_status

    if current_status == "delivered":
        return {
            "status": "already_delivered",
            "event_id": event_id,
            "notification_status": current_status,
        }

    if current_status == "suppressed":
        return {
            "status": "suppressed",
            "event_id": event_id,
            "notification_status": current_status,
        }

    if current_status == "failed":
        return {
            "status": "retry_required",
            "event_id": event_id,
            "notification_status": current_status,
        }

    if current_status != "pending":
        raise NotificationServiceError(
            "Unsupported notification status."
        )

    if monitoring_event.is_acknowledged:
        return {
            "status": "already_acknowledged",
            "event_id": event_id,
            "notification_status": current_status,
        }

    if monitoring_event.event_type not in NOTIFIABLE_EVENT_TYPES:
        monitoring_event.notification_status = "suppressed"
        db.flush()

        return {
            "status": "suppressed_by_policy",
            "event_id": event_id,
            "notification_status": "suppressed",
        }

    mark_notification_delivered(
        db=db,
        event_id=event_id,
        user_id=user_id,
        delivered_at=datetime.now(timezone.utc),
    )

    return {
        "status": "delivered",
        "event_id": event_id,
        "notification_status": "delivered",
    }