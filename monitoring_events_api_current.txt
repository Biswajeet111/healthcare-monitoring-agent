from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthguard.core.dependencies import get_current_user
from healthguard.database.models import MonitoringEvent, UserProfile
from healthguard.database.session import get_db


router = APIRouter(
    prefix="/users/{user_id}/monitoring/events",
    tags=["Monitoring Events"],
)


def verify_event_access(
    user_id: int,
    current_user: UserProfile,
) -> None:
    """Ensure users can access only their own monitoring events."""

    if user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access this user's monitoring events",
        )


def serialize_event(event: MonitoringEvent) -> dict:
    """Convert a monitoring event into a safe API response."""

    return {
        "id": event.id,
        "user_id": event.user_id,
        "metric_type": event.metric_type,
        "unit": event.unit,
        "event_type": event.event_type,
        "event_level": event.event_level,
        "monitoring_priority": event.monitoring_priority,
        "statistical_status": event.statistical_status,
        "message": event.message,
        "notification_status": event.notification_status,
        "is_acknowledged": event.is_acknowledged,
        "created_at": event.created_at,
        "notified_at": event.notified_at,
        "acknowledged_at": event.acknowledged_at,
        "disclaimer": (
            "Monitoring events represent statistical observations "
            "and do not establish medical diagnoses or clinical urgency."
        ),
    }


# ============================================================
# GET MONITORING EVENT HISTORY
# ============================================================

@router.get("")
def list_monitoring_events(
    user_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_event_access(user_id, current_user)

    statement = (
        select(MonitoringEvent)
        .where(MonitoringEvent.user_id == user_id)
        .order_by(
            MonitoringEvent.created_at.desc(),
            MonitoringEvent.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    events = db.scalars(statement).all()

    total = db.scalar(
        select(func.count(MonitoringEvent.id)).where(
            MonitoringEvent.user_id == user_id
        )
    )

    return {
        "user_id": user_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": [
            serialize_event(event)
            for event in events
        ],
    }


# ============================================================
# GET MONITORING EVENT SUMMARY
# ============================================================

@router.get("/summary")
def get_monitoring_event_summary(
    user_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_event_access(user_id, current_user)

    events = db.scalars(
        select(MonitoringEvent).where(
            MonitoringEvent.user_id == user_id
        )
    ).all()

    by_type = {}
    by_status = {}

    for event in events:
        by_type[event.event_type] = (
            by_type.get(event.event_type, 0) + 1
        )

        by_status[event.notification_status] = (
            by_status.get(event.notification_status, 0) + 1
        )

    return {
        "user_id": user_id,
        "total_events": len(events),
        "acknowledged": sum(
            bool(event.is_acknowledged)
            for event in events
        ),
        "unacknowledged": sum(
            not bool(event.is_acknowledged)
            for event in events
        ),
        "by_event_type": by_type,
        "by_notification_status": by_status,
    }


# ============================================================
# GET SINGLE MONITORING EVENT
# ============================================================

@router.get("/{event_id}")
def get_monitoring_event(
    user_id: int,
    event_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_event_access(user_id, current_user)

    event = db.scalar(
        select(MonitoringEvent).where(
            MonitoringEvent.id == event_id,
            MonitoringEvent.user_id == user_id,
        )
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Monitoring event not found",
        )

    return serialize_event(event)


# ============================================================
# ACKNOWLEDGE MONITORING EVENT
# ============================================================

@router.patch("/{event_id}/acknowledge")
def acknowledge_monitoring_event(
    user_id: int,
    event_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_event_access(user_id, current_user)

    event = db.scalar(
        select(MonitoringEvent).where(
            MonitoringEvent.id == event_id,
            MonitoringEvent.user_id == user_id,
        )
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Monitoring event not found",
        )

    if not event.is_acknowledged:
        event.is_acknowledged = True

        event.acknowledged_at = datetime.now(
            timezone.utc
        ).replace(tzinfo=None)

        db.commit()
        db.refresh(event)

    return {
        "message": "Monitoring event acknowledged",
        "event": serialize_event(event),
    }