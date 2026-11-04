import pytest


@pytest.fixture
def authenticated_user(client):
    response = client.post(
        "/auth/register",
        json={
            "full_name": "Test User",
            "email": "testuser@example.com",
            "password": "TestPassword@123"
        }
    )

    assert response.status_code in (200, 201)

    login = client.post(
        "/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPassword@123"
        }
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    return {
        "user_id": response.json()["id"],
        "headers": {"Authorization": f"Bearer {token}"}
    }


def test_home(client):
    response = client.get("/")
    assert response.status_code == 200


def test_register_user(client):
    response = client.post(
        "/auth/register",
        json={
            "full_name": "New User",
            "email": "newuser@example.com",
            "password": "Password@123"
        }
    )

    assert response.status_code in (200, 201)


def test_duplicate_registration(client):
    payload = {
        "full_name": "Duplicate User",
        "email": "duplicate@example.com",
        "password": "Password@123"
    }

    client.post("/auth/register", json=payload)
    response = client.post("/auth/register", json=payload)

    assert response.status_code == 409


def test_login(client):
    client.post(
        "/auth/register",
        json={
            "full_name": "Login User",
            "email": "login@example.com",
            "password": "Password@123"
        }
    )

    response = client.post(
        "/auth/login",
        json={
            "email": "login@example.com",
            "password": "Password@123"
        }
    )

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_get_current_user(client, authenticated_user):
    response = client.get(
        "/auth/me",
        headers=authenticated_user["headers"]
    )

    assert response.status_code == 200


def test_unauthenticated_access(client):
    response = client.get("/auth/me")
    assert response.status_code in (401, 403)



def test_create_health_metric(client, authenticated_user):
    user_id = authenticated_user["user_id"]

    response = client.post(
        f"/metrics?user_id={user_id}",
        headers=authenticated_user["headers"],
        json={
            "metric_type": "heart_rate",
            "value": 75,
            "unit": "bpm",
            "source": "manual",
            "notes": "Automated test"
        }
    )

    assert response.status_code in (200, 201), response.text




def test_invalid_metric_unit(client, authenticated_user):
    response = client.post(
        "/metrics",
        headers=authenticated_user["headers"],
        json={
            "metric_type": "heart_rate",
            "value": 75,
            "unit": "kg",
            "source": "manual"
        }
    )

    assert response.status_code == 422


def test_get_user_metrics(client, authenticated_user):
    user_id = authenticated_user["user_id"]

    response = client.get(
        f"/users/{user_id}/metrics",
        headers=authenticated_user["headers"]
    )

    assert response.status_code == 200


def test_blood_pressure_pair(client, authenticated_user):
    user_id = authenticated_user["user_id"]

    response = client.post(
        f"/users/{user_id}/metrics/blood-pressure",
        headers=authenticated_user["headers"],
        json={
            "systolic": 120,
            "diastolic": 80,
            "unit": "mmHg",
            "source": "manual",
            "notes": "Automated test"
        }
    )

    assert response.status_code in (200, 201)

def test_csv_import_success(client, authenticated_user):
    csv_content = (
        "metric_type,value,unit,recorded_at,notes\n"
        "heart_rate,75,bpm,2026-11-04T09:00:00,Morning reading\n"
        "blood_glucose,110,mg/dL,2026-11-04T09:15:00,Fasting\n"
        "weight,70,kg,2026-11-04T09:30:00,Weekly measurement\n"
    )

    response = client.post(
        "/metrics/import-csv",
        headers=authenticated_user["headers"],
        files={
            "file": (
                "health_data.csv",
                csv_content.encode("utf-8"),
                "text/csv"
            )
        }
    )

    assert response.status_code == 200, response.text
    assert response.json()["imported_count"] == 3
    assert response.json()["failed_count"] == 0


def test_csv_import_invalid_extension(client, authenticated_user):
    response = client.post(
        "/metrics/import-csv",
        headers=authenticated_user["headers"],
        files={
            "file": ("report.txt", b"some data", "text/plain")
        }
    )

    assert response.status_code == 400


def test_csv_import_missing_columns(client, authenticated_user):
    csv_content = "name,age\nJohn,25"

    response = client.post(
        "/metrics/import-csv",
        headers=authenticated_user["headers"],
        files={
            "file": ("invalid.csv", csv_content.encode(), "text/csv")
        }
    )

    assert response.status_code == 400


def test_csv_import_invalid_unit(client, authenticated_user):
    csv_content = (
        "metric_type,value,unit\n"
        "heart_rate,75,kg\n"
    )

    response = client.post(
        "/metrics/import-csv",
        headers=authenticated_user["headers"],
        files={
            "file": ("invalid_unit.csv", csv_content.encode(), "text/csv")
        }
    )

    assert response.status_code == 200
    assert response.json()["imported_count"] == 0
    assert response.json()["failed_count"] == 1


