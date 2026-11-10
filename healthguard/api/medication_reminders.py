"""
Medication Reminders API — Phase 6

Endpoints for managing in-app medication reminders.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from healthguard.core.dependencies import get_current_user
from healthguard.database.models import MedicationReminder, UserProfile
from healthguard.database.session import get_db
from healthguard.services.medication_reminder_service import (
    acknowledge_reminder,
    generate_reminders_for_user,
    get_pending_reminders,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reminders", tags=["Medication Reminders"])


@router.get("/medications")
def get_medication_reminders(
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None, pattern="^(pending|acknowledged|dismissed)$"),
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get medication reminders for the authenticated user.

    Optionally filter by status. Triggers reminder generation for new due doses.
    """
    # Generate any new due reminders
    try:
        new_reminders = generate_reminders_for_user(db, current_user.id)
        if new_reminders:
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Reminder generation failed for user %s", current_user.id)

    query = db.query(MedicationReminder).filter(
        MedicationReminder.user_id == current_user.id
    )
    if status:
        query = query.filter(MedicationReminder.status == status)

    reminders = query.order_by(MedicationReminder.created_at.desc()).limit(limit).all()

    return {
        "user_id": current_user.id,
        "reminders": [
            {
                "id": r.id,
                "medication_id": r.medication_id,
                "occurrence_id": r.occurrence_id,
                "message": r.message,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
            }
            for r in reminders
        ],
        "total": len(reminders),
        "limitation": (
            "In-app reminders are only generated while the backend is running. "
            "If the server was stopped, reminders for that period were not delivered."
        ),
    }


@router.get("/medications/summary")
def get_reminder_summary(
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a count summary of pending and acknowledged reminders."""
    pending_count = (
        db.query(MedicationReminder)
        .filter(
            MedicationReminder.user_id == current_user.id,
            MedicationReminder.status == "pending",
        )
        .count()
    )
    acknowledged_count = (
        db.query(MedicationReminder)
        .filter(
            MedicationReminder.user_id == current_user.id,
            MedicationReminder.status == "acknowledged",
        )
        .count()
    )

    return {
        "user_id": current_user.id,
        "pending": pending_count,
        "acknowledged": acknowledged_count,
        "total": pending_count + acknowledged_count,
    }


@router.patch("/medications/{reminder_id}/acknowledge")
def acknowledge_medication_reminder(
    reminder_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Acknowledge a medication reminder. Enforces ownership."""
    reminder = acknowledge_reminder(db, reminder_id, current_user.id)

    if not reminder:
        raise HTTPException(
            status_code=404,
            detail="Reminder not found or access denied",
        )

    db.commit()
    return {
        "reminder_id": reminder.id,
        "status": reminder.status,
        "acknowledged_at": reminder.acknowledged_at.isoformat() if reminder.acknowledged_at else None,
    }
