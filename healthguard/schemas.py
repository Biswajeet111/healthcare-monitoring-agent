from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class HealthMetricCreate(BaseModel):
    metric_type: Literal[
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "blood_glucose",
        "heart_rate",
        "weight",
        "height",
        "steps",
        "sleep_duration"
    ]

    value: float = Field(gt=0)
    unit: str

    source: Literal[
        "manual",
        "health_connect",
        "imported"
    ] = "manual"

    context: str | None = None
    measurement_group_id: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_unit(self):
        allowed_units = {
            "blood_pressure_systolic": ["mmHg"],
            "blood_pressure_diastolic": ["mmHg"],
            "blood_glucose": ["mg/dL", "mmol/L"],
            "heart_rate": ["bpm"],
            "weight": ["kg"],
            "height": ["cm"],
            "steps": ["steps"],
            "sleep_duration": ["hours"],
        }

        if self.unit not in allowed_units[self.metric_type]:
            raise ValueError(
                f"Invalid unit for {self.metric_type}"
            )

        return self

class MedicationLogCreate(BaseModel):
    scheduled_at: datetime
    status: Literal["taken", "missed", "skipped"]
    taken_at: datetime | None = None
    notes: str | None = None


class MedicationLogResponse(BaseModel):
    id: int
    medication_id: int
    scheduled_at: datetime
    status: str
    taken_at: datetime | None
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationCreate(BaseModel):
    name: str
    dosage: str
    frequency: str
    instructions: str | None = None
    start_date: date
    end_date: date | None = None



class MedicationResponse(BaseModel):
    id: int
    user_id: int
    name: str
    dosage: str
    frequency: str
    instructions: str | None
    start_date: datetime
    end_date: datetime | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserProfileCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: str | None = None


class UserProfileResponse(BaseModel):
    id: int
    full_name: str
    email: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HealthMetricResponse(BaseModel):
    id: int
    user_id: int
    metric_type: str
    value: float
    unit: str
    recorded_at: datetime
    source: str
    context: str | None
    measurement_group_id: str | None
    notes: str | None
    original_value: float | None = None
    original_unit: str | None = None

    model_config = ConfigDict(from_attributes=True)

class BloodPressureCreate(BaseModel):
    systolic: float = Field(gt=0)
    diastolic: float = Field(gt=0)

    unit: Literal["mmHg"] = "mmHg"

    source: Literal[
        "manual",
        "health_connect",
        "imported"
    ] = "manual"

    context: str | None = None
    notes: str | None = None

class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: str
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MedicalDocumentResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    file_size: int
    sha256_hash: str
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)
