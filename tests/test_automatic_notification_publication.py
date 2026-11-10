from unittest.mock import patch
from uuid import uuid4
import pytest
from sqlalchemy import select

from healthguard.database.models import MonitoringEvent
from healthguard.database.session import get_db
from healthguard.main import app
@pytest.fixture
def authenticated_user(client):
    """
    Register and authenticate a fresh user for each test.

    Uses the existing FastAPI test client and isolated
    database provided by tests/conftest.py.
    """

    email = f"notification_{uuid4().hex}@example.com"
    password = "TestPassword@123"

    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Notification Integration Test User",
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

    token = login.json()["access_token"]

    return {
        "user_id": registration.json()["id"],
        "headers": {
            "Authorization": f"Bearer {token}",
        },
    }

def get_test_session():
    dependency = app.dependency_overrides[get_db]
    generator = dependency()
    db = next(generator)
    return db, generator


def create_metric(client, user, value):
    response = client.post(
        f"/metrics?user_id={user['user_id']}",
        headers=user["headers"],
        json={
            "metric_type": "heart_rate",
            "value": value,
            "unit": "bpm",
            "source": "manual",
            "notes": "Automatic notification publication test",
        },
    )

    assert response.status_code in (200, 201), response.text
    return response.json()


def create_history(client, user):
    for value in [70, 71, 69, 72, 70, 95, 98, 100]:
        create_metric(client, user, value)


def test_automatic_publication_through_http(
    client,
    authenticated_user,
):
    create_history(client, authenticated_user)

    user_id = authenticated_user["user_id"]
    headers = authenticated_user["headers"]

    events_response = client.get(
        f"/users/{user_id}/monitoring/events",
        headers=headers,
    )

    assert events_response.status_code == 200

    events = events_response.json()["events"]

    eligible_events = [
        event
        for event in events
        if event["event_type"] in {
            "statistical_deviation",
            "insufficient_baseline_variability",
        }
    ]

    assert eligible_events, "Expected at least one eligible event."

    assert any(
        event["notification_status"] == "delivered"
        and event["notified_at"] is not None
        for event in eligible_events
    )

    feed_response = client.get(
        f"/users/{user_id}/notifications",
        headers=headers,
    )

    assert feed_response.status_code == 200

    notifications = feed_response.json()["notifications"]

    assert notifications

    event_ids = {event["id"] for event in eligible_events}
    notification_ids = {
        notification["id"] for notification in notifications
    }

    assert notification_ids.issubset(event_ids)


def test_notification_failure_preserves_metric_and_event(
    client,
    authenticated_user,
):
    user_id = authenticated_user["user_id"]

    # Establish the baseline without introducing a failure.
    for value in [70, 71, 69, 72, 70, 95, 98]:
        create_metric(client, authenticated_user, value)

    with patch(
        "healthguard.main.process_in_app_notification",
        side_effect=RuntimeError("Simulated publication failure"),
    ):
        response = client.post(
            f"/metrics?user_id={user_id}",
            headers=authenticated_user["headers"],
            json={
                "metric_type": "heart_rate",
                "value": 100,
                "unit": "bpm",
                "source": "manual",
            },
        )

    assert response.status_code in (200, 201), response.text

    metric_id = response.json()["id"]

    metrics_response = client.get(
        f"/users/{user_id}/metrics",
        headers=authenticated_user["headers"],
    )

    assert metrics_response.status_code == 200

    assert any(
        metric["id"] == metric_id
        for metric in metrics_response.json()
    )

    db, generator = get_test_session()

    try:
        events = db.scalars(
            select(MonitoringEvent).where(
                MonitoringEvent.user_id == user_id,
            )
        ).all()

        assert events, (
            "Monitoring events should survive notification failures."
        )

        assert any(
            event.notification_status == "pending"
            for event in events
        )

    finally:
        generator.close()


def test_notification_acknowledgment_after_publication(
    client,
    authenticated_user,
):
    create_history(client, authenticated_user)

    user_id = authenticated_user["user_id"]
    headers = authenticated_user["headers"]

    feed_response = client.get(
        f"/users/{user_id}/notifications",
        headers=headers,
    )

    assert feed_response.status_code == 200

    notifications = feed_response.json()["notifications"]

    assert notifications

    event_id = notifications[0]["id"]

    acknowledgment = client.patch(
        f"/users/{user_id}/monitoring/events/"
        f"{event_id}/acknowledge",
        headers=headers,
    )

    assert acknowledgment.status_code == 200

    summary = client.get(
        f"/users/{user_id}/notifications/summary",
        headers=headers,
    )

    assert summary.status_code == 200

    data = summary.json()

    assert data["acknowledged"] >= 1
    assert data["total_notifications"] >= 1
    assert (
        data["acknowledged"] + data["unread"]
        == data["total_notifications"]
    )