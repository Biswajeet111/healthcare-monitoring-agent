import pytest


# --------------------------------------------------
# TEST HELPERS
# --------------------------------------------------

@pytest.fixture
def trend_user(client):
    """Register and authenticate a test user."""

    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Trend Test User",
            "email": "trenduser@example.com",
            "password": "TestPassword@123",
        },
    )

    assert registration.status_code in (200, 201)

    login = client.post(
        "/auth/login",
        json={
            "email": "trenduser@example.com",
            "password": "TestPassword@123",
        },
    )

    assert login.status_code == 200

    return {
        "user_id": registration.json()["id"],
        "headers": {
            "Authorization": (
                f"Bearer {login.json()['access_token']}"
            )
        },
    }


def create_reading(
    client,
    user,
    metric_type="blood_glucose",
    value=110,
    unit="mg/dL",
):
    """Create a measurement through the real API."""

    response = client.post(
        f"/metrics?user_id={user['user_id']}",
        headers=user["headers"],
        json={
            "metric_type": metric_type,
            "value": value,
            "unit": unit,
            "source": "manual",
        },
    )

    assert response.status_code in (200, 201), response.text

    return response.json()


def trend_url(user_id, metric_type="blood_glucose"):
    return (
        f"/users/{user_id}/metrics/"
        f"{metric_type}/trend"
    )


# --------------------------------------------------
# 1. SUCCESSFUL TREND ANALYSIS
# --------------------------------------------------

def test_successful_trend_analysis(client, trend_user):

    create_reading(
        client, trend_user, value=105
    )

    create_reading(
        client, trend_user, value=112
    )

    create_reading(
        client, trend_user, value=125
    )

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers=trend_user["headers"],
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["user_id"] == trend_user["user_id"]
    assert data["metric_type"] == "blood_glucose"
    assert data["total_readings"] == 3

    assert len(data["unit_trends"]) == 1

    analysis = data["unit_trends"][0]

    assert analysis["unit"] == "mg/dL"
    assert analysis["count"] == 3

    assert analysis["minimum"] == 105
    assert analysis["maximum"] == 125

    assert analysis["mean"] == pytest.approx(114.0)

    assert "disclaimer" in data


# --------------------------------------------------
# 2. NO READINGS
# --------------------------------------------------

def test_trend_without_readings(client, trend_user):

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers=trend_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 0
    assert data["unit_trends"] == []


# --------------------------------------------------
# 3. ONE READING
# --------------------------------------------------

def test_trend_with_one_reading(client, trend_user):

    create_reading(
        client, trend_user, value=110
    )

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers=trend_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 1
    assert data["unit_trends"] == []


# --------------------------------------------------
# 4. INVALID METRIC TYPE
# --------------------------------------------------

def test_invalid_metric_type(client, trend_user):

    response = client.get(
        trend_url(
            trend_user["user_id"],
            "invalid_metric",
        ),
        headers=trend_user["headers"],
    )

    assert response.status_code == 422


# --------------------------------------------------
# 5. INVALID LIMIT
# --------------------------------------------------

@pytest.mark.parametrize(
    "limit",
    [0, 1, 501, -10],
)
def test_invalid_trend_limit(
    client,
    trend_user,
    limit,
):

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers=trend_user["headers"],
        params={"limit": limit},
    )

    assert response.status_code == 422


# --------------------------------------------------
# 6. UNAUTHENTICATED ACCESS
# --------------------------------------------------

def test_trend_requires_authentication(client, trend_user):

    response = client.get(
        trend_url(trend_user["user_id"])
    )

    assert response.status_code in (401, 403)


# --------------------------------------------------
# 7. INVALID JWT
# --------------------------------------------------

def test_trend_invalid_jwt(client, trend_user):

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers={
            "Authorization": "Bearer invalid.token.here"
        },
    )

    assert response.status_code == 401


# --------------------------------------------------
# 8. CROSS-USER ACCESS PROTECTION
# --------------------------------------------------

def test_trend_cross_user_access(client, trend_user):

    first_user_id = trend_user["user_id"]

    create_reading(
        client,
        trend_user,
        value=110,
    )

    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Second Trend User",
            "email": "secondtrend@example.com",
            "password": "Password@123",
        },
    )

    assert registration.status_code in (200, 201)

    login = client.post(
        "/auth/login",
        json={
            "email": "secondtrend@example.com",
            "password": "Password@123",
        },
    )

    assert login.status_code == 200

    second_headers = {
        "Authorization": (
            f"Bearer {login.json()['access_token']}"
        )
    }

    response = client.get(
        trend_url(first_user_id),
        headers=second_headers,
    )

    assert response.status_code == 403


# --------------------------------------------------
# 9. METRIC TYPE ISOLATION
# --------------------------------------------------

def test_trend_filters_metric_type(client, trend_user):

    create_reading(
        client,
        trend_user,
        metric_type="blood_glucose",
        value=105,
        unit="mg/dL",
    )

    create_reading(
        client,
        trend_user,
        metric_type="blood_glucose",
        value=115,
        unit="mg/dL",
    )

    create_reading(
        client,
        trend_user,
        metric_type="heart_rate",
        value=75,
        unit="bpm",
    )

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers=trend_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 2

    assert data["unit_trends"][0]["unit"] == "mg/dL"


# --------------------------------------------------
# 10. UNIT NORMALIZATION
# --------------------------------------------------

def test_trend_normalized_glucose_units(
    client,
    trend_user,
):

    create_reading(
        client,
        trend_user,
        value=5.5,
        unit="mmol/L",
    )

    create_reading(
        client,
        trend_user,
        value=110,
        unit="mg/dL",
    )

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers=trend_user["headers"],
    )

    assert response.status_code == 200

    data = response.json()

    # Existing API normalizes glucose to mg/dL.
    assert len(data["unit_trends"]) == 1

    analysis = data["unit_trends"][0]

    assert analysis["unit"] == "mg/dL"
    assert analysis["count"] == 2

    assert analysis["minimum"] == pytest.approx(99.1)
    assert analysis["maximum"] == pytest.approx(110)


# --------------------------------------------------
# 11. VALID LIMIT
# --------------------------------------------------

def test_trend_valid_limit(client, trend_user):

    for value in [100, 105, 110, 115]:
        create_reading(
            client,
            trend_user,
            value=value,
        )

    response = client.get(
        trend_url(trend_user["user_id"]),
        headers=trend_user["headers"],
        params={"limit": 2},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 2
    assert len(data["unit_trends"]) == 1
    assert data["unit_trends"][0]["count"] == 2