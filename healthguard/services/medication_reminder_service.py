"""
Medication Reminder Service — Phase 6

Generates in-app reminders for due and overdue dose occurrences.

Design:
- One reminder per occurrence (enforced by unique constraint).
- Reminders are idempotent: re-running the worker never creates duplicates.
- Reminders are user-specific.
- Reminders are transactionally safe.

Worker lifecycle:
- The reminder worker is started as a background thread when FastAPI starts.
- It runs process_reminders_for_all_users() every REMINDER_INTERVAL_SECONDS.
- If the backend is stopped, reminders cannot be delivered in real-time.
  Users will see pending reminders when the backend restarts.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from healthguard.database.models import (
    Medication,
    MedicationDoseOccurrence,
    MedicationReminder,
    UserProfile,
)
from healthguard.database.session import SessionLocal
from healthguard.services.medication_scheduler import refresh_occurrence_statuses

logger = logging.getLogger(__name__)

# How often the reminder worker runs
REMINDER_INTERVAL_SECONDS = 120  # 2 minutes

# How far ahead to look for upcoming doses to remind about
REMINDER_AHEAD_MINUTES = 30


def generate_reminders_for_user(
    db: Session,
    user_id: int,
    now_utc: Optional[datetime] = None,
) -> list[MedicationReminder]:
    """
    Generate reminder records for due and overdue occurrences for a user.

    Idempotent — skips occurrences that already have a reminder.

    Returns newly created reminders.
    """
    if now_utc is None:
        now_utc = datetime.utcnow()

    # First refresh occurrence statuses
    refresh_occurrence_statuses(db, user_id, now_utc)

    # Find eligible occurrences: due or overdue, belonging to active medications
    active_medication_ids = [
        row[0]
        for row in db.query(Medication.id)
        .filter(
            Medication.user_id == user_id,
            Medication.is_active.is_(True),
        )
        .all()
    ]

    if not active_medication_ids:
        return []

    eligible_occurrences = (
        db.query(MedicationDoseOccurrence)
        .filter(
            MedicationDoseOccurrence.medication_id.in_(active_medication_ids),
            MedicationDoseOccurrence.status.in_(["due", "overdue"]),
        )
        .all()
    )

    new_reminders = []
    for occ in eligible_occurrences:
        # Check if reminder already exists for this occurrence
        existing = (
            db.query(MedicationReminder)
            .filter(MedicationReminder.occurrence_id == occ.id)
            .first()
        )
        if existing:
            continue

        medication = (
            db.query(Medication).filter(Medication.id == occ.medication_id).first()
        )
        if not medication:
            continue

        status_label = "is due now" if occ.status == "due" else "is overdue"
        message = (
            f"Reminder: {medication.name} ({medication.dosage}) {status_label}. "
            f"Scheduled at {occ.scheduled_at.strftime('%H:%M UTC')}."
        )

        reminder = MedicationReminder(
            user_id=user_id,
            occurrence_id=occ.id,
            medication_id=occ.medication_id,
            message=message,
            status="pending",
            created_at=now_utc,
        )
        db.add(reminder)
        new_reminders.append(reminder)

    if new_reminders:
        try:
            db.flush()
            logger.info(
                "Generated %d reminder(s) for user %s",
                len(new_reminders),
                user_id,
            )
        except IntegrityError:
            db.rollback()
            logger.warning(
                "Some reminders for user %s already existed (race condition), rolled back.",
                user_id,
            )
            return []

    return new_reminders


def get_pending_reminders(
    db: Session,
    user_id: int,
    limit: int = 50,
) -> list[MedicationReminder]:
    """Return pending reminders for a user, newest first."""
    return (
        db.query(MedicationReminder)
        .filter(
            MedicationReminder.user_id == user_id,
            MedicationReminder.status == "pending",
        )
        .order_by(MedicationReminder.created_at.desc())
        .limit(limit)
        .all()
    )


def acknowledge_reminder(
    db: Session,
    reminder_id: int,
    user_id: int,
) -> Optional[MedicationReminder]:
    """
    Acknowledge a reminder. Returns the updated reminder or None if not found.
    Enforces ownership.
    """
    reminder = (
        db.query(MedicationReminder)
        .filter(
            MedicationReminder.id == reminder_id,
            MedicationReminder.user_id == user_id,
        )
        .first()
    )

    if not reminder:
        return None

    reminder.status = "acknowledged"
    reminder.acknowledged_at = datetime.utcnow()
    db.flush()
    return reminder


def process_reminders_for_all_users(db: Session) -> None:
    """
    Process medication reminders for all users with active medications.
    Called by the background worker.
    """
    users_with_medications = (
        db.query(UserProfile.id)
        .join(Medication, Medication.user_id == UserProfile.id)
        .filter(Medication.is_active.is_(True))
        .distinct()
        .all()
    )

    for (user_id,) in users_with_medications:
        try:
            generate_reminders_for_user(db, user_id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Reminder processing failed for user %s", user_id)


# ============================================================
# BACKGROUND WORKER
# ============================================================

_worker_thread: Optional[threading.Thread] = None
_worker_running = False


def _reminder_worker_loop() -> None:
    """Background thread that periodically processes reminders."""
    global _worker_running
    logger.info(
        "Medication reminder worker started. Interval: %ds",
        REMINDER_INTERVAL_SECONDS,
    )
    while _worker_running:
        try:
            db: Session = SessionLocal()
            try:
                process_reminders_for_all_users(db)
            finally:
                db.close()
        except Exception:
            logger.exception("Reminder worker iteration failed")

        for _ in range(REMINDER_INTERVAL_SECONDS):
            if not _worker_running:
                break
            time.sleep(1)

    logger.info("Medication reminder worker stopped.")


def start_reminder_worker() -> None:
    """Start the background reminder worker thread. Called once at app startup."""
    global _worker_thread, _worker_running

    if _worker_thread is not None and _worker_thread.is_alive():
        logger.info("Reminder worker already running.")
        return

    _worker_running = True
    _worker_thread = threading.Thread(
        target=_reminder_worker_loop,
        daemon=True,
        name="medication-reminder-worker",
    )
    _worker_thread.start()
    logger.info("Medication reminder worker thread started.")


def stop_reminder_worker() -> None:
    """Signal the background reminder worker to stop."""
    global _worker_running
    _worker_running = False
    logger.info("Medication reminder worker stop requested.")
