from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

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