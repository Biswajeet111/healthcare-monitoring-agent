import uuid

import pytest

from datetime import datetime, timezone

from sqlalchemy import select

from healthguard.database.models import MonitoringEvent
from healthguard.database.session import get_db
from healthguard.main import app


@pytest.fixture
def notification_user(client):
    """Register and authenticate a user through real HTTP endpoints."""

    email = f"notification_{uuid.uuid4().hex}@example.com"
    password = "TestPassword@123"

    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Notification Test User",
            "email": email,
            "password": password,
        },
    )

    assert registration.status_code in (200, 201), registration.text

    login = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login.status_code == 200, login.text

    return {
        "user_id": registration.json()["id"],
        "headers": {
            "Authorization": f"Bearer {login.json()['access_token']}"
        },
    }


def get_test_db():
    """Use the existing overridden database dependency."""

    dependency = app.dependency_overrides[get_db]
    generator = dependency()

    db = next(generator)

    return db, generator


def create_test_notification(
    user_id,
    *,
    event_type="statistical_deviation",
    notification_status="delivered",
    acknowledged=False,
):
    """Insert a monitoring event into the isolated pytest database."""

    db, generator = get_test_db()

    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        event_levels = {
            "statistical_deviation": "review",
            "insufficient_baseline_variability": "informational",
            "routine_monitoring": "routine",
        }

        priorities = {
            "statistical_deviation": "review_recommended",
            "insufficient_baseline_variability": "more_data_needed",
            "routine_monitoring": "routine_tracking",
        }

        statuses = {
            "statistical_deviation": "statistical_deviation_detected",
            "insufficient_baseline_variability": "insufficient_baseline_variability",
            "routine_monitoring": "within_configured_threshold",
        }

        event = MonitoringEvent(
            user_id=user_id,
            fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
            metric_type="heart_rate",
            unit="bpm",
            event_type=event_type,
            event_level=event_levels[event_type],
            monitoring_priority=priorities[event_type],
            statistical_status=statuses[event_type],
            message="Statistical monitoring observation.",
            notification_status=notification_status,
            created_at=now,
            notified_at=(
                now if notification_status == "delivered" else None
            ),
            is_acknowledged=acknowledged,
            acknowledged_at=now if acknowledged else None,
        )

        db.add(event)
        db.commit()
        db.refresh(event)

        return event.id

    finally:
        generator.close()


def test_notifications_require_authentication(client, notification_user):

    response = client.get(
        f"/users/{notification_user['user_id']}/notifications"
    )

    assert response.status_code == 401


def test_empty_notification_feed(client, notification_user):

    response = client.get(
        f"/users/{notification_user['user_id']}/notifications",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 0
    assert data["notifications"] == []


def test_delivered_notification_visible(client, notification_user):

    event_id = create_test_notification(
        notification_user["user_id"]
    )

    response = client.get(
        f"/users/{notification_user['user_id']}/notifications",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 1
    assert data["notifications"][0]["id"] == event_id


def test_pending_and_suppressed_notifications_hidden(
    client,
    notification_user,
):

    user_id = notification_user["user_id"]

    create_test_notification(
        user_id,
        notification_status="pending",
    )

    create_test_notification(
        user_id,
        notification_status="suppressed",
    )

    create_test_notification(
        user_id,
        notification_status="failed",
    )

    response = client.get(
        f"/users/{user_id}/notifications",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_routine_monitoring_excluded(client, notification_user):

    create_test_notification(
        notification_user["user_id"],
        event_type="routine_monitoring",
    )

    response = client.get(
        f"/users/{notification_user['user_id']}/notifications",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_unread_filter(client, notification_user):

    user_id = notification_user["user_id"]

    create_test_notification(user_id, acknowledged=False)
    create_test_notification(user_id, acknowledged=True)

    response = client.get(
        f"/users/{user_id}/notifications?unread_only=true",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 1
    assert len(data["notifications"]) == 1
    assert data["notifications"][0]["is_acknowledged"] is False


def test_notification_summary(client, notification_user):

    user_id = notification_user["user_id"]

    create_test_notification(user_id, acknowledged=False)
    create_test_notification(user_id, acknowledged=True)

    response = client.get(
        f"/users/{user_id}/notifications/summary",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_notifications"] == 2
    assert data["unread"] == 1
    assert data["acknowledged"] == 1


def test_cross_user_notification_access_denied(
    client,
    notification_user,
):

    other_email = f"other_{uuid.uuid4().hex}@example.com"

    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Other Notification User",
            "email": other_email,
            "password": "TestPassword@123",
        },
    )

    assert registration.status_code in (200, 201)

    other_user_id = registration.json()["id"]

    response = client.get(
        f"/users/{other_user_id}/notifications",
        headers=notification_user["headers"],
    )

    assert response.status_code == 403


def test_notification_pagination(client, notification_user):

    user_id = notification_user["user_id"]

    for _ in range(5):
        create_test_notification(user_id)

    response = client.get(
        f"/users/{user_id}/notifications?limit=2&offset=1",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 5
    assert len(data["notifications"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 1


def test_reading_does_not_acknowledge(
    client,
    notification_user,
):

    user_id = notification_user["user_id"]

    event_id = create_test_notification(user_id)

    response = client.get(
        f"/users/{user_id}/notifications",
        headers=notification_user["headers"],
    )

    assert response.status_code == 200

    db, generator = get_test_db()

    try:
        event = db.scalar(
            select(MonitoringEvent).where(
                MonitoringEvent.id == event_id
            )
        )

        assert event is not None
        assert event.is_acknowledged is False

    finally:
        generator.close()