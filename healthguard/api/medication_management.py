"""
Medication Management API — Phase 6

Extends the existing medication infrastructure with:
- Full CRUD for medications
- Structured scheduling
- Dose occurrence management
- Adherence analytics (schedule-based)
- Medication timeline

All endpoints enforce JWT authentication and per-user ownership.
No duplicate endpoints with existing main.py functionality.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from healthguard.core.dependencies import get_current_user
from healthguard.database.models import (
    Medication,
    MedicationSchedule,
    MedicationDoseOccurrence,
    UserProfile,
)
from healthguard.database.session import get_db
from healthguard.services.medication_scheduler import (
    ensure_occurrences_for_window,
    refresh_occurrence_statuses,
    generate_occurrences_for_schedule,
)
from healthguard.services.medication_adherence import (
    get_medication_adherence_summary,
    get_medication_timeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/medications", tags=["Medication Management"])


# ------------------------------------------------------------------
# HELPER
# ------------------------------------------------------------------

def _get_owned_medication(
    medication_id: int,
    current_user: UserProfile,
    db: Session,
) -> Medication:
    med = db.query(Medication).filter(Medication.id == medication_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")
    if med.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return med


# ------------------------------------------------------------------
# SCHEMAS
# ------------------------------------------------------------------

class ScheduleCreate(BaseModel):
    schedule_type: str = Field(..., pattern="^(daily|weekly|as_needed)$")
    times: list[str] = Field(default_factory=list, description="List of 'HH:MM' strings")
    weekdays: list[int] = Field(
        default_factory=list,
        description="0=Monday … 6=Sunday; only for weekly schedule",
    )
    timezone: str = Field(default="UTC", max_length=60)


class MedicationUpdateRequest(BaseModel):
    name: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    instructions: Optional[str] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None


class DoseConfirmRequest(BaseModel):
    status: str = Field(..., pattern="^(taken|skipped|missed)$")
    taken_at: Optional[datetime] = None
    notes: Optional[str] = None


# ------------------------------------------------------------------
# MEDICATION DETAIL
# ------------------------------------------------------------------

@router.get("/{medication_id}")
def get_medication_detail(
    medication_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full details for a single medication."""
    med = _get_owned_medication(medication_id, current_user, db)

    active_schedule = (
        db.query(MedicationSchedule)
        .filter(
            MedicationSchedule.medication_id == med.id,
            MedicationSchedule.is_active.is_(True),
        )
        .first()
    )

    schedule_info = None
    if active_schedule:
        schedule_info = {
            "id": active_schedule.id,
            "schedule_type": active_schedule.schedule_type,
            "times": json.loads(active_schedule.times_of_day_json or "[]"),
            "weekdays": json.loads(active_schedule.weekdays_json or "[]"),
            "timezone": active_schedule.timezone,
            "effective_from": active_schedule.effective_from.isoformat(),
        }

    return {
        "id": med.id,
        "user_id": med.user_id,
        "name": med.name,
        "dosage": med.dosage,
        "frequency": med.frequency,
        "instructions": med.instructions,
        "start_date": med.start_date.isoformat(),
        "end_date": med.end_date.isoformat() if med.end_date else None,
        "is_active": med.is_active,
        "created_at": med.created_at.isoformat(),
        "schedule": schedule_info,
    }


# ------------------------------------------------------------------
# MEDICATION UPDATE
# ------------------------------------------------------------------

