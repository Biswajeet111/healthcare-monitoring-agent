from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
)
from sqlalchemy.orm import relationship

from healthguard.database.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    health_metrics = relationship(
        "HealthMetric",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    medications = relationship(
    "Medication",
    back_populates="user",
    cascade="all, delete-orphan"
    )


class HealthMetric(Base):
    __tablename__ = "health_metrics"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True
    )

    metric_type = Column(String(50), nullable=False, index=True)
    value = Column(Float, nullable=False)
    unit = Column(String(30), nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    user = relationship(
        "UserProfile",
        back_populates="health_metrics"
    )
class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True
    )

    adherence_logs = relationship(
        "MedicationLog",
        back_populates="medication",
        cascade="all, delete-orphan"
    )

    name = Column(String(150), nullable=False)
    dosage = Column(String(100), nullable=False)
    frequency = Column(String(100), nullable=False)
    instructions = Column(Text, nullable=True)

    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship(
        "UserProfile",
        back_populates="medications"
    )

class MedicationLog(Base):
    __tablename__ = "medication_logs"

    id = Column(Integer, primary_key=True, index=True)

    medication_id = Column(
        Integer,
        ForeignKey("medications.id"),
        nullable=False,
        index=True
    )

    scheduled_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)
    taken_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    medication = relationship(
        "Medication",
        back_populates="adherence_logs"
    )