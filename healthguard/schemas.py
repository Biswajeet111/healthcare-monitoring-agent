from datetime import date
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


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


class HealthMetricCreate(BaseModel):
    metric_type: str
    value: float
    unit: str
    notes: str | None = None


class HealthMetricResponse(BaseModel):
    id: int
    user_id: int
    metric_type: str
    value: float
    unit: str
    recorded_at: datetime
    notes: str | None

    model_config = ConfigDict(from_attributes=True)