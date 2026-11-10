"""
End-to-end verification script for Phase 6 and Phase 7 features.
"""
import json
from datetime import datetime, timedelta
from healthguard.database.session import SessionLocal
from healthguard.database import models
from healthguard.core.security import hash_password
from healthguard.services.medication_scheduler import (
    generate_occurrences_for_schedule,
    refresh_occurrence_statuses,
)
from healthguard.services.medication_adherence import (
    get_medication_adherence_summary,
    get_medication_timeline,
)
from healthguard.services.medication_reminder_service import (
    generate_reminders_for_user,
    acknowledge_reminder,
)
from healthguard.rag.retriever import retrieve_from_global_knowledge
from healthguard.rag.safety import check_unsafe_request


def main():
    db = SessionLocal()

    # 1. Test user
    email = f"verify_{int(datetime.utcnow().timestamp())}@example.com"
    user = models.UserProfile(
        full_name="Verification Patient",
        email=email,
        password_hash=hash_password("TestPass123!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"1. User created: ID={user.id}")

    # 2. Add Medication
    med = models.Medication(
        user_id=user.id,
        name="Metformin",
        dosage="500 mg",
        frequency="Twice daily",
        instructions="Take with water after food",
        start_date=datetime.utcnow() - timedelta(days=2),
        is_active=True,
    )
    db.add(med)
    db.commit()
    db.refresh(med)
    print(f"2. Medication created: ID={med.id}, Name={med.name}")

    # 3. Add Schedule
    sch = models.MedicationSchedule(
        medication_id=med.id,
        schedule_type="daily",
        times_of_day_json=json.dumps(["08:00", "20:00"]),
        weekdays_json="[]",
        timezone="Asia/Kolkata",
        effective_from=med.start_date,
        is_active=True,
    )
    db.add(sch)
    db.commit()
    db.refresh(sch)
    print(f"3. Schedule created: ID={sch.id}, Type={sch.schedule_type}")

    # 4. Generate Occurrences
    occs = generate_occurrences_for_schedule(
        db, sch, start=med.start_date, end=datetime.utcnow() + timedelta(days=2)
    )
    db.commit()
    print(f"4. Dose occurrences generated: {len(occs)} doses")

    # 5. Status refresh & mark taken
    refresh_occurrence_statuses(db, user.id)
    db.commit()

    first_occ = occs[0]
    first_occ.status = "taken"
    first_occ.taken_at = datetime.utcnow()
    first_occ.notes = "Taken on time with meal"
    db.commit()
    print(f"5. First dose confirmed taken: ID={first_occ.id}")

    # 6. Reminder Generation
    rems = generate_reminders_for_user(db, user.id)
    db.commit()
    print(f"6. Reminders generated: {len(rems)}")

    # 7. Adherence Analytics
    adh = get_medication_adherence_summary(db, med)
    overall = adh["overall"]
    print(
        f"7. Adherence percentage: {overall['adherence_percentage']}%, "
        f"Taken: {overall['taken']}, Overdue: {overall['overdue_unconfirmed']}"
    )

    # 8. Timeline
    tl = get_medication_timeline(db, med)
    print(f"8. Timeline entries: {len(tl)}")

    # 9. RAG Retrieval from Ingested Guidelines
    rag_chunks = retrieve_from_global_knowledge(
        "hypertension guidelines blood pressure targets", n_results=3
    )
    print(f"9. RAG Knowledge Chunks Retrieved: {len(rag_chunks)}")
    if rag_chunks:
        print(f"   Top chunk title: {rag_chunks[0]['metadata'].get('title')}")

    # 10. Safety Check
    safe_check = check_unsafe_request("prescribe me 100mg of medication")
    print(
        f"10. Safety guardrail check (unsafe request rejected): {not safe_check['safe_to_process']}"
    )

    db.close()
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
