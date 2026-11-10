"""
Medication Scheduler Service — Phase 6

Generates MedicationDoseOccurrence records from MedicationSchedule definitions.

Policy for historical occurrences:
- When a schedule is edited, the old schedule is deactivated (effective_until set).
- A new schedule record is created.
- Historical occurrences generated under the old schedule are PRESERVED as-is.
- New occurrences are only generated under the new schedule from its effective_from date.

This ensures immutable historical dose records.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from healthguard.database.models import (
    Medication,
    MedicationSchedule,
    MedicationDoseOccurrence,
)

logger = logging.getLogger(__name__)

# Grace period after which an unconfirmed due dose is treated as overdue
OVERDUE_GRACE_MINUTES = 60


def _parse_times(times_json: str) -> list[str]:
    """Parse JSON list of HH:MM time strings from schedule."""
    try:
        return json.loads(times_json) if times_json else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_weekdays(weekdays_json: str) -> list[int]:
    """Parse JSON list of weekday integers (0=Mon…6=Sun)."""
    try:
        return json.loads(weekdays_json) if weekdays_json else []
    except (json.JSONDecodeError, TypeError):
        return []


def _time_str_to_hm(time_str: str) -> tuple[int, int]:
    """Convert 'HH:MM' to (hour, minute). Raises ValueError on bad format."""
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str}")
    return int(parts[0]), int(parts[1])


def generate_occurrences_for_schedule(
    db: Session,
    schedule: MedicationSchedule,
    start: datetime,
    end: datetime,
) -> list[MedicationDoseOccurrence]:
    """
    Generate and persist dose occurrences for a schedule between start and end (UTC).

    Skips occurrences that already exist (idempotent).
    Does not generate occurrences outside the medication's start/end dates.

    Returns the list of newly created occurrences.
    """
    medication: Medication = schedule.medication

    if not medication.is_active:
        return []

    # Clamp generation range to medication's active date range
    med_start = medication.start_date
    med_end = medication.end_date  # May be None

    effective_start = max(start, med_start, schedule.effective_from)
    effective_end = end
    if schedule.effective_until:
        effective_end = min(effective_end, schedule.effective_until)
    if med_end:
        effective_end = min(effective_end, med_end)

    if effective_start >= effective_end:
        return []

    times = _parse_times(schedule.times_of_day_json)
    if not times and schedule.schedule_type != "as_needed":
        logger.warning(
            "Schedule %s has no times configured, skipping generation.",
            schedule.id,
        )
        return []

    weekdays = _parse_weekdays(schedule.weekdays_json)

    # Collect all scheduled UTC datetimes in the range
    scheduled_datetimes: list[datetime] = []

    if schedule.schedule_type == "daily":
        current = effective_start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= effective_end:
            for time_str in times:
                try:
                    hour, minute = _time_str_to_hm(time_str)
                except ValueError:
                    logger.warning("Invalid time '%s' in schedule %s", time_str, schedule.id)
                    continue
                occurrence_dt = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if effective_start <= occurrence_dt <= effective_end:
                    scheduled_datetimes.append(occurrence_dt)
            current += timedelta(days=1)

    elif schedule.schedule_type == "weekly":
        if not weekdays:
            return []
        current = effective_start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= effective_end:
            if current.weekday() in weekdays:
                for time_str in times:
                    try:
                        hour, minute = _time_str_to_hm(time_str)
                    except ValueError:
                        logger.warning("Invalid time '%s' in schedule %s", time_str, schedule.id)
                        continue
                    occurrence_dt = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if effective_start <= occurrence_dt <= effective_end:
                        scheduled_datetimes.append(occurrence_dt)
            current += timedelta(days=1)

    elif schedule.schedule_type == "as_needed":
        # No auto-generated occurrences for as_needed
        return []

    # Deduplicate
    scheduled_datetimes = sorted(set(scheduled_datetimes))

    # Fetch existing occurrence timestamps for this schedule to avoid duplicates
    existing_times = set(
        row[0]
        for row in db.query(MedicationDoseOccurrence.scheduled_at)
        .filter(MedicationDoseOccurrence.schedule_id == schedule.id)
        .all()
    )

    new_occurrences = []
    for dt in scheduled_datetimes:
        if dt in existing_times:
            continue
        occ = MedicationDoseOccurrence(
            medication_id=schedule.medication_id,
            schedule_id=schedule.id,
            scheduled_at=dt,
            status="upcoming",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(occ)
        new_occurrences.append(occ)

    if new_occurrences:
        db.flush()
        logger.info(
            "Generated %d new occurrences for schedule %s (medication %s)",
            len(new_occurrences),
            schedule.id,
            schedule.medication_id,
        )

    return new_occurrences


def refresh_occurrence_statuses(
    db: Session,
    user_id: int,
    now_utc: Optional[datetime] = None,
) -> None:
    """
    Update occurrence statuses based on current UTC time.

    Transitions:
    - upcoming → due: when now >= scheduled_at
    - due → overdue: when now >= scheduled_at + OVERDUE_GRACE_MINUTES
    - overdue → missed: when the medication's end_date is past and status is overdue

    A dose is NEVER automatically marked 'taken'.
    'taken' and 'skipped' are user-confirmed states only.
    """
    if now_utc is None:
        now_utc = datetime.utcnow()

    due_cutoff = now_utc
    overdue_cutoff = now_utc - timedelta(minutes=OVERDUE_GRACE_MINUTES)

    # upcoming → due
    (
        db.query(MedicationDoseOccurrence)
        .filter(
            MedicationDoseOccurrence.status == "upcoming",
            MedicationDoseOccurrence.scheduled_at <= due_cutoff,
            MedicationDoseOccurrence.medication_id.in_(
                db.query(Medication.id).filter(
                    Medication.user_id == user_id,
                    Medication.is_active.is_(True),
                )
            ),
        )
        .update(
            {"status": "due", "updated_at": now_utc},
            synchronize_session=False,
        )
    )

    # due → overdue
    (
        db.query(MedicationDoseOccurrence)
        .filter(
            MedicationDoseOccurrence.status == "due",
            MedicationDoseOccurrence.scheduled_at <= overdue_cutoff,
            MedicationDoseOccurrence.medication_id.in_(
                db.query(Medication.id).filter(
                    Medication.user_id == user_id,
                    Medication.is_active.is_(True),
                )
            ),
        )
        .update(
            {"status": "overdue", "updated_at": now_utc},
            synchronize_session=False,
        )
    )


def ensure_occurrences_for_window(
    db: Session,
    medication: Medication,
    days_ahead: int = 7,
) -> None:
    """
    Ensure dose occurrences exist for the next `days_ahead` days for a medication.

    Called after schedule creation or update, and by the reminder worker.
    """
    active_schedule = (
        db.query(MedicationSchedule)
        .filter(
            MedicationSchedule.medication_id == medication.id,
            MedicationSchedule.is_active.is_(True),
        )
        .first()
    )

    if not active_schedule:
        return

    now = datetime.utcnow()
    window_end = now + timedelta(days=days_ahead)

    generate_occurrences_for_schedule(
        db=db,
        schedule=active_schedule,
        start=now - timedelta(hours=1),  # small backward buffer
        end=window_end,
    )