def test_csv_import_empty_file(client, authenticated_user):
    response = client.post(
        "/metrics/import-csv",
        headers=authenticated_user["headers"],
        files={
            "file": ("empty.csv", b"", "text/csv")
        }
    )

    assert response.status_code == 400


def test_csv_import_unauthenticated(client):
    csv_content = "metric_type,value,unit\nheart_rate,75,bpm"

    response = client.post(
        "/metrics/import-csv",
        files={
            "file": ("health.csv", csv_content.encode(), "text/csv")
        }
    )

    assert response.status_code in (401, 403)

def test_manual_glucose_normalization(client, authenticated_user):
    user_id = authenticated_user["user_id"]

    response = client.post(
        f"/metrics?user_id={user_id}",
        headers=authenticated_user["headers"],
        json={
            "metric_type": "blood_glucose",
            "value": 5.5,
            "unit": "mmol/L",
            "source": "manual",
            "notes": "Normalization test"
        }
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert data["value"] == 99.1
    assert data["unit"] == "mg/dL"
    assert data["original_value"] == 5.5
    assert data["original_unit"] == "mmol/L"


def test_blood_pressure_original_values(client, authenticated_user):
    user_id = authenticated_user["user_id"]

    response = client.post(
        f"/users/{user_id}/metrics/blood-pressure",
        headers=authenticated_user["headers"],
        json={
            "systolic": 120,
            "diastolic": 80,
            "unit": "mmHg",
            "source": "manual",
            "notes": "Normalization test"
        }
    )

    assert response.status_code in (200, 201), response.text

    history = client.get(
        f"/users/{user_id}/metrics",
        headers=authenticated_user["headers"]
    )

    assert history.status_code == 200

    records = history.json()

    systolic = next(
        item for item in records
        if item["metric_type"] == "blood_pressure_systolic"
    )

    diastolic = next(
        item for item in records
        if item["metric_type"] == "blood_pressure_diastolic"
    )

    assert systolic["original_value"] == 120
    assert systolic["original_unit"] == "mmHg"
    assert diastolic["original_value"] == 80
    assert diastolic["original_unit"] == "mmHg"

def test_documents_requires_authentication(client):
    response = client.get("/documents")
    assert response.status_code in (401, 403)


def test_delete_nonexistent_document(client, authenticated_user):
    response = client.delete(
        "/documents/99999",
        headers=authenticated_user["headers"]
    )

    assert response.status_code == 404

def test_duplicate_csv_import(client, authenticated_user):
    csv_content = (
        "metric_type,value,unit\n"
        "heart_rate,75,bpm\n"
    )

    headers = authenticated_user["headers"]

    first_response = client.post(
        "/metrics/import-csv",
        headers=headers,
        files={
            "file": (
                "health.csv",
                csv_content.encode(),
                "text/csv"
            )
        }
    )

    assert first_response.status_code == 200

    second_response = client.post(
        "/metrics/import-csv",
        headers=headers,
        files={
            "file": (
                "health.csv",
                csv_content.encode(),
                "text/csv"
            )
        }
    )

    assert second_response.status_code == 409

def test_invalid_jwt(client):
    response = client.get(
        "/auth/me",
        headers={
            "Authorization": "Bearer invalid.token.here"
        }
    )

    assert response.status_code == 401

def test_cross_user_metrics_access(client, authenticated_user):
    first_user_id = authenticated_user["user_id"]

    # Register second user
    client.post(
        "/auth/register",
        json={
            "full_name": "Second User",
            "email": "seconduser@example.com",
            "password": "Password@123"
        }
    )

    # Login second user
    login = client.post(
        "/auth/login",
        json={
            "email": "seconduser@example.com",
            "password": "Password@123"
        }
    )

    second_token = login.json()["access_token"]

    second_headers = {
        "Authorization": f"Bearer {second_token}"
    }

    # Second user attempts to access first user's metrics
    response = client.get(
        f"/users/{first_user_id}/metrics",
        headers=second_headers
    )

    assert response.status_code == 403

def test_cross_user_metric_creation(client, authenticated_user):
    first_user_id = authenticated_user["user_id"]

    client.post(
        "/auth/register",
        json={
            "full_name": "Another User",
            "email": "anotheruser@example.com",
            "password": "Password@123"
        }
    )

    login = client.post(
        "/auth/login",
        json={
            "email": "anotheruser@example.com",
            "password": "Password@123"
        }
    )

    second_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    response = client.post(
        f"/metrics?user_id={first_user_id}",
        headers=second_headers,
        json={
            "metric_type": "heart_rate",
            "value": 80,
            "unit": "bpm",
            "source": "manual"
        }
    )

    assert response.status_code == 403