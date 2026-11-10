"""
Medication Agent — Phase 8

Evaluates scheduled doses, missed doses, and adherence trends.
Identifies pending reminders requiring user attention.
NEVER autonomously changes medication dosages or schedules.
"""

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from healthguard.database.models import (
    Medication,
    MedicationDoseOccurrence,
    MedicationReminder,
)
from healthguard.services.medication_scheduler import refresh_occurrence_statuses
from healthguard.services.medication_adherence import get_medication_adherence_summary
from healthguard.orchestration.schemas import MedicationAgentResult

logger = logging.getLogger(__name__)


class MedicationAgent:
    """Agent responsible for deterministic medication schedule tracking and adherence analysis."""

    def __init__(self, db: Session):
        self.db = db

    def evaluate_medications(
        self,
        user_id: int,
        now_utc: Optional[datetime] = None,
    ) -> MedicationAgentResult:
        """
        Evaluate active medications, dose statuses, and adherence trends for a user.
        """
        if now_utc is None:
            now_utc = datetime.utcnow()

        # 1. Refresh dose occurrence statuses deterministically
        refresh_occurrence_statuses(self.db, user_id, now_utc)

        # 2. Query active medications for user
        meds = list(
            self.db.scalars(
                select(Medication).where(
                    Medication.user_id == user_id,
                    Medication.is_active.is_(True),
                )
            ).all()
        )

        if not meds:
            return MedicationAgentResult(
                active_medications_count=0,
                overall_adherence_percentage=None,
                overdue_doses_count=0,
                missed_doses_count=0,
                taken_doses_count=0,
                pending_reminders=[],
                adherence_by_medication=[],
                summary="No active medications found for this profile.",
                recommendations=["Keep medication records up to date to enable adherence tracking."],
            )

        total_taken = 0
        total_missed = 0
        total_overdue = 0
        total_evaluable = 0
        adherence_list = []
        recommendations = []

        for med in meds:
            summary = get_medication_adherence_summary(self.db, med, now_utc)
            overall = summary.get("overall", {})
            taken = overall.get("taken", 0)
            missed = overall.get("missed", 0)
            overdue = overall.get("overdue_unconfirmed", 0)
            evaluable = overall.get("evaluable_past_doses", 0)
            pct = overall.get("adherence_percentage")

            total_taken += taken
            total_missed += missed
            total_overdue += overdue
            total_evaluable += evaluable

            adherence_list.append({
                "medication_id": med.id,
                "name": med.name,
                "dosage": med.dosage,
                "frequency": med.frequency,
                "adherence_percentage": pct,
                "taken": taken,
                "missed": missed,
                "overdue": overdue,
            })

            if overdue > 0:
                recommendations.append(
                    f"{med.name} ({med.dosage}): {overdue} scheduled dose(s) are overdue. Please confirm or log dose status."
                )
            if pct is not None and pct < 75.0:
                recommendations.append(
                    f"{med.name} adherence is currently {pct}%. Consistent adherence is recommended for optimal therapy."
                )

        # Overall adherence percentage across all active medications
        overall_pct = (
            round((total_taken / total_evaluable) * 100, 2)
            if total_evaluable > 0
            else None
        )

        # 3. Retrieve pending reminders
        reminders = list(
            self.db.scalars(
                select(MedicationReminder)
                .where(
                    MedicationReminder.user_id == user_id,
                    MedicationReminder.status == "pending",
                )
                .order_by(MedicationReminder.created_at.desc())
                .limit(10)
            ).all()
        )
        reminder_items = [
            {
                "id": r.id,
                "occurrence_id": r.occurrence_id,
                "medication_id": r.medication_id,
                "message": r.message,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in reminders
        ]

        # Construct summary
        pct_str = f"{overall_pct}%" if overall_pct is not None else "N/A (no past doses)"
        summary_text = (
            f"{len(meds)} active medication(s). "
            f"Overall adherence: {pct_str} "
            f"({total_taken} taken, {total_missed} missed, {total_overdue} unconfirmed/overdue). "
            f"{len(reminder_items)} pending reminder(s)."
        )

        return MedicationAgentResult(
            active_medications_count=len(meds),
            overall_adherence_percentage=overall_pct,
            overdue_doses_count=total_overdue,
            missed_doses_count=total_missed,
            taken_doses_count=total_taken,
            pending_reminders=reminder_items,
            adherence_by_medication=adherence_list,
            summary=summary_text,
            recommendations=recommendations,
        )
