from collections import defaultdict
from datetime import datetime, time
from uuid import uuid4
import hashlib
import math
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from healthguard.api.monitoring_events import (
    router as monitoring_events_router,
)
from healthguard.api.notifications import (
    router as notifications_router,
)
from healthguard.api.medication_management import (
    router as medication_management_router,
)
from healthguard.api.medication_reminders import (
    router as medication_reminders_router,
)
from healthguard.api.medical_rag import (
    router as medical_rag_router,
)
from healthguard.api.orchestration import (
    router as orchestration_router,
)
from sqlalchemy.orm import Session
from healthguard.services.csv_service import parse_health_csv
from healthguard.database.models import MedicalDocument
from healthguard.services.document_service import process_medical_pdf
from healthguard.schemas import MedicalDocumentResponse
from healthguard.core.dependencies import get_current_user
from healthguard.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from fastapi import Query

from healthguard.agents.monitoring_trigger import trigger_monitoring_for_metric
from healthguard.services.notification_service import (
    process_in_app_notification,
)
from healthguard.agents.monitoring_orchestrator import (
    run_monitoring_pipeline,
    MonitoringOrchestrationError,
)
from healthguard.analytics.longitudinal_analyzer import (
    analyze_longitudinal_health,
    LongitudinalAnalysisError,
)
from healthguard.analytics.trend_analyzer import (
    analyze_health_trend,
    TrendAnalysisError,
)
import logging
from healthguard.schemas import DiabetesPredictionV3Response

from healthguard.ml.diabetes_v3_predictor import (
    predict_diabetes_v3,
)

from healthguard.ml.diabetes_predictor import predict_diabetes
from healthguard.services.normalization import normalize_measurement
from healthguard.database import models
from healthguard.database.models import Medication, MedicationLog
from healthguard.database.session import get_db
from healthguard.schemas import (
    BloodPressureCreate,
    DiabetesPredictionRequest,
    DiabetesPredictionResponse,
    HealthMetricCreate,
    HealthMetricResponse,
    MedicationCreate,
    MedicationLogCreate,
    MedicationLogResponse,
    MedicationResponse,
    TokenResponse,
    UserLogin,
    UserProfileResponse,
    UserRegister,
)


logger = logging.getLogger(__name__)

app = FastAPI(
    title="HealthGuard AI",
    description="Agentic AI-Powered Personal Healthcare Intelligence Platform",
    version="1.0.0",
)
app.include_router(monitoring_events_router)
app.include_router(notifications_router)
app.include_router(medication_management_router)
app.include_router(medication_reminders_router)
app.include_router(medical_rag_router)
app.include_router(orchestration_router)


# Start medication reminder worker on startup
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    from healthguard.services.medication_reminder_service import (
        start_reminder_worker,
        stop_reminder_worker,
    )
    start_reminder_worker()
    yield
    stop_reminder_worker()

app.router.lifespan_context = lifespan
def verify_user_access(
    requested_user_id: int,
    current_user: models.UserProfile,
) -> None:
    """Ensure the authenticated user can only access their own records."""
    if requested_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this user's data",
        )


def get_owned_medication(
    medication_id: int,
    current_user: models.UserProfile,
    db: Session,
) -> Medication:
    """Retrieve a medication only if it belongs to the authenticated user."""
    medication = (
        db.query(Medication)
        .filter(Medication.id == medication_id)
        .first()
    )

    if medication is None:
        raise HTTPException(
            status_code=404,
            detail="Medication not found",
        )

    if medication.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access this medication",
        )

    return medication


@app.get("/")
def home():
    return {"message": "HealthGuard AI API is running"}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@app.post("/auth/register", response_model=UserProfileResponse)
