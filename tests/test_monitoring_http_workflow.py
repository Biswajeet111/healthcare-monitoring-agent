import uuid

import pytest


@pytest.fixture
def monitoring_user(client):
    """
    Create a real authenticated test user using the existing
    FastAPI registration and login endpoints.
    """

    unique_id = uuid.uuid4().hex[:10]

    email = f"monitoring_{unique_id}@example.com"
    password = "TestPassword@123"

    register = client.post(
        "/auth/register",
        json={
            "full_name": "HTTP Monitoring Test User",
            "email": email,
            "password": password,
        },
    )

    assert register.status_code in (200, 201), register.text

    login = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login.status_code == 200, login.text

    return {
        "user_id": register.json()["id"],
        "headers": {
            "Authorization": f"Bearer {login.json()['access_token']}"
        },
    }


def create_metric(client, user, value):
    """
    Insert a measurement through the real HTTP endpoint.
    """

    response = client.post(
        f"/metrics?user_id={user['user_id']}",
        headers=user["headers"],
        json={
            "metric_type": "heart_rate",
            "value": value,
            "unit": "bpm",
            "source": "manual",
            "notes": "HTTP monitoring integration test",
        },
    )

    assert response.status_code in (200, 201), response.text

    return response.json()


def create_monitoring_history(client, user):
    """
    Establish a historical baseline followed by
    measurements that differ from that baseline.
    """

    values = [
        70, 71, 69, 72, 70,
        95, 98, 100,
    ]

    return [
        create_metric(client, user, value)
        for value in values
    ]


# ============================================================
# TEST 1 — AUTHENTICATED METRIC CREATION
# ============================================================

def test_authenticated_metric_creation(client, monitoring_user):

    metric = create_metric(
        client,
        monitoring_user,
        75,
    )

    assert metric["metric_type"] == "heart_rate"
    assert metric["unit"] == "bpm"
    assert metric["value"] == 75


# ============================================================
# TEST 2 — AUTOMATIC MONITORING EVENT GENERATION
# ============================================================

def test_automatic_monitoring_event_generation(
    client,
    monitoring_user,
):

    create_monitoring_history(client, monitoring_user)

    response = client.get(
        f"/users/{monitoring_user['user_id']}/monitoring/events",
        headers=monitoring_user["headers"],
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total"] >= 1, (
        "No monitoring event was generated automatically "
        "after measurements were created through POST /metrics."
    )

    assert any(
        event["metric_type"] == "heart_rate"
        for event in data["events"]
    )


# ============================================================
# TEST 3 — EVENT SUMMARY
# ============================================================

def test_monitoring_event_summary_http(
    client,
    monitoring_user,
):

    create_monitoring_history(client, monitoring_user)

    response = client.get(
        f"/users/{monitoring_user['user_id']}/monitoring/events/summary",
        headers=monitoring_user["headers"],
    )

    assert response.status_code == 200, response.text

    summary = response.json()

    assert summary["total_events"] >= 1

    assert (
        summary["acknowledged"]
        + summary["unacknowledged"]
        == summary["total_events"]
    )


# ============================================================
# TEST 4 — ACKNOWLEDGMENT THROUGH HTTP
# ============================================================

def test_monitoring_acknowledgment_http(
    client,
    monitoring_user,
):

    create_monitoring_history(client, monitoring_user)

    events_response = client.get(
        f"/users/{monitoring_user['user_id']}/monitoring/events",
        headers=monitoring_user["headers"],
    )

    assert events_response.status_code == 200

    events = events_response.json()["events"]

    assert events

    event = events[0]

    event_id = event["id"]
    original_notification_status = event["notification_status"]

    response = client.patch(
        (
            f"/users/{monitoring_user['user_id']}"
            f"/monitoring/events/{event_id}/acknowledge"
        ),
        headers=monitoring_user["headers"],
    )

    assert response.status_code == 200, response.text

    acknowledged_event = response.json()["event"]

    assert acknowledged_event["is_acknowledged"] is True
    assert acknowledged_event["acknowledged_at"] is not None

    assert (
        acknowledged_event["notification_status"]
        == original_notification_status
    )

    # Verify persistence through another HTTP request.

    verification = client.get(
        (
            f"/users/{monitoring_user['user_id']}"
            f"/monitoring/events/{event_id}"
        ),
        headers=monitoring_user["headers"],
    )

    assert verification.status_code == 200

    persisted = verification.json()

    assert persisted["is_acknowledged"] is True
    assert persisted["acknowledged_at"] is not None


# ============================================================
# TEST 5 — UNAUTHENTICATED ACCESS
# ============================================================

def test_monitoring_events_require_authentication(
    client,
    monitoring_user,
):

    response = client.get(
        f"/users/{monitoring_user['user_id']}/monitoring/events"
    )

    assert response.status_code == 401


# ============================================================
# TEST 6 — CROSS-USER ACCESS PROTECTION
# ============================================================

def test_cross_user_monitoring_access_denied(
    client,
    monitoring_user,
):

    second_email = f"second_{uuid.uuid4().hex[:10]}@example.com"

    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Second Monitoring User",
            "email": second_email,
            "password": "TestPassword@123",
        },
    )

    assert registration.status_code in (200, 201)

    second_user_id = registration.json()["id"]

    response = client.get(
        f"/users/{second_user_id}/monitoring/events",
        headers=monitoring_user["headers"],
    )

    assert response.status_code == 403