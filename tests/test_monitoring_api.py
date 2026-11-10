import pytest


@pytest.fixture
def monitoring_user(client):
    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Monitoring API User",
            "email": "monitoringapi@example.com",
            "password": "TestPassword@123",
        },
    )

    assert registration.status_code in (200, 201), registration.text

    login = client.post(
        "/auth/login",
        json={
            "email": "monitoringapi@example.com",
            "password": "TestPassword@123",
        },
    )

    assert login.status_code == 200, login.text

    return {
        "user_id": registration.json()["id"],
        "headers": {
            "Authorization": (
                f"Bearer {login.json()['access_token']}"
            )
        },
    }


def monitoring_url(user_id, metric_type="blood_glucose"):
    return (
        f"/users/{user_id}/metrics/"
        f"{metric_type}/monitoring"
    )


def create_monitoring_reading(
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


def add_monitoring_readings(
    client,
    user,
    values,
    metric_type="blood_glucose",
    unit="mg/dL",
):
    for value in values:
        create_monitoring_reading(
            client,
            user,
            value,
            metric_type=metric_type,
            unit=unit,
        )


def get_monitoring(client, user, **params):
    return client.get(
        monitoring_url(user["user_id"]),
        headers=user["headers"],
        params=params,
    )


# ============================================================
# SUCCESSFUL MONITORING
# ============================================================

def test_successful_monitoring_report(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["user_id"] == monitoring_user["user_id"]
    assert data["metric_type"] == "blood_glucose"
    assert data["total_readings"] == 8
    assert data["required_readings"] == 8

    assert len(data["reports"]) == 1

    report = data["reports"][0]

    assert report["pipeline_status"] == "completed"
    assert report["unit"] == "mg/dL"
    assert report["safety_validation"]["safe"] is True

    assert (
        report["monitoring_decision"]["monitoring_priority"]
        == "review_recommended"
    )


def test_routine_monitoring(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [70, 75, 72, 73, 71, 72, 73, 74],
        metric_type="heart_rate",
        unit="bpm",
    )

    response = client.get(
        monitoring_url(
            monitoring_user["user_id"],
            "heart_rate",
        ),
        headers=monitoring_user["headers"],
    )

    assert response.status_code == 200, response.text

    report = response.json()["reports"][0]

    assert (
        report["monitoring_decision"]["monitoring_priority"]
        == "routine_tracking"
    )


def test_zero_variance_monitoring(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [100, 100, 100, 100, 100, 110, 120, 130],
    )

    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200, response.text

    report = response.json()["reports"][0]

    assert (
        report["monitoring_decision"]["monitoring_priority"]
        == "more_data_needed"
    )


# ============================================================
# INSUFFICIENT DATA
# ============================================================

def test_no_measurements(client, monitoring_user):
    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 0
    assert data["reports"] == []
    assert data["message"] is not None


def test_insufficient_measurements(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [100, 105, 110],
    )

    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200

    data = response.json()

    assert data["reports"] == []
    assert len(data["insufficient_units"]) == 1

    assert (
        data["insufficient_units"][0]["available_readings"]
        == 3
    )


# ============================================================
# METRIC ISOLATION
# ============================================================

def test_metric_type_isolation(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    add_monitoring_readings(
        client,
        monitoring_user,
        [70, 75],
        metric_type="heart_rate",
        unit="bpm",
    )

    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200

    data = response.json()

    assert data["total_readings"] == 8
    assert len(data["reports"]) == 1
    assert data["reports"][0]["metric_type"] == "blood_glucose"


def test_normalized_glucose_units(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [5.5, 5.6, 5.7, 5.8, 5.9, 6.0, 6.1, 6.2],
        unit="mmol/L",
    )

    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200, response.text

    data = response.json()

    assert len(data["reports"]) == 1
    assert data["reports"][0]["unit"] == "mg/dL"


# ============================================================
# PARAMETER VALIDATION
# ============================================================

@pytest.mark.parametrize(
    "metric_type",
    [
        "invalid_metric",
        "temperature",
        "unknown",
    ],
)
def test_invalid_metric_type(
    client,
    monitoring_user,
    metric_type,
):
    response = client.get(
        monitoring_url(
            monitoring_user["user_id"],
            metric_type,
        ),
        headers=monitoring_user["headers"],
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"baseline_window": 1},
        {"recent_window": 0},
        {"baseline_window": 500},
        {"recent_window": 500},
        {"baseline_window": 10, "recent_window": 3, "limit": 8},
        {"anomaly_threshold": 0},
        {"anomaly_threshold": -1},
        {"limit": 2},
        {"limit": 501},
    ],
)
def test_invalid_parameters(client, monitoring_user, params):
    response = get_monitoring(
        client,
        monitoring_user,
        **params,
    )

    assert response.status_code == 422


def test_custom_analysis_windows(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [100, 101, 102, 103, 104, 105],
    )

    response = get_monitoring(
        client,
        monitoring_user,
        baseline_window=3,
        recent_window=2,
        limit=6,
    )

    assert response.status_code == 200, response.text

    report = response.json()["reports"][0]

    assert (
        report["longitudinal_analysis"]["baseline"]["count"]
        == 3
    )

    assert (
        report["longitudinal_analysis"]["recent"]["count"]
        == 2
    )


def test_reading_limit(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
    )

    response = get_monitoring(
        client,
        monitoring_user,
        baseline_window=3,
        recent_window=2,
        limit=5,
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total_readings"] == 5

    assert (
        data["reports"][0]["longitudinal_analysis"][
            "total_readings"
        ]
        == 5
    )


# ============================================================
# AUTHENTICATION AND AUTHORIZATION
# ============================================================

def test_missing_authentication(client, monitoring_user):
    response = client.get(
        monitoring_url(monitoring_user["user_id"])
    )

    assert response.status_code in (401, 403)


def test_invalid_token(client, monitoring_user):
    response = client.get(
        monitoring_url(monitoring_user["user_id"]),
        headers={
            "Authorization": "Bearer invalid.token.here"
        },
    )

    assert response.status_code == 401


def test_cross_user_access_denied(client, monitoring_user):
    registration = client.post(
        "/auth/register",
        json={
            "full_name": "Another Monitoring User",
            "email": "anothermonitoring@example.com",
            "password": "TestPassword@123",
        },
    )

    assert registration.status_code in (200, 201)

    login = client.post(
        "/auth/login",
        json={
            "email": "anothermonitoring@example.com",
            "password": "TestPassword@123",
        },
    )

    assert login.status_code == 200

    response = client.get(
        monitoring_url(monitoring_user["user_id"]),
        headers={
            "Authorization": (
                f"Bearer {login.json()['access_token']}"
            )
        },
    )

    assert response.status_code == 403


# ============================================================
# SAFETY REPORT
# ============================================================

def test_safety_validation_in_api(client, monitoring_user):
    add_monitoring_readings(
        client,
        monitoring_user,
        [100, 102, 101, 103, 104, 115, 120, 125],
    )

    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200, response.text

    report = response.json()["reports"][0]

    assert report["safety_validation"]["safe"] is True

    assert all(
        value == "passed"
        for value in report["safety_validation"]["checks"].values()
    )


def test_monitoring_disclaimer(client, monitoring_user):
    response = get_monitoring(client, monitoring_user)

    assert response.status_code == 200

    disclaimer = response.json()["disclaimer"]

    assert "not medical urgency" in disclaimer
    assert "do not diagnose" in disclaimer