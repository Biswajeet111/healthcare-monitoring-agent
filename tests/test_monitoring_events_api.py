from datetime import datetime, timedelta

import pytest

from fastapi.testclient import TestClient

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from healthguard.main import app
from healthguard.core.dependencies import get_current_user
from healthguard.database.base import Base
from healthguard.database.models import (
    UserProfile,
    MonitoringEvent,
)
from healthguard.database.session import get_db


# ============================================================
# ISOLATED TEST DATABASE
# ============================================================

@pytest.fixture
def test_environment():
    """
    Create an isolated in-memory SQLite database.

    Tests must not modify the real HealthGuard database.
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    db = TestingSessionLocal()

    user1 = UserProfile(
        full_name="Test User One",
        email="monitoring_user1@example.com",
        password_hash="test_hash",
    )

    user2 = UserProfile(
        full_name="Test User Two",
        email="monitoring_user2@example.com",
        password_hash="test_hash",
    )

    db.add_all([user1, user2])
    db.commit()

    db.refresh(user1)
    db.refresh(user2)

    user1_id = user1.id
    user2_id = user2.id

    db.close()

    def override_get_db():
        test_db = TestingSessionLocal()

        try:
            yield test_db
        finally:
            test_db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "session_factory": TestingSessionLocal,
                "user1_id": user1_id,
                "user2_id": user2_id,
            }

    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def authenticate_as(environment, user_id):
    """
    Override authentication only for tests requiring
    an authenticated user.

    The unauthenticated test uses real JWT validation.
    """

    session_factory = environment["session_factory"]

    def override_current_user():
        with session_factory() as db:
            user = db.get(UserProfile, user_id)

            if user is None:
                raise RuntimeError("Test user not found")

            db.expunge(user)

            return user

    app.dependency_overrides[get_current_user] = override_current_user


def create_event(
    environment,
    user_id,
    fingerprint_character="a",
    event_type="statistical_deviation",
    event_level="review",
    notification_status="pending",
    acknowledged=False,
    created_at=None,
):
    session_factory = environment["session_factory"]

    with session_factory() as db:

        monitoring_event = MonitoringEvent(
            user_id=user_id,
            fingerprint=fingerprint_character * 64,
            metric_type="heart_rate",
            unit="bpm",
            event_type=event_type,
            event_level=event_level,
            monitoring_priority="review_recommended",
            statistical_status="statistical_deviation_detected",
            message="Statistical monitoring observation.",
            notification_status=notification_status,
            is_acknowledged=acknowledged,
            acknowledged_at=(
                datetime.utcnow()
                if acknowledged
                else None
            ),
            created_at=created_at or datetime.utcnow(),
        )

        db.add(monitoring_event)
        db.commit()
        db.refresh(monitoring_event)

        return monitoring_event.id


# ============================================================
# TEST 1 — AUTHENTICATION REQUIRED
# ============================================================

def test_monitoring_events_requires_authentication(test_environment):

    client = test_environment["client"]
    user_id = test_environment["user1_id"]

    response = client.get(
        f"/users/{user_id}/monitoring/events"
    )

    assert response.status_code == 401


# ============================================================
# TEST 2 — USER CAN LIST OWN EVENTS
# ============================================================

def test_user_can_list_own_events(test_environment):

    user_id = test_environment["user1_id"]

    create_event(test_environment, user_id)

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].get(
        f"/users/{user_id}/monitoring/events"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["user_id"] == user_id
    assert data["total"] == 1
    assert len(data["events"]) == 1

    assert data["events"][0]["metric_type"] == "heart_rate"


# ============================================================
# TEST 3 — CROSS-USER ACCESS BLOCKED
# ============================================================

def test_cross_user_event_access_blocked(test_environment):

    user1_id = test_environment["user1_id"]
    user2_id = test_environment["user2_id"]

    create_event(
        test_environment,
        user2_id,
        fingerprint_character="b",
    )

    authenticate_as(test_environment, user1_id)

    response = test_environment["client"].get(
        f"/users/{user2_id}/monitoring/events"
    )

    assert response.status_code == 403


# ============================================================
# TEST 4 — PAGINATION
# ============================================================

def test_monitoring_event_pagination(test_environment):

    user_id = test_environment["user1_id"]

    for index in range(5):

        create_event(
            test_environment,
            user_id,
            fingerprint_character=str(index),
            created_at=(
                datetime.utcnow()
                + timedelta(minutes=index)
            ),
        )

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].get(
        f"/users/{user_id}/monitoring/events",
        params={
            "limit": 2,
            "offset": 1,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 5
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert len(data["events"]) == 2


# ============================================================
# TEST 5 — INVALID PAGINATION REJECTED
# ============================================================

def test_invalid_pagination_rejected(test_environment):

    user_id = test_environment["user1_id"]

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].get(
        f"/users/{user_id}/monitoring/events",
        params={"limit": 1000},
    )

    assert response.status_code == 422


# ============================================================
# TEST 6 — EVENT SUMMARY
# ============================================================

def test_monitoring_event_summary(test_environment):

    user_id = test_environment["user1_id"]

    create_event(
        test_environment,
        user_id,
        fingerprint_character="a",
        notification_status="pending",
    )

    create_event(
        test_environment,
        user_id,
        fingerprint_character="b",
        notification_status="delivered",
        acknowledged=True,
    )

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].get(
        f"/users/{user_id}/monitoring/events/summary"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_events"] == 2
    assert data["acknowledged"] == 1
    assert data["unacknowledged"] == 1

    assert data["by_notification_status"]["pending"] == 1
    assert data["by_notification_status"]["delivered"] == 1


# ============================================================
# TEST 7 — RETRIEVE SINGLE EVENT
# ============================================================

def test_get_single_monitoring_event(test_environment):

    user_id = test_environment["user1_id"]

    event_id = create_event(
        test_environment,
        user_id,
    )

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].get(
        f"/users/{user_id}/monitoring/events/{event_id}"
    )

    assert response.status_code == 200

    assert response.json()["id"] == event_id


# ============================================================
# TEST 8 — UNKNOWN EVENT RETURNS 404
# ============================================================

def test_unknown_event_returns_404(test_environment):

    user_id = test_environment["user1_id"]

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].get(
        f"/users/{user_id}/monitoring/events/999999"
    )

    assert response.status_code == 404


# ============================================================
# TEST 9 — ACKNOWLEDGE EVENT
# ============================================================

def test_acknowledge_monitoring_event(test_environment):

    user_id = test_environment["user1_id"]

    event_id = create_event(
        test_environment,
        user_id,
    )

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].patch(
        f"/users/{user_id}/monitoring/events/{event_id}/acknowledge"
    )

    assert response.status_code == 200

    event_data = response.json()["event"]

    assert event_data["is_acknowledged"] is True
    assert event_data["acknowledged_at"] is not None


# ============================================================
# TEST 10 — ACKNOWLEDGMENT IS IDEMPOTENT
# ============================================================

def test_acknowledgment_is_idempotent(test_environment):

    user_id = test_environment["user1_id"]

    event_id = create_event(
        test_environment,
        user_id,
    )

    authenticate_as(test_environment, user_id)

    url = (
        f"/users/{user_id}/monitoring/events/"
        f"{event_id}/acknowledge"
    )

    first_response = test_environment["client"].patch(url)

    second_response = test_environment["client"].patch(url)

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_timestamp = (
        first_response.json()["event"]["acknowledged_at"]
    )

    second_timestamp = (
        second_response.json()["event"]["acknowledged_at"]
    )

    assert first_timestamp == second_timestamp


# ============================================================
# TEST 11 — ACKNOWLEDGMENT PRESERVES NOTIFICATION STATUS
# ============================================================

def test_acknowledgment_preserves_notification_status(
    test_environment,
):

    user_id = test_environment["user1_id"]

    event_id = create_event(
        test_environment,
        user_id,
        notification_status="delivered",
    )

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].patch(
        f"/users/{user_id}/monitoring/events/{event_id}/acknowledge"
    )

    assert response.status_code == 200

    assert (
        response.json()["event"]["notification_status"]
        == "delivered"
    )


# ============================================================
# TEST 12 — CROSS-USER ACKNOWLEDGMENT BLOCKED
# ============================================================

def test_cross_user_acknowledgment_blocked(
    test_environment,
):

    user1_id = test_environment["user1_id"]
    user2_id = test_environment["user2_id"]

    event_id = create_event(
        test_environment,
        user2_id,
        fingerprint_character="z",
    )

    authenticate_as(test_environment, user1_id)

    response = test_environment["client"].patch(
        f"/users/{user2_id}/monitoring/events/{event_id}/acknowledge"
    )

    assert response.status_code == 403


# ============================================================
# TEST 13 — EVENT EVIDENCE IS NOT EXPOSED
# ============================================================

def test_event_evidence_not_exposed(test_environment):

    user_id = test_environment["user1_id"]

    create_event(
        test_environment,
        user_id,
    )

    authenticate_as(test_environment, user_id)

    response = test_environment["client"].get(
        f"/users/{user_id}/monitoring/events"
    )

    assert response.status_code == 200

    event_data = response.json()["events"][0]

    assert "evidence_json" not in event_data
    assert "fingerprint" not in event_data


# ============================================================
# TEST 14 — SUMMARY CROSS-USER ACCESS BLOCKED
# ============================================================

def test_cross_user_summary_blocked(test_environment):

    user1_id = test_environment["user1_id"]
    user2_id = test_environment["user2_id"]

    authenticate_as(test_environment, user1_id)

    response = test_environment["client"].get(
        f"/users/{user2_id}/monitoring/events/summary"
    )

    assert response.status_code == 403


# ============================================================
# TEST 15 — SINGLE EVENT CROSS-USER ACCESS BLOCKED
# ============================================================

def test_cross_user_single_event_blocked(test_environment):

    user1_id = test_environment["user1_id"]
    user2_id = test_environment["user2_id"]

    event_id = create_event(
        test_environment,
        user2_id,
        fingerprint_character="c",
    )

    authenticate_as(test_environment, user1_id)

    response = test_environment["client"].get(
        f"/users/{user2_id}/monitoring/events/{event_id}"
    )

    assert response.status_code == 403