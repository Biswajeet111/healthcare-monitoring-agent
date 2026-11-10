"""Phase 3.4.6: notification authorization and edge-case regression tests.

Run with: python -m pytest tests/test_notification_security.py -v
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from healthguard.database.models import MonitoringEvent
from healthguard.database.session import get_db
from healthguard.main import app


@pytest.fixture
def two_users(client):
    users = []
    for _ in range(2):
        email = f"security_{uuid4().hex}@example.com"
        password = "TestPassword@123"
        registration = client.post("/auth/register", json={
            "full_name": "Notification Security Test User",
            "email": email,
            "password": password,
        })
        assert registration.status_code in (200, 201), registration.text
        login = client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        users.append({
            "id": registration.json()["id"],
            "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        })
    return users


def insert_notification(user_id):
    dependency = app.dependency_overrides[get_db]
    generator = dependency()
    db = next(generator)
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        event = MonitoringEvent(
            user_id=user_id,
            fingerprint=uuid4().hex + uuid4().hex,
            metric_type="heart_rate",
            unit="bpm",
            event_type="statistical_deviation",
            event_level="review",
            monitoring_priority="review_recommended",
            statistical_status="statistical_deviation_detected",
            message="Test-only statistical observation.",
            notification_status="delivered",
            created_at=now,
            notified_at=now,
            is_acknowledged=False,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event.id
    finally:
        generator.close()


def test_invalid_token_rejected_for_feed_and_summary(client, two_users):
    user_id = two_users[0]["id"]
    invalid_headers = {"Authorization": "Bearer invalid.token.value"}
    for endpoint in (
        f"/users/{user_id}/notifications",
        f"/users/{user_id}/notifications/summary",
    ):
        response = client.get(endpoint, headers=invalid_headers)
        assert response.status_code == 401, response.text


def test_cross_user_summary_access_denied(client, two_users):
    owner, outsider = two_users
    insert_notification(owner["id"])
    response = client.get(
        f"/users/{owner['id']}/notifications/summary",
        headers=outsider["headers"],
    )
    assert response.status_code == 403, response.text


def test_cross_user_event_acknowledgment_denied(client, two_users):
    owner, outsider = two_users
    event_id = insert_notification(owner["id"])
    response = client.patch(
        f"/users/{owner['id']}/monitoring/events/{event_id}/acknowledge",
        headers=outsider["headers"],
    )
    assert response.status_code == 403, response.text
    own_feed = client.get(
        f"/users/{owner['id']}/notifications?unread_only=true",
        headers=owner["headers"],
    )
    assert own_feed.status_code == 200
    assert any(item["id"] == event_id for item in own_feed.json()["notifications"])


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "offset=-1", "limit=abc"])
def test_invalid_notification_pagination_rejected(client, two_users, query):
    owner = two_users[0]
    response = client.get(
        f"/users/{owner['id']}/notifications?{query}",
        headers=owner["headers"],
    )
    assert response.status_code == 422, response.text


def test_acknowledgment_is_idempotent(client, two_users):
    owner = two_users[0]
    event_id = insert_notification(owner["id"])
    endpoint = f"/users/{owner['id']}/monitoring/events/{event_id}/acknowledge"
    first = client.patch(endpoint, headers=owner["headers"])
    second = client.patch(endpoint, headers=owner["headers"])
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_event = first.json()["event"]
    second_event = second.json()["event"]
    assert first_event["is_acknowledged"] is True
    assert second_event["is_acknowledged"] is True
    assert first_event["acknowledged_at"] == second_event["acknowledged_at"]
    summary = client.get(
        f"/users/{owner['id']}/notifications/summary",
        headers=owner["headers"],
    )
    assert summary.status_code == 200
    assert summary.json()["total_notifications"] == 1
    assert summary.json()["acknowledged"] == 1
    assert summary.json()["unread"] == 0


def test_notification_summary_isolation(client, two_users):
    owner, outsider = two_users
    insert_notification(owner["id"])
    insert_notification(owner["id"])
    insert_notification(outsider["id"])
    for user, expected in ((owner, 2), (outsider, 1)):
        response = client.get(
            f"/users/{user['id']}/notifications/summary",
            headers=user["headers"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["total_notifications"] == expected
        assert response.json()["unread"] == expected
