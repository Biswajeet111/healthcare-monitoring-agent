"""
Medication Adherence Service — Phase 6

Calculates adherence metrics from actual MedicationDoseOccurrence records.

Adherence formula:
  adherence_percentage = taken / (taken + missed + overdue) * 100

Where:
  - taken: user-confirmed "taken" occurrences in the window
  - missed: occurrences the user marked as "missed" (explicitly)
  - overdue: past-due occurrences not yet confirmed (treated as potentially missed
    but NOT counted as confirmed non-adherence in the percentage)

Future upcoming doses are excluded from all calculations.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from healthguard.database.models import (
    Medication,
    MedicationDoseOccurrence,
)

logger = logging.getLogger(__name__)


def _get_occurrences_in_window(
    db: Session,
    medication_id: int,
    start: datetime,
    end: datetime,
) -> list[MedicationDoseOccurrence]:
    """Return all dose occurrences in [start, end) for a medication."""
    return (
        db.query(MedicationDoseOccurrence)
        .filter(
            MedicationDoseOccurrence.medication_id == medication_id,
            MedicationDoseOccurrence.scheduled_at >= start,
            MedicationDoseOccurrence.scheduled_at < end,
        )
        .order_by(MedicationDoseOccurrence.scheduled_at.asc())
        .all()
    )


def _compute_adherence(occurrences: list[MedicationDoseOccurrence], now: datetime) -> dict:
    """
    Compute adherence statistics from a list of occurrences.

    Only past occurrences (scheduled_at < now) contribute to the
    adherence percentage denominator.
    """
    taken = 0
    missed = 0
    skipped = 0
    overdue = 0
    upcoming = 0

    for occ in occurrences:
        if occ.status == "taken":
            taken += 1
        elif occ.status == "missed":
            missed += 1
        elif occ.status == "skipped":
            skipped += 1
        elif occ.status in ("overdue", "due"):
            overdue += 1
        elif occ.status == "upcoming":
            upcoming += 1

    # Denominator: doses that were scheduled in the past and can be evaluated
    past_total = taken + missed + overdue  # skipped deliberately excluded from %
    adherence_pct = round((taken / past_total) * 100, 2) if past_total > 0 else None

    return {
        "total_occurrences": len(occurrences),
        "taken": taken,
        "missed": missed,
        "skipped": skipped,
        "overdue_unconfirmed": overdue,
        "upcoming": upcoming,
        "evaluable_past_doses": past_total,
        "adherence_percentage": adherence_pct,
        "note": (
            "Adherence = taken ÷ (taken + missed + overdue). "
            "Overdue doses are unconfirmed — the user may have taken them "
            "without logging. Skipped and upcoming doses are not in the denominator."
        ),
    }


def get_medication_adherence_summary(
    db: Session,
    medication: Medication,
    now_utc: Optional[datetime] = None,
) -> dict:
    """
    Returns overall, daily, weekly, and monthly adherence for a medication.
    """
    if now_utc is None:
        now_utc = datetime.utcnow()

    # Overall: from medication start_date
    overall_start = medication.start_date
    overall_end = medication.end_date or now_utc

    # Clamp to now
    effective_end = min(overall_end, now_utc)

    overall_occs = _get_occurrences_in_window(
        db, medication.id, overall_start, effective_end + timedelta(seconds=1)
    )

    # Last 7 days
    week_start = now_utc - timedelta(days=7)
    week_occs = [o for o in overall_occs if o.scheduled_at >= week_start]

    # Last 30 days
    month_start = now_utc - timedelta(days=30)
    month_occs = [o for o in overall_occs if o.scheduled_at >= month_start]

    # Today
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_occs = [o for o in overall_occs if o.scheduled_at >= today_start]

    return {
        "medication_id": medication.id,
        "medication_name": medication.name,
        "overall": _compute_adherence(overall_occs, now_utc),
        "last_7_days": _compute_adherence(week_occs, now_utc),
        "last_30_days": _compute_adherence(month_occs, now_utc),
        "today": _compute_adherence(today_occs, now_utc),
        "schedule_based": True,
        "disclaimer": (
            "Adherence is calculated from scheduled dose occurrences. "
            "Overdue doses are not confirmed missed — the user may not have logged them. "
            "This does not constitute a clinical adherence assessment."
        ),
    }


def get_medication_timeline(
    db: Session,
    medication: Medication,
    days_back: int = 7,
    days_ahead: int = 1,
    now_utc: Optional[datetime] = None,
) -> list[dict]:
    """
    Returns a chronological timeline of dose occurrences.
    """
    if now_utc is None:
        now_utc = datetime.utcnow()

    start = now_utc - timedelta(days=days_back)
    end = now_utc + timedelta(days=days_ahead)

    occurrences = _get_occurrences_in_window(db, medication.id, start, end)

    timeline = []
    for occ in occurrences:
        entry = {
            "occurrence_id": occ.id,
            "medication_id": medication.id,
            "medication_name": medication.name,
            "scheduled_at": occ.scheduled_at.isoformat(),
            "status": occ.status,
            "taken_at": occ.taken_at.isoformat() if occ.taken_at else None,
            "notes": occ.notes,
        }
        timeline.append(entry)

    return timeline
