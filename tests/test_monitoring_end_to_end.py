from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from healthguard.main import app
from healthguard.core.dependencies import get_current_user
from healthguard.database.base import Base
from healthguard.database.models import (
    UserProfile,
    HealthMetric,
    MonitoringEvent,
)
from healthguard.database.session import get_db
from healthguard.agents.monitoring_trigger import (
    trigger_monitoring_for_metric,
)


# ============================================================
# ISOLATED TEST ENVIRONMENT
# ============================================================

@pytest.fixture
def environment():

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
    )

    with SessionLocal() as db:
        user = UserProfile(
            full_name="Monitoring Integration Test",
            email="monitoring_e2e@example.com",
            password_hash="test_hash",
        )

        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    def override_db():
        with SessionLocal() as db:
            yield db

    def override_user():
        with SessionLocal() as db:
            user = db.get(UserProfile, user_id)
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "session_factory": SessionLocal,
                "user_id": user_id,
            }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# ============================================================
# TEST DATA HELPER
# ============================================================

def insert_readings(environment, values):

    session_factory = environment["session_factory"]
    user_id = environment["user_id"]

    ids = []

    with session_factory() as db:

        start = datetime.utcnow() - timedelta(days=len(values))

        for index, value in enumerate(values):

            metric = HealthMetric(
                user_id=user_id,
                metric_type="heart_rate",
                value=value,
                unit="bpm",
                recorded_at=start + timedelta(days=index),
                source="manual",
            )

            db.add(metric)
            db.flush()
            ids.append(metric.id)

        db.commit()

    return ids


# ============================================================
# TEST 1 — COMPLETE MONITORING PIPELINE
# ============================================================

def test_complete_monitoring_pipeline(environment):

    # Historical baseline + recent readings.
    values = [
        70, 71, 69, 72, 70,
        95, 98, 100,
    ]

    ids = insert_readings(environment, values)

    with environment["session_factory"]() as db:

        result = trigger_monitoring_for_metric(
            db=db,
            user_id=environment["user_id"],
            metric_id=ids[-1],
        )

        db.commit()

    assert result is not None

    with environment["session_factory"]() as db:

        events = db.scalars(
            select(MonitoringEvent).where(
                MonitoringEvent.user_id == environment["user_id"]
            )
        ).all()

        assert len(events) >= 1

        monitoring_event = events[-1]

        assert monitoring_event.metric_type == "heart_rate"
        assert monitoring_event.unit == "bpm"

        assert monitoring_event.event_type in {
            "statistical_deviation",
            "insufficient_baseline_variability",
            "routine_monitoring",
        }


# ============================================================
# TEST 2 — EVENT VISIBLE THROUGH API
# ============================================================

def test_event_visible_through_api(environment):

    ids = insert_readings(
        environment,
        [70, 71, 69, 72, 70, 95, 98, 100],
    )

    with environment["session_factory"]() as db:
        trigger_monitoring_for_metric(
            db=db,
            user_id=environment["user_id"],
            metric_id=ids[-1],
        )
        db.commit()

    response = environment["client"].get(
        f"/users/{environment['user_id']}/monitoring/events"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] >= 1
    assert len(data["events"]) >= 1


# ============================================================
# TEST 3 — EVENT SUMMARY MATCHES DATABASE
# ============================================================

def test_event_summary_matches_database(environment):

    ids = insert_readings(
        environment,
        [70, 71, 69, 72, 70, 95, 98, 100],
    )

    with environment["session_factory"]() as db:
        trigger_monitoring_for_metric(
            db=db,
            user_id=environment["user_id"],
            metric_id=ids[-1],
        )
        db.commit()

    response = environment["client"].get(
        f"/users/{environment['user_id']}/monitoring/events/summary"
    )

    assert response.status_code == 200

    summary = response.json()

    with environment["session_factory"]() as db:
        database_count = len(
            db.scalars(
                select(MonitoringEvent).where(
                    MonitoringEvent.user_id == environment["user_id"]
                )
            ).all()
        )

    assert summary["total_events"] == database_count


# ============================================================
# TEST 4 — EVENT ACKNOWLEDGMENT PERSISTS
# ============================================================

def test_event_acknowledgment_persists(environment):

    ids = insert_readings(
        environment,
        [70, 71, 69, 72, 70, 95, 98, 100],
    )

    with environment["session_factory"]() as db:
        trigger_monitoring_for_metric(
            db=db,
            user_id=environment["user_id"],
            metric_id=ids[-1],
        )
        db.commit()

        monitoring_event = db.scalar(
            select(MonitoringEvent).where(
                MonitoringEvent.user_id == environment["user_id"]
            )
        )

        assert monitoring_event is not None
        event_id = monitoring_event.id

    response = environment["client"].patch(
        f"/users/{environment['user_id']}/monitoring/events/"
        f"{event_id}/acknowledge"
    )

    assert response.status_code == 200

    with environment["session_factory"]() as db:
        persisted = db.get(MonitoringEvent, event_id)

        assert persisted.is_acknowledged is True
        assert persisted.acknowledged_at is not None


# ============================================================
# TEST 5 — DEDUPLICATION PREVENTS REPEATED PENDING EVENTS
# ============================================================

def test_pending_event_deduplication(environment):

    ids = insert_readings(
        environment,
        [70, 71, 69, 72, 70, 95, 98, 100],
    )

    with environment["session_factory"]() as db:

        trigger_monitoring_for_metric(
            db=db,
            user_id=environment["user_id"],
            metric_id=ids[-1],
        )

        db.commit()

        first_count = len(
            db.scalars(
                select(MonitoringEvent).where(
                    MonitoringEvent.user_id == environment["user_id"]
                )
            ).all()
        )

        trigger_monitoring_for_metric(
            db=db,
            user_id=environment["user_id"],
            metric_id=ids[-1],
        )

        db.commit()

        second_count = len(
            db.scalars(
                select(MonitoringEvent).where(
                    MonitoringEvent.user_id == environment["user_id"]
                )
            ).all()
        )

    assert first_count >= 1
    assert second_count == first_count