@router.patch("/{medication_id}")
def update_medication(
    medication_id: int,
    update: MedicationUpdateRequest,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update medication details. Does not change schedule (use schedule endpoint)."""
    med = _get_owned_medication(medication_id, current_user, db)

    if update.name is not None:
        med.name = update.name.strip()
    if update.dosage is not None:
        med.dosage = update.dosage.strip()
    if update.frequency is not None:
        med.frequency = update.frequency.strip()
    if update.instructions is not None:
        med.instructions = update.instructions.strip()
    if update.end_date is not None:
        med.end_date = update.end_date
    if update.is_active is not None:
        med.is_active = update.is_active

    db.commit()
    db.refresh(med)
    return {"message": "Medication updated", "medication_id": med.id}


# ------------------------------------------------------------------
# DEACTIVATE MEDICATION
# ------------------------------------------------------------------

@router.delete("/{medication_id}/deactivate")
def deactivate_medication(
    medication_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deactivate a medication (soft delete).
    Does not delete historical dose records.
    """
    med = _get_owned_medication(medication_id, current_user, db)
    med.is_active = False

    # Deactivate the schedule so no new occurrences are generated
    active_schedule = (
        db.query(MedicationSchedule)
        .filter(
            MedicationSchedule.medication_id == med.id,
            MedicationSchedule.is_active.is_(True),
        )
        .first()
    )
    if active_schedule:
        active_schedule.is_active = False
        active_schedule.effective_until = datetime.utcnow()

    db.commit()
    return {"message": "Medication deactivated", "medication_id": medication_id}


# ------------------------------------------------------------------
# GET ALL MEDICATIONS (active + inactive)
# ------------------------------------------------------------------

@router.get("/user/{user_id}/all")
def get_all_medications(
    user_id: int,
    include_inactive: bool = Query(default=False),
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all medications for a user, including inactive ones."""
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    query = db.query(Medication).filter(Medication.user_id == current_user.id)
    if not include_inactive:
        query = query.filter(Medication.is_active.is_(True))

    medications = query.order_by(Medication.created_at.desc()).all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "dosage": m.dosage,
            "frequency": m.frequency,
            "instructions": m.instructions,
            "start_date": m.start_date.isoformat(),
            "end_date": m.end_date.isoformat() if m.end_date else None,
            "is_active": m.is_active,
            "created_at": m.created_at.isoformat(),
        }
        for m in medications
    ]


# ------------------------------------------------------------------
# SCHEDULE MANAGEMENT
# ------------------------------------------------------------------

@router.post("/{medication_id}/schedule")
def create_or_update_schedule(
    medication_id: int,
    schedule_data: ScheduleCreate,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create or replace the schedule for a medication.

    Policy: Old schedule is deactivated; a new one is created.
    Historical dose occurrences under the old schedule are preserved.
    New occurrences are generated under the new schedule.
    """
    med = _get_owned_medication(medication_id, current_user, db)

    if not med.is_active:
        raise HTTPException(
            status_code=400,
            detail="Cannot create schedule for an inactive medication",
        )

    # Validate times format
    for t in schedule_data.times:
        parts = t.split(":")
        if len(parts) != 2:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid time format '{t}'. Expected HH:MM",
            )
        try:
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError()
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid time value '{t}'",
            )

    if schedule_data.schedule_type == "weekly" and not schedule_data.weekdays:
        raise HTTPException(
            status_code=422,
            detail="Weekly schedule requires at least one weekday",
        )

    # Deactivate existing active schedule
    existing = (
        db.query(MedicationSchedule)
        .filter(
            MedicationSchedule.medication_id == medication_id,
            MedicationSchedule.is_active.is_(True),
        )
        .first()
    )
    if existing:
        existing.is_active = False
        existing.effective_until = datetime.utcnow()

    # Create new schedule
    new_schedule = MedicationSchedule(
        medication_id=medication_id,
        schedule_type=schedule_data.schedule_type,
        times_of_day_json=json.dumps(schedule_data.times),
        weekdays_json=json.dumps(schedule_data.weekdays),
        timezone=schedule_data.timezone,
        effective_from=datetime.utcnow(),
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(new_schedule)
    db.flush()  # get new_schedule.id

    # Generate upcoming occurrences
    ensure_occurrences_for_window(db, med, days_ahead=7)
    db.commit()

    return {
        "message": "Schedule created successfully",
        "schedule_id": new_schedule.id,
        "medication_id": medication_id,
        "schedule_type": schedule_data.schedule_type,
        "times": schedule_data.times,
        "weekdays": schedule_data.weekdays,
        "timezone": schedule_data.timezone,
    }


@router.get("/{medication_id}/schedule")
def get_medication_schedule(
    medication_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the active schedule for a medication."""
    med = _get_owned_medication(medication_id, current_user, db)

    schedule = (
        db.query(MedicationSchedule)
        .filter(
            MedicationSchedule.medication_id == med.id,
            MedicationSchedule.is_active.is_(True),
        )
        .first()
    )

    if not schedule:
        return {"medication_id": medication_id, "schedule": None}

    return {
        "medication_id": medication_id,
        "schedule": {
            "id": schedule.id,
            "schedule_type": schedule.schedule_type,
            "times": json.loads(schedule.times_of_day_json or "[]"),
            "weekdays": json.loads(schedule.weekdays_json or "[]"),
            "timezone": schedule.timezone,
            "effective_from": schedule.effective_from.isoformat(),
            "is_active": schedule.is_active,
        },
    }


# ------------------------------------------------------------------
# DOSE OCCURRENCES
# ------------------------------------------------------------------

@router.get("/{medication_id}/occurrences")
def get_dose_occurrences(
    medication_id: int,
    days_back: int = Query(default=7, ge=0, le=90),
    days_ahead: int = Query(default=1, ge=0, le=30),
    status_filter: Optional[str] = Query(default=None),
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get dose occurrences for a medication within a time window.

    Refreshes occurrence statuses before returning.
    """
    med = _get_owned_medication(medication_id, current_user, db)

    # Ensure upcoming occurrences are generated
    ensure_occurrences_for_window(db, med, days_ahead=max(days_ahead + 1, 7))

    # Refresh statuses
    refresh_occurrence_statuses(db, current_user.id)
    db.commit()

    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - __import__("datetime").timedelta(days=days_back)
    end = now + __import__("datetime").timedelta(days=days_ahead + 1)

    query = db.query(MedicationDoseOccurrence).filter(
        MedicationDoseOccurrence.medication_id == medication_id,
        MedicationDoseOccurrence.scheduled_at >= start,
        MedicationDoseOccurrence.scheduled_at <= end,
    )

    if status_filter:
        query = query.filter(MedicationDoseOccurrence.status == status_filter)

    occurrences = query.order_by(MedicationDoseOccurrence.scheduled_at.asc()).all()

    return {
        "medication_id": medication_id,
        "medication_name": med.name,
        "occurrences": [
            {
                "id": occ.id,
                "scheduled_at": occ.scheduled_at.isoformat(),
                "status": occ.status,
                "taken_at": occ.taken_at.isoformat() if occ.taken_at else None,
                "notes": occ.notes,
                "updated_at": occ.updated_at.isoformat(),
            }
            for occ in occurrences
        ],
        "total": len(occurrences),
    }


@router.patch("/occurrences/{occurrence_id}")
def confirm_dose(
    occurrence_id: int,
    request: DoseConfirmRequest,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Confirm a dose as taken, skipped, or missed.

    Enforces ownership. A dose can be corrected after initial confirmation.
    """
    occ = db.query(MedicationDoseOccurrence).filter(
        MedicationDoseOccurrence.id == occurrence_id
    ).first()

    if not occ:
        raise HTTPException(status_code=404, detail="Dose occurrence not found")

    # Ownership check via medication
    med = db.query(Medication).filter(Medication.id == occ.medication_id).first()
    if not med or med.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if request.status == "taken":
        occ.taken_at = request.taken_at or datetime.utcnow()
    else:
        occ.taken_at = None

    occ.status = request.status
    occ.notes = request.notes
    occ.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(occ)

    return {
        "occurrence_id": occ.id,
        "status": occ.status,
        "taken_at": occ.taken_at.isoformat() if occ.taken_at else None,
        "notes": occ.notes,
    }


# ------------------------------------------------------------------
# TODAY'S DOSES
# ------------------------------------------------------------------

@router.get("/user/{user_id}/today")
def get_todays_doses(
    user_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all dose occurrences for today for a user."""
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Refresh statuses for all user medications
    refresh_occurrence_statuses(db, user_id)
    db.commit()

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Get active medication IDs for user
    active_med_ids = [
        row[0]
        for row in db.query(Medication.id)
        .filter(Medication.user_id == user_id, Medication.is_active.is_(True))
        .all()
    ]

    if not active_med_ids:
        return {"date": today_start.date().isoformat(), "doses": [], "total": 0}

    occurrences = (
        db.query(MedicationDoseOccurrence)
        .filter(
            MedicationDoseOccurrence.medication_id.in_(active_med_ids),
            MedicationDoseOccurrence.scheduled_at >= today_start,
            MedicationDoseOccurrence.scheduled_at <= today_end,
        )
        .order_by(MedicationDoseOccurrence.scheduled_at.asc())
        .all()
    )

    # Enrich with medication name
    med_names = {
        m.id: m.name
        for m in db.query(Medication).filter(Medication.id.in_(active_med_ids)).all()
    }

    return {
        "date": today_start.date().isoformat(),
        "doses": [
            {
                "occurrence_id": occ.id,
                "medication_id": occ.medication_id,
                "medication_name": med_names.get(occ.medication_id, "Unknown"),
                "scheduled_at": occ.scheduled_at.isoformat(),
                "status": occ.status,
                "taken_at": occ.taken_at.isoformat() if occ.taken_at else None,
                "notes": occ.notes,
            }
            for occ in occurrences
        ],
        "total": len(occurrences),
    }


# ------------------------------------------------------------------
# ADHERENCE ANALYTICS (schedule-based)
# ------------------------------------------------------------------

@router.get("/{medication_id}/adherence-v2")
def get_medication_adherence_v2(
    medication_id: int,
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Schedule-based adherence analytics.

    More accurate than the basic adherence endpoint in main.py
    because it uses actual scheduled occurrences, not just manual logs.
    """
    med = _get_owned_medication(medication_id, current_user, db)
    refresh_occurrence_statuses(db, current_user.id)
    db.commit()
    return get_medication_adherence_summary(db, med)


# ------------------------------------------------------------------
# MEDICATION TIMELINE
# ------------------------------------------------------------------

@router.get("/{medication_id}/timeline")
def get_medication_timeline_view(
    medication_id: int,
    days_back: int = Query(default=7, ge=1, le=90),
    days_ahead: int = Query(default=1, ge=0, le=7),
    current_user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a chronological timeline of dose events for a medication."""
    med = _get_owned_medication(medication_id, current_user, db)
    refresh_occurrence_statuses(db, current_user.id)
    db.commit()

    timeline = get_medication_timeline(db, med, days_back=days_back, days_ahead=days_ahead)
    return {
        "medication_id": medication_id,
        "medication_name": med.name,
        "timeline": timeline,
        "total_entries": len(timeline),
    }
