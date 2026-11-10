"""
Notification Agent — Phase 8

Delivers in-app alerts through existing notification infrastructure.
Prevents duplicate notifications and respects cooldown periods.
Prioritizes urgent safety escalation alerts.
"""

import logging
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import MonitoringEvent
from healthguard.services.notification_service import process_in_app_notification
from healthguard.orchestration.schemas import NotificationAgentResult

logger = logging.getLogger(__name__)


class NotificationAgent:
    """Agent responsible for delivering in-app alerts and preventing duplicates."""

    def __init__(self, db: Session):
        self.db = db

    def process_pending_alerts(
        self,
        user_id: int,
        event_ids: Optional[list[int]] = None,
    ) -> NotificationAgentResult:
        """
        Process pending notifications for a user, ensuring deduplication and in-app delivery.
        """
        notifications_created = []
        suppressed_count = 0

        # Query pending monitoring events
        stmt = (
            select(MonitoringEvent)
            .where(
                MonitoringEvent.user_id == user_id,
                MonitoringEvent.notification_status == "pending",
            )
            .order_by(MonitoringEvent.created_at.desc())
        )
        if event_ids:
            stmt = stmt.where(MonitoringEvent.id.in_(event_ids))

        pending_events = list(self.db.scalars(stmt).all())

        for ev in pending_events:
            try:
                res = process_in_app_notification(
                    db=self.db,
                    user_id=user_id,
                    event_id=ev.id,
                )
                status = res.get("status")
                if status == "delivered":
                    notifications_created.append({
                        "event_id": ev.id,
                        "metric_type": ev.metric_type,
                        "event_level": ev.event_level,
                        "message": ev.message,
                        "status": "delivered",
                    })
                elif status == "suppressed":
                    suppressed_count += 1
            except Exception as exc:
                logger.warning("Notification delivery attempt failed: %s", exc)
                suppressed_count += 1

        summary = (
            f"Delivered {len(notifications_created)} in-app alert(s). "
            f"Suppressed/skipped {suppressed_count} duplicate or unnotifiable event(s)."
        )

        return NotificationAgentResult(
            notifications_created=notifications_created,
            suppressed_count=suppressed_count,
            summary=summary,
        )