def register_user(
    user: UserRegister,
    db: Session = Depends(get_db),
):
    email = user.email.strip().lower()

    existing_user = (
        db.query(models.UserProfile)
        .filter(models.UserProfile.email == email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="Email already registered",
        )

    new_user = models.UserProfile(
        full_name=user.full_name.strip(),
        email=email,
        password_hash=hash_password(user.password),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@app.post("/auth/login", response_model=TokenResponse)
def login_user(
    credentials: UserLogin,
    db: Session = Depends(get_db),
):
    email = credentials.email.strip().lower()

    user = (
        db.query(models.UserProfile)
        .filter(models.UserProfile.email == email)
        .first()
    )

    if user is None or not user.password_hash:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token({"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.get("/auth/me", response_model=UserProfileResponse)
def get_my_profile(
    current_user: models.UserProfile = Depends(get_current_user),
):
    return current_user


# ---------------------------------------------------------------------------
# Best-effort monitoring after successful measurement persistence
# ---------------------------------------------------------------------------

def _run_post_save_monitoring(
    db: Session,
    user_id: int,
    metric_ids: list[int],
) -> None:
    """Persist monitoring events, then publish eligible in-app notifications.

    Measurements are committed before this function is called.
    Monitoring and publication use separate transactions. Processing is
    synchronous and best-effort; durable retries are not implemented yet.
    """
    for metric_id in metric_ids:
        try:
            result = trigger_monitoring_for_metric(
                db=db,
                user_id=user_id,
                metric_id=metric_id,
            )
            db.commit()
            logger.info(
                "Monitoring trigger finished: user_id=%s metric_id=%s status=%s",
                user_id,
                metric_id,
                result.get("trigger_status"),
            )
        except Exception:
            db.rollback()
            logger.exception(
                "Monitoring trigger failed after measurement commit: "
                "user_id=%s metric_id=%s",
                user_id,
                metric_id,
            )
            continue

        event_id = result.get("event_id")
        if event_id is None or result.get("notification_status") != "pending":
            continue

        try:
            notification_result = process_in_app_notification(
                db=db,
                user_id=user_id,
                event_id=event_id,
            )
            db.commit()
            logger.info(
                "In-app notification processed: user_id=%s event_id=%s status=%s",
                user_id,
                event_id,
                notification_result.get("status"),
            )
        except Exception:
            db.rollback()
            logger.exception(
                "In-app notification publication failed: "
                "user_id=%s event_id=%s",
                user_id,
                event_id,
            )


# ---------------------------------------------------------------------------
# Health metrics
# ---------------------------------------------------------------------------

@app.post("/metrics", response_model=HealthMetricResponse)
def create_metric(
    metric: HealthMetricCreate,
    user_id: int,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    # Preserve original measurement
    original_value = metric.value
    original_unit = metric.unit

    # Normalize measurement
    normalized_value, normalized_unit = normalize_measurement(
        metric.metric_type,
        original_value,
        original_unit
    )

    new_metric = models.HealthMetric(
        user_id=current_user.id,
        metric_type=metric.metric_type,
        value=normalized_value,
        unit=normalized_unit,
        original_value=original_value,
        original_unit=original_unit,
        source=metric.source,
        context=metric.context,
        measurement_group_id=metric.measurement_group_id,
        notes=metric.notes,
    )

    db.add(new_metric)
    db.commit()
    db.refresh(new_metric)

    _run_post_save_monitoring(db, current_user.id, [new_metric.id])

    return new_metric


@app.get(
    "/users/{user_id}/metrics",
    response_model=list[HealthMetricResponse],
)
def get_user_metrics(
    user_id: int,
    metric_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 500",
        )

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be after end_date",
        )

    query = db.query(models.HealthMetric).filter(
        models.HealthMetric.user_id == current_user.id
    )

    if metric_type:
        query = query.filter(
            models.HealthMetric.metric_type == metric_type
        )

    if start_date:
        query = query.filter(
            models.HealthMetric.recorded_at >= start_date
        )

    if end_date:
        query = query.filter(
            models.HealthMetric.recorded_at <= end_date
        )

    return (
        query
        .order_by(models.HealthMetric.recorded_at.desc())
        .limit(limit)
        .all()
    )

# ---------------------------------------------------------------------------
# Longitudinal health trend analysis
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/metrics/{metric_type}/trend")
def get_health_metric_trend(
    user_id: int,
    metric_type: str,
    limit: int = 100,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Analyze historical measurements for one authenticated patient.

    Returns descriptive statistics only.
    Does not provide medical diagnoses.
    """

    verify_user_access(user_id, current_user)

    allowed_metric_types = {
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "blood_glucose",
        "heart_rate",
        "weight",
        "height",
        "steps",
        "sleep_duration",
    }

    if metric_type not in allowed_metric_types:
        raise HTTPException(
            status_code=422,
            detail="Unsupported metric type",
        )

    if limit < 2 or limit > 500:
        raise HTTPException(
            status_code=422,
            detail="Limit must be between 2 and 500",
        )

    metrics = (
        db.query(models.HealthMetric)
        .filter(
            models.HealthMetric.user_id == current_user.id,
            models.HealthMetric.metric_type == metric_type,
        )
        .order_by(
            models.HealthMetric.recorded_at.desc(),
            models.HealthMetric.id.desc(),
        )
        .limit(limit)
        .all()
    )

    if len(metrics) < 2:
        return {
            "user_id": current_user.id,
            "metric_type": metric_type,
            "total_readings": len(metrics),
            "message": "At least two readings are required",
            "unit_trends": [],
        }

    # Never combine incompatible units.
    grouped_metrics = defaultdict(list)

    for metric in metrics:
        grouped_metrics[metric.unit].append(metric)

    unit_trends = []

    for unit, unit_metrics in grouped_metrics.items():

        if len(unit_metrics) < 2:
            continue

        readings = [
            {
                "recorded_at": metric.recorded_at.isoformat(),
                "value": metric.value,
            }
            for metric in unit_metrics
        ]

        try:
            analysis = analyze_health_trend(readings)

        except (TrendAnalysisError, AttributeError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Stored health measurements cannot be analyzed",
            ) from exc

        unit_trends.append({
            "unit": unit,
            **analysis,
        })

    return {
        "user_id": current_user.id,
        "metric_type": metric_type,
        "total_readings": len(metrics),
        "unit_trends": unit_trends,
        "disclaimer": (
            "This analysis describes recorded measurements "
            "and does not establish a medical diagnosis."
        ),
    }

@app.get("/users/{user_id}/metrics/{metric_type}/longitudinal")
def get_longitudinal_health_analysis(
    user_id: int,
    metric_type: str,
    baseline_window: int = 5,
    recent_window: int = 3,
    anomaly_threshold: float = 2.0,
    limit: int = 200,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    allowed_metric_types = {
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "blood_glucose",
        "heart_rate",
        "weight",
        "height",
        "steps",
        "sleep_duration",
    }

    if metric_type not in allowed_metric_types:
        raise HTTPException(
            status_code=422,
            detail="Unsupported metric type",
        )

    if (
        baseline_window < 2
        or recent_window < 1
        or baseline_window + recent_window > 500
    ):
        raise HTTPException(
            status_code=422,
            detail="Invalid analysis windows",
        )

    if (
        not math.isfinite(anomaly_threshold)
        or anomaly_threshold <= 0
    ):
        raise HTTPException(
            status_code=422,
            detail="Invalid anomaly threshold",
        )

    if limit < 3 or limit > 500:
        raise HTTPException(
            status_code=422,
            detail="Limit must be between 3 and 500",
        )

    if baseline_window + recent_window > limit:
        raise HTTPException(
            status_code=422,
            detail="Analysis windows exceed reading limit",
        )

    metrics = (
        db.query(models.HealthMetric)
        .filter(
            models.HealthMetric.user_id == current_user.id,
            models.HealthMetric.metric_type == metric_type,
        )
        .order_by(
            models.HealthMetric.recorded_at.desc(),
            models.HealthMetric.id.desc(),
        )
        .limit(limit)
        .all()
    )

    grouped_metrics = defaultdict(list)

    for metric in metrics:
        grouped_metrics[metric.unit].append(metric)

    unit_analyses = []

    required_readings = baseline_window + recent_window

    for unit, unit_metrics in grouped_metrics.items():
        if len(unit_metrics) < required_readings:
            continue

        readings = [
            {
                "id": metric.id,
                "recorded_at": metric.recorded_at.isoformat(),
                "value": metric.value,
            }
        for metric in unit_metrics
    ]

        try:
            analysis = analyze_longitudinal_health(
                readings,
                baseline_window=baseline_window,
                recent_window=recent_window,
                anomaly_threshold=anomaly_threshold,
            )
        except LongitudinalAnalysisError as exc:
            raise HTTPException(
                status_code=422,
                detail="Stored measurements cannot be analyzed",
            ) from exc

        unit_analyses.append({
            "unit": unit,
            **analysis,
        })

    return {
        "user_id": current_user.id,
        "metric_type": metric_type,
        "total_readings": len(metrics),
        "required_readings": required_readings,
        "unit_analyses": unit_analyses,
        "message": (
            None
            if unit_analyses
            else "Insufficient compatible readings for analysis"
        ),
        "disclaimer": (
            "Statistical deviations are not medical diagnoses "
            "or validated clinical risk assessments."
        ),
    }
# ============================================================
# HEALTH MONITORING AGENT API
# ============================================================

@app.get("/users/{user_id}/metrics/{metric_type}/monitoring")
def get_health_monitoring_report(
    user_id: int,
    metric_type: str,
    baseline_window: int = Query(default=5, ge=2, le=499),
    recent_window: int = Query(default=3, ge=1, le=499),
    anomaly_threshold: float = Query(default=2.0, gt=0),
    limit: int = Query(default=200, ge=3, le=500),
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Run authenticated, deterministic health monitoring.

    The endpoint:
    - Enforces user ownership.
    - Retrieves the user's recorded measurements.
    - Separates incompatible measurement units.
    - Runs longitudinal analysis and monitoring decisions.
    - Validates generated decisions through the safety layer.
    - Returns non-diagnostic monitoring reports.

    No database writes or external AI services.
    """

    # --------------------------------------------------------
    # 1. Authentication and authorization
    # --------------------------------------------------------

    verify_user_access(user_id, current_user)

    # --------------------------------------------------------
    # 2. Validate requested metric
    # --------------------------------------------------------

    allowed_metric_types = {
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "blood_glucose",
        "heart_rate",
        "weight",
        "height",
        "steps",
        "sleep_duration",
    }

    if metric_type not in allowed_metric_types:
        raise HTTPException(
            status_code=422,
            detail="Unsupported metric type.",
        )

    if baseline_window + recent_window > limit:
        raise HTTPException(
            status_code=422,
            detail="Analysis windows exceed reading limit.",
        )

    if not math.isfinite(anomaly_threshold):
        raise HTTPException(
            status_code=422,
            detail="Anomaly threshold must be finite.",
        )

    # --------------------------------------------------------
    # 3. Fetch the user's latest measurements
    # --------------------------------------------------------

    metrics = (
        db.query(models.HealthMetric)
        .filter(
            models.HealthMetric.user_id == current_user.id,
            models.HealthMetric.metric_type == metric_type,
        )
        .order_by(
            models.HealthMetric.recorded_at.desc(),
            models.HealthMetric.id.desc(),
        )
        .limit(limit)
        .all()
    )

    # --------------------------------------------------------
    # 4. Group measurements by unit
    # --------------------------------------------------------

    grouped_metrics = defaultdict(list)

    for metric in metrics:
        grouped_metrics[metric.unit].append(metric)

    required_readings = baseline_window + recent_window

    reports = []
    insufficient_units = []

    # --------------------------------------------------------
    # 5. Execute monitoring pipeline for each unit
    # --------------------------------------------------------

    for unit, unit_metrics in sorted(
        grouped_metrics.items(),
        key=lambda item: str(item[0]),
    ):

        if len(unit_metrics) < required_readings:
            insufficient_units.append({
                "unit": unit,
                "available_readings": len(unit_metrics),
                "required_readings": required_readings,
            })
            continue

        # Sort chronologically, using database ID as the
        # deterministic tie-breaker for equal timestamps.
        chronological_metrics = sorted(
            unit_metrics,
            key=lambda metric: (
                metric.recorded_at,
                metric.id,
            ),
        )

        readings = [
            {
                "id": metric.id,
                "recorded_at": metric.recorded_at.isoformat(),
                "value": metric.value,
            }
            for metric in chronological_metrics
        ]

        try:
            report = run_monitoring_pipeline(
                metric_type=metric_type,
                unit=unit,
                readings=readings,
                baseline_window=baseline_window,
                recent_window=recent_window,
                anomaly_threshold=anomaly_threshold,
            )

        except MonitoringOrchestrationError as exc:
            # Do not expose stored health values or internal
            # implementation details through error messages.
            raise HTTPException(
                status_code=422,
                detail=(
                    "Stored measurements could not be "
                    "processed safely."
                ),
            ) from exc

        reports.append(report)

    # --------------------------------------------------------
    # 6. Return structured monitoring results
    # --------------------------------------------------------

    return {
        "user_id": current_user.id,
        "metric_type": metric_type,
        "total_readings": len(metrics),
        "required_readings": required_readings,
        "reports": reports,
        "insufficient_units": insufficient_units,
        "message": (
            None
            if reports
            else "Insufficient compatible readings for monitoring."
        ),
        "disclaimer": (
            "Monitoring priorities indicate statistical "
            "data-review attention only, not medical urgency. "
            "These results do not diagnose conditions, "
            "establish medical safety, or recommend treatment."
        ),
    }
@app.get("/users/{user_id}/metrics/analytics")
def get_metric_analytics(
    user_id: int,
    metric_type: str,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    metrics = (
        db.query(models.HealthMetric)
        .filter(
            models.HealthMetric.user_id == current_user.id,
            models.HealthMetric.metric_type == metric_type,
        )
        .order_by(models.HealthMetric.recorded_at.asc())
        .all()
    )

    if not metrics:
        return {
            "user_id": current_user.id,
            "metric_type": metric_type,
            "total_readings": 0,
            "message": "No readings available",
        }

    # Keep units separate so incompatible measurements are never averaged.
    by_unit = defaultdict(list)
    for metric in metrics:
        by_unit[metric.unit].append(metric)

    summaries = []

    for unit, unit_metrics in by_unit.items():
        values = [item.value for item in unit_metrics]
        daily_data = defaultdict(list)

        for item in unit_metrics:
            daily_data[item.recorded_at.date().isoformat()].append(item.value)

        daily_averages = [
            {
                "date": day,
                "average": round(sum(day_values) / len(day_values), 2),
            }
            for day, day_values in sorted(daily_data.items())
        ]

        summaries.append({
            "unit": unit,
            "total_readings": len(values),
            "average": round(sum(values) / len(values), 2),
            "minimum": min(values),
            "maximum": max(values),
            "first_reading": values[0],
            "latest_reading": values[-1],
            "daily_averages": daily_averages,
        })

    return {
        "user_id": current_user.id,
        "metric_type": metric_type,
        "unit_summaries": summaries,
    }


@app.post("/users/{user_id}/metrics/blood-pressure")
def create_blood_pressure(
    user_id: int,
    reading: BloodPressureCreate,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    measurement_group_id = str(uuid4())

    systolic = models.HealthMetric(
        user_id=current_user.id,
        metric_type="blood_pressure_systolic",
        value=reading.systolic,
        unit=reading.unit,
        original_value=reading.systolic,
        original_unit=reading.unit,
        source=reading.source,
        context=reading.context,
        measurement_group_id=measurement_group_id,
        notes=reading.notes,
    )

    diastolic = models.HealthMetric(
        user_id=current_user.id,
        metric_type="blood_pressure_diastolic",
        value=reading.diastolic,
        unit=reading.unit,
        original_value=reading.diastolic,
        original_unit=reading.unit,
        source=reading.source,
        context=reading.context,
        measurement_group_id=measurement_group_id,
        notes=reading.notes,
    )

    try:
        db.add_all([systolic, diastolic])
        db.commit()
        db.refresh(systolic)
        db.refresh(diastolic)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to save blood pressure readings",
        )

    # Run separately for each metric type after both measurements are saved.
    _run_post_save_monitoring(
        db, current_user.id, [systolic.id, diastolic.id]
    )

    return {
        "message": "Blood pressure recorded successfully",
        "measurement_group_id": measurement_group_id,
        "systolic": {
            "id": systolic.id,
            "value": systolic.value,
            "unit": systolic.unit,
        },
        "diastolic": {
            "id": diastolic.id,
            "value": diastolic.value,
            "unit": diastolic.unit,
        },
    }


@app.get("/users/{user_id}/metrics/blood-pressure/history")
def get_blood_pressure_history(
    user_id: int,
    limit: int = 100,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 500",
        )

    metrics = (
        db.query(models.HealthMetric)
        .filter(
            models.HealthMetric.user_id == current_user.id,
            models.HealthMetric.metric_type.in_([
                "blood_pressure_systolic",
                "blood_pressure_diastolic",
            ]),
            models.HealthMetric.measurement_group_id.isnot(None),
        )
        .order_by(models.HealthMetric.recorded_at.desc())
        .all()
    )

    grouped_readings = defaultdict(dict)

    for metric in metrics:
        grouped_readings[metric.measurement_group_id][metric.metric_type] = metric

    paired_readings = []

    for group_id, readings in grouped_readings.items():
        systolic = readings.get("blood_pressure_systolic")
        diastolic = readings.get("blood_pressure_diastolic")

        if systolic is None or diastolic is None:
            continue

        # A valid pair must use the same unit and timestamp.
        if systolic.unit != diastolic.unit:
            continue

        paired_readings.append({
            "measurement_group_id": group_id,
            "recorded_at": systolic.recorded_at,
            "systolic": systolic.value,
            "diastolic": diastolic.value,
            "unit": systolic.unit,
            "context": systolic.context,
            "source": systolic.source,
        })

    paired_readings.sort(
        key=lambda item: item["recorded_at"],
        reverse=True,
    )
    paired_readings = paired_readings[:limit]

    if not paired_readings:
        return {
            "user_id": current_user.id,
            "total_readings": 0,
            "history": [],
            "message": "No paired blood pressure readings available",
        }

    systolic_values = [item["systolic"] for item in paired_readings]
    diastolic_values = [item["diastolic"] for item in paired_readings]

    return {
        "user_id": current_user.id,
        "total_readings": len(paired_readings),
        "statistics": {
            "average_systolic": round(
                sum(systolic_values) / len(systolic_values), 2
            ),
            "average_diastolic": round(
                sum(diastolic_values) / len(diastolic_values), 2
            ),
            "highest_systolic": max(systolic_values),
            "lowest_systolic": min(systolic_values),
            "highest_diastolic": max(diastolic_values),
            "lowest_diastolic": min(diastolic_values),
        },
        "history": paired_readings,
    }


@app.get("/users/{user_id}/metrics/summary")
def get_metrics_summary(
    user_id: int,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be after end_date",
        )

    query = db.query(models.HealthMetric).filter(
        models.HealthMetric.user_id == current_user.id
    )

    if start_date:
        query = query.filter(
            models.HealthMetric.recorded_at >= start_date
        )

    if end_date:
        query = query.filter(
            models.HealthMetric.recorded_at <= end_date
        )

    metrics = query.order_by(
        models.HealthMetric.recorded_at.asc()
    ).all()

    grouped_metrics = defaultdict(list)

    for metric in metrics:
        grouped_metrics[(metric.metric_type, metric.unit)].append(metric)

    summaries = []

    for (metric_type, unit), readings in grouped_metrics.items():
        values = [reading.value for reading in readings]
        daily_data = defaultdict(list)

        for reading in readings:
            day = reading.recorded_at.date().isoformat()
            daily_data[day].append(reading.value)

        daily_averages = [
            {
                "date": day,
                "average": round(sum(day_values) / len(day_values), 2),
            }
            for day, day_values in sorted(daily_data.items())
        ]

        latest = readings[-1]

        summaries.append({
            "metric_type": metric_type,
            "unit": unit,
            "total_readings": len(readings),
            "average": round(sum(values) / len(values), 2),
            "minimum": min(values),
            "maximum": max(values),
            "latest_reading": {
                "value": latest.value,
                "recorded_at": latest.recorded_at,
                "context": latest.context,
                "source": latest.source,
            },
            "daily_averages": daily_averages,
        })

    return {
        "user_id": current_user.id,
        "total_readings": len(metrics),
        "total_metric_groups": len(summaries),
        "summaries": summaries,
    }


# ---------------------------------------------------------------------------
# Medication management
# ---------------------------------------------------------------------------

@app.post("/medications", response_model=MedicationResponse)
def create_medication(
    medication: MedicationCreate,
    user_id: int,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    medication_data = medication.model_dump()

    medication_data["start_date"] = datetime.combine(
        medication_data["start_date"],
        time.min,
    )

    if medication_data["end_date"]:
        medication_data["end_date"] = datetime.combine(
            medication_data["end_date"],
            time.min,
        )

    new_medication = Medication(
        user_id=current_user.id,
        **medication_data,
    )

    db.add(new_medication)
    db.commit()
    db.refresh(new_medication)

    return new_medication


@app.get(
    "/users/{user_id}/medications",
    response_model=list[MedicationResponse],
)
def get_user_medications(
    user_id: int,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_user_access(user_id, current_user)

    return (
        db.query(Medication)
        .filter(
            Medication.user_id == current_user.id,
            Medication.is_active.is_(True),
        )
        .order_by(Medication.created_at.desc())
        .all()
    )


@app.post(
    "/medications/{medication_id}/logs",
    response_model=MedicationLogResponse,
)
def record_medication_log(
    medication_id: int,
    log: MedicationLogCreate,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    medication = get_owned_medication(
        medication_id,
        current_user,
        db,
    )

    log_data = log.model_dump()

    if log_data["status"] == "taken":
        if log_data["taken_at"] is None:
            log_data["taken_at"] = datetime.utcnow()
    elif log_data["taken_at"] is not None:
        raise HTTPException(
            status_code=400,
            detail="taken_at is only valid when status is taken",
        )

    new_log = MedicationLog(
        medication_id=medication.id,
        **log_data,
    )

    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return new_log


@app.get(
    "/medications/{medication_id}/logs",
    response_model=list[MedicationLogResponse],
)
def get_medication_logs(
    medication_id: int,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    medication = get_owned_medication(
        medication_id,
        current_user,
        db,
    )

    return (
        db.query(MedicationLog)
        .filter(MedicationLog.medication_id == medication.id)
        .order_by(MedicationLog.scheduled_at.desc())
        .all()
    )


@app.get("/medications/{medication_id}/adherence")
def get_medication_adherence(
    medication_id: int,
    current_user: models.UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    medication = get_owned_medication(
        medication_id,
        current_user,
        db,
    )

    logs = (
        db.query(MedicationLog)
        .filter(MedicationLog.medication_id == medication.id)
        .all()
    )

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
        "medication_id": medication.id,
        "medication_name": medication.name,
        "total_logged": len(logs),
        "taken": taken,
        "missed": missed,
        "skipped": skipped,
        "adherence_percentage": percentage,
    }

@app.post(
    "/documents/upload",
    response_model=MedicalDocumentResponse,
    status_code=201
)
async def upload_medical_document(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result = await process_medical_pdf(file)

    document = MedicalDocument(
        user_id=current_user.id,
        filename=result["filename"],
        stored_path=result["stored_path"],
        content_type="application/pdf",
        file_size=result["file_size"],
        sha256_hash=result["sha256_hash"],
        extracted_text=result["extracted_text"]
    )

    try:
        db.add(document)
        db.commit()
        db.refresh(document)

        # Index document for RAG retrieval if text was extracted
        if document.extracted_text:
            try:
                from healthguard.rag.document_ingestion import ingest_user_document
                ingest_user_document(db, document.id, current_user.id)
                db.commit()
            except Exception as idx_err:
                logger.warning(
                    "Background RAG indexing failed for doc %s: %s",
                    document.id,
                    idx_err,
                )
                db.rollback()

        return document
    except Exception:
        db.rollback()
        import os
        if os.path.exists(result["stored_path"]):
            os.remove(result["stored_path"])
        raise HTTPException(status_code=500, detail="Could not save document")


@app.get("/documents", response_model=list[MedicalDocumentResponse])
def get_medical_documents(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return (
        db.query(MedicalDocument)
        .filter(MedicalDocument.user_id == current_user.id)
        .order_by(MedicalDocument.uploaded_at.desc())
        .all()
    )

@app.delete("/documents/{document_id}")
def delete_medical_document(
    document_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    document = (
        db.query(MedicalDocument)
        .filter(
            MedicalDocument.id == document_id,
            MedicalDocument.user_id == current_user.id
        )
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    stored_path = Path(document.stored_path).resolve()
    upload_root = Path("storage/medical_reports").resolve()

    # Prevent deletion outside the medical reports directory.
    if upload_root not in stored_path.parents:
        raise HTTPException(
            status_code=400,
            detail="Invalid document storage path"
        )

    # 1. Clean up associated ChromaDB embeddings & status
    try:
        from healthguard.rag.document_ingestion import delete_user_document_index
        delete_user_document_index(db, document_id, current_user.id)
    except Exception as cleanup_err:
        logger.warning(
            "Vector index cleanup failed for doc %s: %s",
            document_id,
            cleanup_err,
        )

    # 2. Check if any other record references this physical file
    other_references = (
        db.query(MedicalDocument)
        .filter(
            MedicalDocument.stored_path == document.stored_path,
            MedicalDocument.id != document_id,
        )
        .count()
    )

    db.delete(document)
    db.commit()

    # Only unlink if no other database record references this physical file
    if other_references == 0 and stored_path.is_file():
        stored_path.unlink()

    return {
        "message": "Medical document deleted successfully",
        "document_id": document_id
    }

@app.post("/metrics/import-csv")
async def import_health_csv(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only CSV files are allowed"
        )

    content = await file.read()

    file_hash = hashlib.sha256(content).hexdigest()

    existing_import = db.query(models.CSVImport).filter(
        models.CSVImport.user_id == current_user.id,
        models.CSVImport.sha256_hash == file_hash
    ).first()

    if existing_import:
        raise HTTPException(
            status_code=409,
            detail="This CSV file has already been imported"
        )

    result = parse_health_csv(content)
    imported = 0

    try:
        for record in result["records"]:
            original_value = record["value"]
            original_unit = record["unit"]

            normalized_value, normalized_unit = normalize_measurement(
                record["metric_type"],
                original_value,
                original_unit
            )

            metric = models.HealthMetric(
                user_id=current_user.id,
                metric_type=record["metric_type"],
                value=normalized_value,
                unit=normalized_unit,
                original_value=original_value,
                original_unit=original_unit,
                source="imported",
                context=record["context"],
                notes=record["notes"],
                measurement_group_id=record["measurement_group_id"],
                recorded_at=record["recorded_at"]
            )

            db.add(metric)
            imported += 1

        import_record = models.CSVImport(
            user_id=current_user.id,
            filename=file.filename,
            sha256_hash=file_hash,
            imported_count=imported
        )

        db.add(import_record)
        db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This CSV file has already been imported"
        )

    except Exception:
        db.rollback()
        import logging
        logging.exception("CSV import failed")

        raise HTTPException(
            status_code=500,
            detail="CSV import failed"
        )

    return {
        "message": "CSV import completed",
        "imported_count": imported,
        "failed_count": len(result["errors"]),
        "import_hash": file_hash,
        "errors": result["errors"]
    }

# ---------------------------------------------------------------------------
# Experimental ML screening
# ---------------------------------------------------------------------------

@app.post(
    "/ml/diabetes/predict",
    response_model=DiabetesPredictionResponse,
    tags=["Machine Learning"],
)
def diabetes_prediction_endpoint(
    payload: DiabetesPredictionRequest,
    current_user: models.UserProfile = Depends(get_current_user),
):
    """Experimental diabetes screening; not a clinical diagnosis."""
    try:
        return predict_diabetes(payload.model_dump())
    except (FileNotFoundError, ValueError):
        logger.exception("Diabetes screening model unavailable or invalid")
        raise HTTPException(
            status_code=503,
            detail="Diabetes screening service is unavailable",
        )
    except Exception:
        logger.exception("Unexpected diabetes screening failure")
        raise HTTPException(
            status_code=503,
            detail="Diabetes screening service is unavailable",
        )

@app.post(
    "/ml/diabetes/predict-v3",
    response_model=DiabetesPredictionV3Response,
    tags=["Machine Learning"],
)
def diabetes_prediction_v3(
    payload: DiabetesPredictionRequest,
    current_user=Depends(get_current_user),
):
    """Authenticated experimental diabetes screening (v3)."""

    try:
        return predict_diabetes_v3(
            payload.model_dump()
        )

    except ValueError as exc:
        # Input validation errors must be distinguished
        # from model configuration failures.
        message = str(exc)

        input_errors = (
            "Missing features",
            "Unexpected features",
            "must be",
            "cannot be negative",
            "must be greater than zero",
        )

        if any(error in message for error in input_errors):
            raise HTTPException(
                status_code=422,
                detail=message,
            ) from exc

        raise HTTPException(
            status_code=503,
            detail="Diabetes screening service is unavailable",
        ) from exc

    except (FileNotFoundError, OSError, KeyError, TypeError):
        raise HTTPException(
            status_code=503,
            detail="Diabetes screening service is unavailable",
        )
