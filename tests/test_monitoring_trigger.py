from datetime import datetime, timedelta

import pytest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from healthguard.database.base import Base
from healthguard.database.models import (
    UserProfile,
    HealthMetric,
    MonitoringEvent,
)

from healthguard.agents.monitoring_trigger import (
    trigger_monitoring_for_metric,
    MonitoringTriggerError,
)


@pytest.fixture
def db():
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

    with Session(engine) as session:
        yield session

    engine.dispose()


@pytest.fixture
def users(db):
    first = UserProfile(full_name="Monitoring User One")
    second = UserProfile(full_name="Monitoring User Two")

    db.add_all([first, second])
    db.commit()

    return first.id, second.id


def add_readings(
    db,
    user_id,
    values,
    metric_type="blood_glucose",
    unit="mg/dL",
):
    start = datetime(2026, 11, 1, 10, 0)

    records = []

    for index, value in enumerate(values):
        metric = HealthMetric(
            user_id=user_id,
            metric_type=metric_type,
            value=value,
            unit=unit,
            recorded_at=start + timedelta(hours=index),
        )

        db.add(metric)
        records.append(metric)

    db.commit()

    return records


def test_insufficient_readings_skips(db, users):
    user_id, _ = users

    records = add_readings(
        db,
        user_id,
        [100, 102, 101],
    )

    result = trigger_monitoring_for_metric(
        db,
        user_id,
        records[-1].id,
    )

    assert result["trigger_status"] == "skipped"
    assert result["reason"] == "insufficient_readings"
    assert result["event_id"] is None


def test_statistical_deviation_creates_event(db, users):
    user_id, _ = users

    records = add_readings(
        db,
        user_id,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    result = trigger_monitoring_for_metric(
        db,
        user_id,
        records[-1].id,
    )

    db.commit()

    assert result["trigger_status"] == "event_created"
    assert result["event_type"] == "statistical_deviation"
    assert result["notification_status"] == "pending"

    events = db.query(MonitoringEvent).all()

    assert len(events) == 1


def test_repeated_pending_event_is_suppressed(db, users):
    user_id, _ = users

    records = add_readings(
        db,
        user_id,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    first = trigger_monitoring_for_metric(
        db,
        user_id,
        records[-1].id,
    )

    db.commit()

    second = trigger_monitoring_for_metric(
        db,
        user_id,
        records[-1].id,
    )

    assert first["trigger_status"] == "event_created"
    assert second["trigger_status"] == "suppressed"
    assert second["reason"] == "pending_event_exists"

    assert db.query(MonitoringEvent).count() == 1


def test_cross_user_metric_access_rejected(db, users):
    first_user, second_user = users

    records = add_readings(
        db,
        first_user,
        [100, 102, 101],
    )

    with pytest.raises(MonitoringTriggerError):
        trigger_monitoring_for_metric(
            db,
            second_user,
            records[-1].id,
        )


def test_missing_metric_rejected(db, users):
    user_id, _ = users

    with pytest.raises(MonitoringTriggerError):
        trigger_monitoring_for_metric(
            db,
            user_id,
            999999,
        )


def test_invalid_user_id_rejected(db):
    with pytest.raises(MonitoringTriggerError):
        trigger_monitoring_for_metric(
            db,
            0,
            1,
        )


def test_invalid_metric_id_rejected(db, users):
    user_id, _ = users

    with pytest.raises(MonitoringTriggerError):
        trigger_monitoring_for_metric(
            db,
            user_id,
            0,
        )


def test_user_events_remain_isolated(db, users):
    first_user, second_user = users

    first_records = add_readings(
        db,
        first_user,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    second_records = add_readings(
        db,
        second_user,
        [90, 92, 91, 93, 94, 105, 110, 115],
    )

    trigger_monitoring_for_metric(
        db,
        first_user,
        first_records[-1].id,
    )

    trigger_monitoring_for_metric(
        db,
        second_user,
        second_records[-1].id,
    )

    db.commit()

    events = db.query(MonitoringEvent).all()

    assert len(events) == 2
    assert {event.user_id for event in events} == {
        first_user,
        second_user,
    }


def test_different_units_evaluated_independently(db, users):
    user_id, _ = users

    first = add_readings(
        db,
        user_id,
        [100, 102, 101, 103, 104, 115, 120, 125],
        unit="mg/dL",
    )

    second = add_readings(
        db,
        user_id,
        [5.0, 5.2, 5.1, 5.3, 5.4, 6.0, 6.2, 6.5],
        unit="mmol/L",
    )

    first_result = trigger_monitoring_for_metric(
        db,
        user_id,
        first[-1].id,
    )

    second_result = trigger_monitoring_for_metric(
        db,
        user_id,
        second[-1].id,
    )

    db.commit()

    assert first_result["event_id"] != second_result["event_id"]
    assert db.query(MonitoringEvent).count() == 2


def test_trigger_does_not_commit_automatically(db, users):
    user_id, _ = users

    records = add_readings(
        db,
        user_id,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    trigger_monitoring_for_metric(
        db,
        user_id,
        records[-1].id,
    )

    db.rollback()

    assert db.query(MonitoringEvent).count() == 0

    assert db.query(HealthMetric).count() == 8


def test_routine_monitoring_event(db, users):
    user_id, _ = users

    records = add_readings(
        db,
        user_id,
        [100, 102, 101, 103, 104, 102, 103, 104],
    )

    result = trigger_monitoring_for_metric(
        db,
        user_id,
        records[-1].id,
    )

    db.commit()

    assert result["event_type"] == "routine_monitoring"
    assert result["notification_status"] == "pending"


def test_trigger_result_has_no_raw_measurements(db, users):
    user_id, _ = users

    records = add_readings(
        db,
        user_id,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    result = trigger_monitoring_for_metric(
        db,
        user_id,
        records[-1].id,
    )

    assert "readings" not in result
    assert "longitudinal_analysis" not in result