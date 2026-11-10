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
    UniqueConstraint,
    CheckConstraint,
    Index,
    JSON,
)

from sqlalchemy.orm import relationship

from healthguard.database.base import Base


# ============================================================
# USER PROFILE
# ============================================================

class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)

    full_name = Column(String(150), nullable=False)

    email = Column(
        String(255),
        unique=True,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    password_hash = Column(
        String(255),
        nullable=True,
    )

    health_metrics = relationship(
        "HealthMetric",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    monitoring_events = relationship(
        "MonitoringEvent",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    medications = relationship(
        "Medication",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    agent_audits = relationship(
        "AgentExecutionAudit",
        back_populates="user",
        cascade="all, delete-orphan",
    )


# ============================================================
# HEALTH METRIC
# ============================================================

class HealthMetric(Base):
    __tablename__ = "health_metrics"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True,
    )

    metric_type = Column(
        String(50),
        nullable=False,
        index=True,
    )

    value = Column(
        Float,
        nullable=False,
    )

    unit = Column(
        String(30),
        nullable=False,
    )

    recorded_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    notes = Column(
        Text,
        nullable=True,
    )

    original_value = Column(
        Float,
        nullable=True,
    )

    original_unit = Column(
        String(50),
        nullable=True,
    )

    source = Column(
        String(30),
        nullable=False,
        default="manual",
        server_default="manual",
    )

    context = Column(
        String(50),
        nullable=True,
    )

    measurement_group_id = Column(
        String(36),
        nullable=True,
        index=True,
    )

    user = relationship(
        "UserProfile",
        back_populates="health_metrics",
    )


# ============================================================
# MEDICATION
# ============================================================

class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True,
    )

    adherence_logs = relationship(
        "MedicationLog",
        back_populates="medication",
        cascade="all, delete-orphan",
    )

    name = Column(
        String(150),
        nullable=False,
    )

    dosage = Column(
        String(100),
        nullable=False,
    )

    frequency = Column(
        String(100),
        nullable=False,
    )

    instructions = Column(
        Text,
        nullable=True,
    )

    start_date = Column(
        DateTime,
        nullable=False,
    )

    end_date = Column(
        DateTime,
        nullable=True,
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    user = relationship(
        "UserProfile",
        back_populates="medications",
    )

    schedules = relationship(
        "MedicationSchedule",
        back_populates="medication",
        cascade="all, delete-orphan",
    )

    dose_occurrences = relationship(
        "MedicationDoseOccurrence",
        back_populates="medication",
        cascade="all, delete-orphan",
    )

    reminders = relationship(
        "MedicationReminder",
        back_populates="medication",
        cascade="all, delete-orphan",
    )


# ============================================================
# MEDICATION LOG
# ============================================================

class MedicationLog(Base):
    __tablename__ = "medication_logs"

    id = Column(Integer, primary_key=True, index=True)

    medication_id = Column(
        Integer,
        ForeignKey("medications.id"),
        nullable=False,
        index=True,
    )

    scheduled_at = Column(
        DateTime,
        nullable=False,
    )

    status = Column(
        String(20),
        nullable=False,
    )

    taken_at = Column(
        DateTime,
        nullable=True,
    )

    notes = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    medication = relationship(
        "Medication",
        back_populates="adherence_logs",
    )


# ============================================================
# MEDICAL DOCUMENT
# ============================================================

class MedicalDocument(Base):
    __tablename__ = "medical_documents"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True,
    )

    filename = Column(
        String(255),
        nullable=False,
    )

    stored_path = Column(
        String(500),
        nullable=False,
    )

    content_type = Column(
        String(100),
        default="application/pdf",
    )

    file_size = Column(
        Integer,
        nullable=False,
    )

    sha256_hash = Column(
        String(64),
        nullable=False,
    )

    extracted_text = Column(
        Text,
        nullable=True,
    )

    uploaded_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ============================================================
# CSV IMPORT
# ============================================================

class CSVImport(Base):
    __tablename__ = "csv_imports"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "sha256_hash",
            name="uq_csv_import_user_hash",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id"),
        nullable=False,
        index=True,
    )

    filename = Column(
        String(255),
        nullable=False,
    )

    sha256_hash = Column(
        String(64),
        nullable=False,
    )

    imported_count = Column(
        Integer,
        default=0,
    )

    imported_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ============================================================
# MONITORING EVENT
# PHASE 3.3.3 + PHASE 3.3.5
# ============================================================

class MonitoringEvent(Base):
    """
    Persistent record of a classified health monitoring event.

    Events represent statistical monitoring observations,
    not medical diagnoses or clinical emergencies.

    Phase 3.3.5 adds user acknowledgment tracking.
    """

    __tablename__ = "monitoring_events"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'statistical_deviation', "
            "'insufficient_baseline_variability', "
            "'routine_monitoring')",
            name="ck_monitoring_event_type",
        ),

        CheckConstraint(
            "event_level IN ("
            "'review', 'informational', 'routine')",
            name="ck_monitoring_event_level",
        ),

        CheckConstraint(
            "notification_status IN ("
            "'pending', 'suppressed', 'delivered', 'failed')",
            name="ck_monitoring_notification_status",
        ),

        CheckConstraint(
            "length(fingerprint) = 64",
            name="ck_monitoring_fingerprint_length",
        ),

        Index(
            "ix_monitoring_events_user_fingerprint_created",
            "user_id",
            "fingerprint",
            "created_at",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    user_id = Column(
        Integer,
        ForeignKey(
            "user_profiles.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    fingerprint = Column(
        String(64),
        nullable=False,
    )

    metric_type = Column(
        String(50),
        nullable=False,
    )

    unit = Column(
        String(30),
        nullable=False,
    )

    event_type = Column(
        String(60),
        nullable=False,
    )

    event_level = Column(
        String(30),
        nullable=False,
    )

    monitoring_priority = Column(
        String(50),
        nullable=False,
    )

    statistical_status = Column(
        String(60),
        nullable=False,
    )

    message = Column(
        Text,
        nullable=False,
    )

    # --------------------------------------------------------
    # Notification tracking
    # --------------------------------------------------------

    notification_status = Column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    notified_at = Column(
        DateTime,
        nullable=True,
    )

    evidence_json = Column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # Phase 3.3.5 — User acknowledgment
    # --------------------------------------------------------

    is_acknowledged = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    acknowledged_at = Column(
        DateTime,
        nullable=True,
    )

    # --------------------------------------------------------
    # Relationships
    # --------------------------------------------------------

    user = relationship(
        "UserProfile",
        back_populates="monitoring_events",
    )


# ============================================================
# MEDICATION SCHEDULE  (Phase 6)
# ============================================================

class MedicationSchedule(Base):
    """
    Structured schedule for a medication.

    One medication has at most one active schedule.
    When a schedule is modified, the old one is deactivated
    and a new one is created so that historical dose occurrences
    are never retroactively altered.
    """

    __tablename__ = "medication_schedules"

    __table_args__ = (
        CheckConstraint(
            "schedule_type IN ('daily', 'weekly', 'as_needed')",
            name="ck_med_schedule_type",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    medication_id = Column(
        Integer,
        ForeignKey("medications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # daily | weekly | as_needed
    schedule_type = Column(String(20), nullable=False)

    # JSON list of "HH:MM" strings — e.g. ["08:00","20:00"]
    times_of_day_json = Column(Text, nullable=False, default="[]")

    # JSON list of weekday integers (0=Mon…6=Sun) for weekly schedules
    weekdays_json = Column(Text, nullable=False, default="[]")

    # IANA timezone string — e.g. "Asia/Kolkata"
    timezone = Column(String(60), nullable=False, default="UTC")

    # When this schedule version became effective
    effective_from = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Set when schedule is superseded or deactivated
    effective_until = Column(DateTime, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    medication = relationship("Medication", back_populates="schedules")
    dose_occurrences = relationship(
        "MedicationDoseOccurrence",
        back_populates="schedule",
        cascade="all, delete-orphan",
    )


# ============================================================
# MEDICATION DOSE OCCURRENCE  (Phase 6)
# ============================================================

class MedicationDoseOccurrence(Base):
    """
    One calculated dose occurrence generated from a MedicationSchedule.

    Records the scheduled time and the confirmed user action (taken /
    skipped / missed).  A dose is never automatically confirmed.
    """

    __tablename__ = "medication_dose_occurrences"

    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "scheduled_at",
            name="uq_dose_occurrence_schedule_scheduled_at",
        ),
        CheckConstraint(
            "status IN ('upcoming','due','overdue','taken','skipped','missed')",
            name="ck_dose_occurrence_status",
        ),
        Index(
            "ix_dose_occ_medication_scheduled",
            "medication_id",
            "scheduled_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    medication_id = Column(
        Integer,
        ForeignKey("medications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    schedule_id = Column(
        Integer,
        ForeignKey("medication_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # UTC wall-clock time when the dose is scheduled
    scheduled_at = Column(DateTime, nullable=False)

    # Computed status — only the user can confirm a dose
    status = Column(String(20), nullable=False, default="upcoming")

    # Set when user confirms they took the dose
    taken_at = Column(DateTime, nullable=True)

    # Optional note attached to the dose action
    notes = Column(Text, nullable=True)

    # When the user last updated this record
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    medication = relationship("Medication", back_populates="dose_occurrences")
    schedule = relationship("MedicationSchedule", back_populates="dose_occurrences")


# ============================================================
# MEDICATION REMINDER  (Phase 6)
# ============================================================

class MedicationReminder(Base):
    """
    An in-app reminder generated for a due or overdue dose.

    Reminders are generated server-side by the reminder worker.
    They are user-specific and idempotent — one reminder per occurrence.
    """

    __tablename__ = "medication_reminders"

    __table_args__ = (
        UniqueConstraint(
            "occurrence_id",
            name="uq_reminder_occurrence",
        ),
        CheckConstraint(
            "status IN ('pending','acknowledged','dismissed')",
            name="ck_reminder_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    occurrence_id = Column(
        Integer,
        ForeignKey("medication_dose_occurrences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    medication_id = Column(
        Integer,
        ForeignKey("medications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    message = Column(Text, nullable=False)

    status = Column(String(20), nullable=False, default="pending")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    acknowledged_at = Column(DateTime, nullable=True)

    occurrence = relationship("MedicationDoseOccurrence")
    medication = relationship("Medication", back_populates="reminders")


# ============================================================
# MEDICAL KNOWLEDGE DOCUMENT  (Phase 7)
# ============================================================

class MedicalKnowledgeDocument(Base):
    """
    An approved, trusted medical reference document ingested into
    the RAG knowledge base.

    Distinct from MedicalDocument which stores user-uploaded files.
    These are curated global-knowledge sources (WHO, MedlinePlus, etc.).
    """

    __tablename__ = "medical_knowledge_documents"

    __table_args__ = (
        UniqueConstraint(
            "content_hash",
            name="uq_knowledge_doc_hash",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(500), nullable=False)

    source_organization = Column(String(200), nullable=True)

    source_url = Column(String(1000), nullable=True)

    document_type = Column(String(100), nullable=True)

    # ISO date strings
    publication_date = Column(String(20), nullable=True)
    review_date = Column(String(20), nullable=True)

    # SHA-256 of raw file content for deduplication
    content_hash = Column(String(64), nullable=False)

    # Original file path (relative to project root)
    source_path = Column(String(1000), nullable=True)

    # Indexing lifecycle
    index_status = Column(
        String(20),
        nullable=False,
        default="pending",
    )  # pending | indexed | failed | deleted

    indexed_at = Column(DateTime, nullable=True)

    ingested_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    chunks = relationship(
        "MedicalKnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


# ============================================================
# MEDICAL KNOWLEDGE CHUNK  (Phase 7)
# ============================================================

class MedicalKnowledgeChunk(Base):
    """
    One text chunk from a MedicalKnowledgeDocument.

    The ChromaDB vector ID mirrors this record's ID so deletions
    can be propagated to the vector store.
    """

    __tablename__ = "medical_knowledge_chunks"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("medical_knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Stable string ID used in ChromaDB (e.g. "doc-{doc_id}-chunk-{seq}")
    chroma_id = Column(String(100), nullable=False, unique=True, index=True)

    chunk_index = Column(Integer, nullable=False)

    text = Column(Text, nullable=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("MedicalKnowledgeDocument", back_populates="chunks")


# ============================================================
# DOCUMENT RAG INDEX STATUS  (Phase 7)
# ============================================================

class DocumentIndexStatus(Base):
    """
    Tracks whether a user-uploaded MedicalDocument has been indexed
    into the per-user ChromaDB collection for RAG retrieval.
    """

    __tablename__ = "document_index_statuses"

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            name="uq_doc_index_status_doc",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(
        Integer,
        ForeignKey("medical_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # pending | indexed | failed | not_applicable (scanned PDFs)
    status = Column(String(20), nullable=False, default="pending")

    # Number of chunks stored in ChromaDB
    chunk_count = Column(Integer, nullable=True)

    error_message = Column(Text, nullable=True)

    indexed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("MedicalDocument")


# ============================================================
# AGENT EXECUTION AUDIT  (Phase 8)
# ============================================================

class AgentExecutionAudit(Base):
    """
    Persistent audit log of an agentic workflow execution.

    Maintains traceability, idempotency, execution performance,
    and agent-level steps for auditability and debugging.
    """

    __tablename__ = "agent_execution_audits"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed', 'escalated', 'degraded')",
            name="ck_agent_audit_status",
        ),
        Index(
            "ix_agent_audits_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_agent_audits_user_idempotency",
            "user_id",
            "idempotency_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    workflow_type = Column(
        String(60),
        nullable=False,
        index=True,
    )

    status = Column(
        String(30),
        nullable=False,
        default="pending",
    )

    idempotency_key = Column(
        String(64),
        nullable=True,
        index=True,
    )

    input_payload = Column(Text, nullable=True)

    execution_steps = Column(Text, nullable=True)

    result_summary = Column(Text, nullable=True)

    error_message = Column(Text, nullable=True)

    duration_ms = Column(Integer, nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    completed_at = Column(DateTime, nullable=True)

    user = relationship("UserProfile", back_populates="agent_audits")