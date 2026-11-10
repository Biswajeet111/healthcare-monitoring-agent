"""phase8 agent execution audits

Revision ID: d1e2f3a4b5c6
Revises: c1a2b3d4e5f6
Create Date: 2026-11-10 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_execution_audits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('workflow_type', sa.String(length=60), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending'),
        sa.Column('idempotency_key', sa.String(length=64), nullable=True),
        sa.Column('input_payload', sa.Text(), nullable=True),
        sa.Column('execution_steps', sa.Text(), nullable=True),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed', 'escalated', 'degraded')",
            name='ck_agent_audit_status',
        ),
        sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_execution_audits_id'), 'agent_execution_audits', ['id'], unique=False)
    op.create_index(op.f('ix_agent_execution_audits_user_id'), 'agent_execution_audits', ['user_id'], unique=False)
    op.create_index(op.f('ix_agent_execution_audits_workflow_type'), 'agent_execution_audits', ['workflow_type'], unique=False)
    op.create_index(op.f('ix_agent_execution_audits_idempotency_key'), 'agent_execution_audits', ['idempotency_key'], unique=False)
    op.create_index(
        'ix_agent_audits_user_created',
        'agent_execution_audits',
        ['user_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_agent_audits_user_idempotency',
        'agent_execution_audits',
        ['user_id', 'idempotency_key'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_agent_audits_user_idempotency', table_name='agent_execution_audits')
    op.drop_index('ix_agent_audits_user_created', table_name='agent_execution_audits')
    op.drop_index(op.f('ix_agent_execution_audits_idempotency_key'), table_name='agent_execution_audits')
    op.drop_index(op.f('ix_agent_execution_audits_workflow_type'), table_name='agent_execution_audits')
    op.drop_index(op.f('ix_agent_execution_audits_user_id'), table_name='agent_execution_audits')
    op.drop_index(op.f('ix_agent_execution_audits_id'), table_name='agent_execution_audits')
    op.drop_table('agent_execution_audits')
