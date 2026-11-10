import pytest


@pytest.fixture
def longitudinal_user(client):
    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Longitudinal Test User",
            "email": "longitudinal@example.com",
            "password": "TestPassword@123",
        },
    )

    assert registration.status_code in (200, 201), registration.text

    login = client.post(
        "/auth/login",
        json={
            "email": "longitudinal@example.com",
            "password": "TestPassword@123",
        },
    )

    assert login.status_code == 200, login.text

    return {
        "user_id": registration.json()["id"],
        "headers": {
            "Authorization": f"Bearer {login.json()['access_token']}"
        },
    }


def longitudinal_url(user_id, metric_type="blood_glucose"):
    return f"/users/{user_id}/metrics/{metric_type}/longitudinal"


def create_reading(
    client,
    user,
    value,
    metric_type="blood_glucose",
    unit="mg/dL",
):
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


def add_readings(client, user, values, **kwargs):
    for value in values:
        create_reading(client, user, value, **kwargs)


def get_analysis(client, user, **params):
    return client.get(
        longitudinal_url(user["user_id"]),
        headers=user["headers"],
        params=params,
    )


def test_successful_longitudinal_analysis(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["user_id"] == longitudinal_user["user_id"]
    assert data["metric_type"] == "blood_glucose"
    assert data["total_readings"] == 8
    assert data["required_readings"] == 8

    assert len(data["unit_analyses"]) == 1

    analysis = data["unit_analyses"][0]

    assert analysis["unit"] == "mg/dL"
    assert analysis["baseline"]["count"] == 5
    assert analysis["recent"]["count"] == 3
    assert analysis["comparison"]["direction"] == "increasing"
    assert analysis["comparison"]["absolute_change"] > 0
    assert len(analysis["rolling_averages"]) == 6
    assert "disclaimer" in data


def test_no_readings(client, longitudinal_user):
    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 0
    assert data["unit_analyses"] == []
    assert data["message"] is not None


def test_insufficient_readings(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 105, 110],
    )

    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 3
    assert data["unit_analyses"] == []
    assert data["message"] is not None


def test_statistical_anomaly_detected(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 101, 99, 100, 102, 105, 110, 150],
    )

    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200, response.text

    anomaly = response.json()["unit_analyses"][0]["anomaly"]

    assert anomaly["is_anomaly"] is True
    assert anomaly["status"] == "statistical_deviation_detected"
    assert anomaly["z_score"] is not None


def test_no_statistical_anomaly(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 105, 95, 102, 98, 100, 101, 102],
    )

    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200, response.text

    anomaly = response.json()["unit_analyses"][0]["anomaly"]

    assert anomaly["is_anomaly"] is False
    assert anomaly["status"] == "within_configured_threshold"


def test_zero_variance_baseline(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 100, 100, 100, 100, 110, 120, 130],
    )

    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200, response.text

    anomaly = response.json()["unit_analyses"][0]["anomaly"]

    assert anomaly["is_anomaly"] is None
    assert anomaly["z_score"] is None
    assert anomaly["status"] == "insufficient_baseline_variability"


def test_metric_type_isolation(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    add_readings(
        client,
        longitudinal_user,
        [70, 75],
        metric_type="heart_rate",
        unit="bpm",
    )

    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 8
    assert len(data["unit_analyses"]) == 1
    assert data["unit_analyses"][0]["unit"] == "mg/dL"


def test_normalized_glucose_units(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [5.5, 5.6, 5.7, 5.8, 5.9, 6.0, 6.1, 6.2],
        unit="mmol/L",
    )

    response = get_analysis(client, longitudinal_user)

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total_readings"] == 8
    assert len(data["unit_analyses"]) == 1
    assert data["unit_analyses"][0]["unit"] == "mg/dL"


@pytest.mark.parametrize(
    "metric_type",
    ["invalid_metric", "temperature", "unknown"],
)
def test_invalid_metric_type(client, longitudinal_user, metric_type):
    response = client.get(
        longitudinal_url(longitudinal_user["user_id"], metric_type),
        headers=longitudinal_user["headers"],
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"baseline_window": 1},
        {"recent_window": 0},
        {"baseline_window": 500, "recent_window": 3},
        {"baseline_window": 10, "recent_window": 3, "limit": 8},
        {"anomaly_threshold": 0},
        {"anomaly_threshold": -2},
        {"limit": 2},
        {"limit": 501},
    ],
)
def test_invalid_parameters(client, longitudinal_user, params):
    response = get_analysis(client, longitudinal_user, **params)

    assert response.status_code == 422


def test_missing_authentication(client, longitudinal_user):
    response = client.get(
        longitudinal_url(longitudinal_user["user_id"])
    )

    assert response.status_code in (401, 403)


def test_invalid_jwt(client, longitudinal_user):
    response = client.get(
        longitudinal_url(longitudinal_user["user_id"]),
        headers={
            "Authorization": "Bearer invalid.token.here"
        },
    )

    assert response.status_code == 401


def test_cross_user_access_denied(client, longitudinal_user):
    first_user_id = longitudinal_user["user_id"]

    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Second Longitudinal User",
            "email": "secondlongitudinal@example.com",
            "password": "Password@123",
        },
    )

    assert registration.status_code in (200, 201)

    login = client.post(
        "/auth/login",
        json={
            "email": "secondlongitudinal@example.com",
            "password": "Password@123",
        },
    )

    assert login.status_code == 200

    response = client.get(
        longitudinal_url(first_user_id),
        headers={
            "Authorization": f"Bearer {login.json()['access_token']}"
        },
    )

    assert response.status_code == 403


def test_custom_analysis_windows(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 101, 102, 103, 104, 105],
    )

    response = get_analysis(
        client,
        longitudinal_user,
        baseline_window=3,
        recent_window=2,
        limit=6,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["required_readings"] == 5

    analysis = data["unit_analyses"][0]

    assert analysis["baseline"]["count"] == 3
    assert analysis["recent"]["count"] == 2


def test_reading_limit(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
    )

    response = get_analysis(
        client,
        longitudinal_user,
        baseline_window=3,
        recent_window=2,
        limit=5,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total_readings"] == 5
    assert data["unit_analyses"][0]["total_readings"] == 5


def test_anomaly_threshold_configuration(client, longitudinal_user):
    add_readings(
        client,
        longitudinal_user,
        [100, 101, 99, 100, 102, 105, 110, 150],
    )

    response = get_analysis(
        client,
        longitudinal_user,
        anomaly_threshold=100.0,
    )

    assert response.status_code == 200, response.text

    anomaly = response.json()["unit_analyses"][0]["anomaly"]

    assert anomaly["is_anomaly"] is False
    assert anomaly["threshold"] == 100.0