from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from healthguard.database.base import Base
from healthguard.database.models import UserProfile

from healthguard.database.monitoring_event_repository import (
    create_monitoring_event,
    get_monitoring_events,
    get_notification_history,
    mark_notification_delivered,
    mark_notification_failed,
    MonitoringEventRepositoryError,
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
    first = UserProfile(full_name="Test User One")
    second = UserProfile(full_name="Test User Two")

    db.add_all([first, second])
    db.commit()

    return first.id, second.id


def classified_event(
    metric_type="blood_glucose",
    unit="mg/dL",
):
    return {
        "event_type": "statistical_deviation",
        "event_level": "review",
        "metric_type": metric_type,
        "unit": unit,
        "monitoring_priority": "review_recommended",
        "statistical_status": "statistical_deviation_detected",
        "classification_status": "completed",
        "message": "Statistical deviation detected.",
        "evidence": {
            "baseline_mean": 100.0,
            "recent_mean": 125.0,
            "latest_value": 130.0,
            "z_score": 3.2,
            "configured_threshold": 2.0,
        },
    }


def test_create_monitoring_event(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    db.commit()

    assert result.id is not None
    assert result.user_id == user_id
    assert result.notification_status == "pending"
    assert len(result.fingerprint) == 64


def test_event_persists_after_commit(db, users):
    user_id, _ = users

    created = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    event_id = created.id

    db.commit()
    db.expunge_all()

    records = get_monitoring_events(db, user_id)

    assert len(records) == 1
    assert records[0].id == event_id


def test_user_isolation(db, users):
    first_user, second_user = users

    create_monitoring_event(
        db,
        first_user,
        classified_event(),
    )

    db.commit()

    assert len(
        get_monitoring_events(db, first_user)
    ) == 1

    assert get_monitoring_events(db, second_user) == []


def test_missing_user_rejected(db):
    with pytest.raises(MonitoringEventRepositoryError):
        create_monitoring_event(
            db,
            999999,
            classified_event(),
        )


def test_invalid_classification_rejected(db, users):
    user_id, _ = users

    payload = classified_event()
    payload["classification_status"] = "failed"

    with pytest.raises(MonitoringEventRepositoryError):
        create_monitoring_event(
            db,
            user_id,
            payload,
        )


def test_suppressed_event_has_no_delivery_timestamp(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
        notification_status="suppressed",
    )

    db.commit()

    assert result.notification_status == "suppressed"
    assert result.notified_at is None


def test_mark_notification_delivered(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    delivered_at = datetime(
        2026, 11, 10, 12, 0,
        tzinfo=timezone.utc,
    )

    mark_notification_delivered(
        db,
        result.id,
        user_id,
        delivered_at=delivered_at,
    )

    db.commit()

    assert result.notification_status == "delivered"
    assert result.notified_at == delivered_at.replace(
        tzinfo=None
    )


def test_delivered_event_in_notification_history(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    fingerprint = result.fingerprint

    mark_notification_delivered(
        db,
        result.id,
        user_id,
        delivered_at=datetime.now(timezone.utc),
    )

    db.commit()

    history = get_notification_history(
        db,
        user_id,
        fingerprint,
    )

    assert len(history) == 1
    assert history[0]["user_id"] == user_id
    assert history[0]["fingerprint"] == fingerprint


def test_pending_event_not_in_notification_history(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    db.commit()

    history = get_notification_history(
        db,
        user_id,
        result.fingerprint,
    )

    assert history == []


def test_suppressed_event_not_in_notification_history(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
        notification_status="suppressed",
    )

    db.commit()

    history = get_notification_history(
        db,
        user_id,
        result.fingerprint,
    )

    assert history == []


def test_mark_notification_failed(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    mark_notification_failed(
        db,
        result.id,
        user_id,
    )

    db.commit()

    assert result.notification_status == "failed"
    assert result.notified_at is None


def test_failed_event_not_in_notification_history(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    mark_notification_failed(
        db,
        result.id,
        user_id,
    )

    db.commit()

    assert get_notification_history(
        db,
        user_id,
        result.fingerprint,
    ) == []


def test_cannot_deliver_suppressed_event(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
        notification_status="suppressed",
    )

    with pytest.raises(MonitoringEventRepositoryError):
        mark_notification_delivered(
            db,
            result.id,
            user_id,
        )


def test_cannot_deliver_twice(db, users):
    user_id, _ = users

    result = create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    mark_notification_delivered(
        db,
        result.id,
        user_id,
    )

    with pytest.raises(MonitoringEventRepositoryError):
        mark_notification_delivered(
            db,
            result.id,
            user_id,
        )


def test_cross_user_delivery_rejected(db, users):
    first_user, second_user = users

    result = create_monitoring_event(
        db,
        first_user,
        classified_event(),
    )

    with pytest.raises(MonitoringEventRepositoryError):
        mark_notification_delivered(
            db,
            result.id,
            second_user,
        )


def test_cross_user_history_isolation(db, users):
    first_user, second_user = users

    result = create_monitoring_event(
        db,
        first_user,
        classified_event(),
    )

    mark_notification_delivered(
        db,
        result.id,
        first_user,
    )

    db.commit()

    assert get_notification_history(
        db,
        second_user,
        result.fingerprint,
    ) == []


def test_invalid_limit_rejected(db, users):
    user_id, _ = users

    with pytest.raises(MonitoringEventRepositoryError):
        get_monitoring_events(
            db,
            user_id,
            limit=0,
        )


def test_invalid_evidence_rejected(db, users):
    user_id, _ = users

    payload = classified_event()
    payload["evidence"]["z_score"] = float("nan")

    with pytest.raises(MonitoringEventRepositoryError):
        create_monitoring_event(
            db,
            user_id,
            payload,
        )


def test_multiple_events_ordered_newest_first(db, users):
    user_id, _ = users

    first = create_monitoring_event(
        db,
        user_id,
        classified_event(metric_type="heart_rate"),
    )

    second = create_monitoring_event(
        db,
        user_id,
        classified_event(metric_type="blood_glucose"),
    )

    first.created_at = datetime(
        2026, 11, 10, 10, 0
    )

    second.created_at = datetime(
        2026, 11, 10, 11, 0
    )

    db.commit()

    results = get_monitoring_events(db, user_id)

    assert results[0].id == second.id
    assert results[1].id == first.id


def test_repository_does_not_commit_automatically(db, users):
    user_id, _ = users

    create_monitoring_event(
        db,
        user_id,
        classified_event(),
    )

    assert db.in_transaction()

    db.rollback()

    assert get_monitoring_events(db, user_id) == []