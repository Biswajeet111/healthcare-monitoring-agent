from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, time

from healthguard.database.models import MedicationLog
from healthguard.schemas import MedicationLogCreate, MedicationLogResponse
from healthguard.schemas import MedicationCreate, MedicationResponse
from healthguard.database.models import Medication
from healthguard.database.session import get_db
from healthguard.database import models
from healthguard.schemas import (
    UserProfileCreate,
    UserProfileResponse,
    HealthMetricCreate,
    HealthMetricResponse,
)

app = FastAPI(
    title="HealthGuard AI",
    description="Agentic AI-Powered Personal Healthcare Intelligence Platform",
    version="1.0.0",
)


@app.get("/")
def home():
    return {"message": "HealthGuard AI API is running"}


@app.post("/users", response_model=UserProfileResponse)
def create_user(
    user: UserProfileCreate,
    db: Session = Depends(get_db),
):
    if user.email:
        existing_user = (
            db.query(models.UserProfile)
            .filter(models.UserProfile.email == user.email)
            .first()
        )

        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="Email already registered",
            )

    new_user = models.UserProfile(**user.model_dump())

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@app.post("/metrics", response_model=HealthMetricResponse)
def create_metric(
    metric: HealthMetricCreate,
    user_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(models.UserProfile).filter(
        models.UserProfile.id == user_id
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_metric = models.HealthMetric(
        user_id=user_id,
        **metric.model_dump(),
    )

    db.add(new_metric)
    db.commit()
    db.refresh(new_metric)

    return new_metric


@app.get("/users/{user_id}/metrics", response_model=list[HealthMetricResponse])
def get_user_metrics(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(models.UserProfile).filter(
        models.UserProfile.id == user_id
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return (
        db.query(models.HealthMetric)
        .filter(models.HealthMetric.user_id == user_id)
        .order_by(models.HealthMetric.recorded_at.desc())
        .all()
    )

@app.post("/medications", response_model=MedicationResponse)
def create_medication(
    medication: MedicationCreate,
    user_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(models.UserProfile).filter(
        models.UserProfile.id == user_id
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    medication_data = medication.model_dump()

    # Convert date objects into SQLAlchemy DateTime values.
    medication_data["start_date"] = datetime.combine(
        medication_data["start_date"], time.min
    )

    if medication_data["end_date"]:
        medication_data["end_date"] = datetime.combine(
            medication_data["end_date"], time.min
        )

    new_medication = Medication(
        user_id=user_id,
        **medication_data
    )

    db.add(new_medication)
    db.commit()
    db.refresh(new_medication)

    return new_medication


@app.get("/users/{user_id}/medications", response_model=list[MedicationResponse])
def get_user_medications(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(models.UserProfile).filter(
        models.UserProfile.id == user_id
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return (
        db.query(Medication)
        .filter(
            Medication.user_id == user_id,
            Medication.is_active == True
        )
        .order_by(Medication.created_at.desc())
        .all()
    )

@app.post(
    "/medications/{medication_id}/logs",
    response_model=MedicationLogResponse
)
def record_medication_log(
    medication_id: int,
    log: MedicationLogCreate,
    db: Session = Depends(get_db),
):
    medication = db.query(Medication).filter(
        Medication.id == medication_id
    ).first()

    if not medication:
        raise HTTPException(
            status_code=404,
            detail="Medication not found"
        )

    log_data = log.model_dump()

    if log_data["status"] == "taken":
        if log_data["taken_at"] is None:
            log_data["taken_at"] = datetime.utcnow()
    else:
        if log_data["taken_at"] is not None:
            raise HTTPException(
                status_code=400,
                detail="taken_at is only valid when status is taken"
            )

    new_log = MedicationLog(
        medication_id=medication_id,
        **log_data
    )

    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return new_log


@app.get(
    "/medications/{medication_id}/logs",
    response_model=list[MedicationLogResponse]
)
def get_medication_logs(
    medication_id: int,
    db: Session = Depends(get_db),
):
    medication = db.query(Medication).filter(
        Medication.id == medication_id
    ).first()

    if not medication:
        raise HTTPException(
            status_code=404,
            detail="Medication not found"
        )

    return (
        db.query(MedicationLog)
        .filter(MedicationLog.medication_id == medication_id)
        .order_by(MedicationLog.scheduled_at.desc())
        .all()
    )


@app.get("/medications/{medication_id}/adherence")
def get_medication_adherence(
    medication_id: int,
    db: Session = Depends(get_db),
):
    medication = db.query(Medication).filter(
        Medication.id == medication_id
    ).first()

    if not medication:
        raise HTTPException(
            status_code=404,
            detail="Medication not found"
        )

    logs = db.query(MedicationLog).filter(
        MedicationLog.medication_id == medication_id
    ).all()

    taken = sum(log.status == "taken" for log in logs)
    missed = sum(log.status == "missed" for log in logs)
    skipped = sum(log.status == "skipped" for log in logs)

    eligible_doses = taken + missed

    percentage = (
        round((taken / eligible_doses) * 100, 2)
        if eligible_doses > 0
        else None
    )

    return {
        "medication_id": medication_id,
        "medication_name": medication.name,
        "total_logged": len(logs),
        "taken": taken,
        "missed": missed,
        "skipped": skipped,
        "adherence_percentage": percentage
    }