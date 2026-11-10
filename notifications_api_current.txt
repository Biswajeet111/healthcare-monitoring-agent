from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthguard.core.dependencies import get_current_user
from healthguard.database.models import MonitoringEvent, UserProfile
from healthguard.database.session import get_db


router = APIRouter(
    prefix="/users/{user_id}/notifications",
    tags=["Notifications"],
)


def verify_notification_access(
    user_id: int,
    current_user: UserProfile,
) -> None:
    """Ensure users can access only their own notifications."""

    if user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access this user's notifications",
        )


def serialize_notification(event: MonitoringEvent) -> dict:
    """Convert a monitoring event into an in-app notification."""

    return {
        "id": event.id,
        "user_id": event.user_id,
        "metric_type": event.metric_type,
        "unit": event.unit,
        "event_type": event.event_type,
        "event_level": event.event_level,
        "monitoring_priority": event.monitoring_priority,
        "message": event.message,
        "notification_status": event.notification_status,
        "is_acknowledged": event.is_acknowledged,
        "created_at": event.created_at,
        "notified_at": event.notified_at,
        "acknowledged_at": event.acknowledged_at,
        "disclaimer": (
            "This notification represents a statistical monitoring "
            "observation and does not establish a medical diagnosis "
            "or clinical urgency."
        ),
    }


def delivered_notifications_query(user_id: int):
    """Return the base query for published notifications."""

    return select(MonitoringEvent).where(
        MonitoringEvent.user_id == user_id,
        MonitoringEvent.notification_status == "delivered",
        MonitoringEvent.notified_at.is_not(None),
        MonitoringEvent.event_type.in_(
            [
                "statistical_deviation",
                "insufficient_baseline_variability",
            ]
        ),
    )


@router.get("")
def list_notifications(
    user_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve published in-app notifications.

    Reading notifications does not acknowledge them.
    """

    verify_notification_access(user_id, current_user)

    base_query = delivered_notifications_query(user_id)

    if unread_only:
        base_query = base_query.where(
            MonitoringEvent.is_acknowledged.is_(False)
        )

    count_query = select(func.count()).select_from(
        base_query.subquery()
    )

    total = db.scalar(count_query) or 0

    events = db.scalars(
        base_query.order_by(
            MonitoringEvent.notified_at.desc(),
            MonitoringEvent.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "user_id": user_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "unread_only": unread_only,
        "notifications": [
            serialize_notification(event)
            for event in events
        ],
    }


@router.get("/summary")
def get_notification_summary(
    user_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return notification counts for the authenticated user."""

    verify_notification_access(user_id, current_user)

    base_query = delivered_notifications_query(user_id)

    total = db.scalar(
        select(func.count()).select_from(
            base_query.subquery()
        )
    ) or 0

    unread_query = base_query.where(
        MonitoringEvent.is_acknowledged.is_(False)
    )

    unread = db.scalar(
        select(func.count()).select_from(
            unread_query.subquery()
        )
    ) or 0

    return {
        "user_id": user_id,
        "total_notifications": total,
        "unread": unread,
        "acknowledged": total - unread,
    }