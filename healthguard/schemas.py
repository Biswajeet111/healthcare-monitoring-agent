from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


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