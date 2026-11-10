"""phase6 and phase7 tables

Revision ID: c1a2b3d4e5f6
Revises: 8131dd90339b
Create Date: 2026-11-10 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '8131dd90339b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----------------------------------------------------------------
    # medication_schedules
    # ----------------------------------------------------------------
    op.create_table(
        'medication_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('medication_id', sa.Integer(), nullable=False),
        sa.Column('schedule_type', sa.String(length=20), nullable=False),
        sa.Column('times_of_day_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('weekdays_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('timezone', sa.String(length=60), nullable=False, server_default='UTC'),
        sa.Column('effective_from', sa.DateTime(), nullable=False),
        sa.Column('effective_until', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "schedule_type IN ('daily', 'weekly', 'as_needed')",
            name='ck_med_schedule_type',
        ),
        sa.ForeignKeyConstraint(['medication_id'], ['medications.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_medication_schedules_id'), 'medication_schedules', ['id'], unique=False)
    op.create_index(op.f('ix_medication_schedules_medication_id'), 'medication_schedules', ['medication_id'], unique=False)

    # ----------------------------------------------------------------
    # medication_dose_occurrences
    # ----------------------------------------------------------------
    op.create_table(
        'medication_dose_occurrences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('medication_id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='upcoming'),
        sa.Column('taken_at', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('upcoming','due','overdue','taken','skipped','missed')",
            name='ck_dose_occurrence_status',
        ),
        sa.ForeignKeyConstraint(['medication_id'], ['medications.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['schedule_id'], ['medication_schedules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('schedule_id', 'scheduled_at', name='uq_dose_occurrence_schedule_scheduled_at'),
    )
    op.create_index(op.f('ix_medication_dose_occurrences_id'), 'medication_dose_occurrences', ['id'], unique=False)
    op.create_index(op.f('ix_medication_dose_occurrences_medication_id'), 'medication_dose_occurrences', ['medication_id'], unique=False)
    op.create_index(op.f('ix_medication_dose_occurrences_schedule_id'), 'medication_dose_occurrences', ['schedule_id'], unique=False)
    op.create_index('ix_dose_occ_medication_scheduled', 'medication_dose_occurrences', ['medication_id', 'scheduled_at'], unique=False)

    # ----------------------------------------------------------------
    # medication_reminders
    # ----------------------------------------------------------------
    op.create_table(
        'medication_reminders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('occurrence_id', sa.Integer(), nullable=False),
        sa.Column('medication_id', sa.Integer(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','acknowledged','dismissed')",
            name='ck_reminder_status',
        ),
        sa.ForeignKeyConstraint(['medication_id'], ['medications.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['occurrence_id'], ['medication_dose_occurrences.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('occurrence_id', name='uq_reminder_occurrence'),
    )
    op.create_index(op.f('ix_medication_reminders_id'), 'medication_reminders', ['id'], unique=False)
    op.create_index(op.f('ix_medication_reminders_medication_id'), 'medication_reminders', ['medication_id'], unique=False)
    op.create_index(op.f('ix_medication_reminders_occurrence_id'), 'medication_reminders', ['occurrence_id'], unique=False)
    op.create_index(op.f('ix_medication_reminders_user_id'), 'medication_reminders', ['user_id'], unique=False)

    # ----------------------------------------------------------------
    # medical_knowledge_documents
    # ----------------------------------------------------------------
    op.create_table(
        'medical_knowledge_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('source_organization', sa.String(length=200), nullable=True),
        sa.Column('source_url', sa.String(length=1000), nullable=True),
        sa.Column('document_type', sa.String(length=100), nullable=True),
        sa.Column('publication_date', sa.String(length=20), nullable=True),
        sa.Column('review_date', sa.String(length=20), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('source_path', sa.String(length=1000), nullable=True),
        sa.Column('index_status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('indexed_at', sa.DateTime(), nullable=True),
        sa.Column('ingested_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('content_hash', name='uq_knowledge_doc_hash'),
    )
    op.create_index(op.f('ix_medical_knowledge_documents_id'), 'medical_knowledge_documents', ['id'], unique=False)

    # ----------------------------------------------------------------
    # medical_knowledge_chunks
    # ----------------------------------------------------------------
    op.create_table(
        'medical_knowledge_chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('chroma_id', sa.String(length=100), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['medical_knowledge_documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chroma_id', name='uq_knowledge_chunk_chroma_id'),
    )
    op.create_index(op.f('ix_medical_knowledge_chunks_id'), 'medical_knowledge_chunks', ['id'], unique=False)
    op.create_index(op.f('ix_medical_knowledge_chunks_chroma_id'), 'medical_knowledge_chunks', ['chroma_id'], unique=True)
    op.create_index(op.f('ix_medical_knowledge_chunks_document_id'), 'medical_knowledge_chunks', ['document_id'], unique=False)

    # ----------------------------------------------------------------
    # document_index_statuses
    # ----------------------------------------------------------------
    op.create_table(
        'document_index_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('chunk_count', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('indexed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['medical_documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', name='uq_doc_index_status_doc'),
    )
    op.create_index(op.f('ix_document_index_statuses_id'), 'document_index_statuses', ['id'], unique=False)
    op.create_index(op.f('ix_document_index_statuses_document_id'), 'document_index_statuses', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_index_statuses_user_id'), 'document_index_statuses', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_table('document_index_statuses')
    op.drop_table('medical_knowledge_chunks')
    op.drop_table('medical_knowledge_documents')
    op.drop_table('medication_reminders')
    op.drop_table('medication_dose_occurrences')
    op.drop_table('medication_schedules')
