"""Fase 5: herramientas (ejecuciones, scripts autorizados, reportes) y permisos.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-22 19:59:18.100343

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('automation_scripts',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('path', sa.String(length=1000), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('runner', sa.String(length=16), nullable=False),
    sa.Column('arg_pattern', sa.String(length=200), nullable=False),
    sa.Column('max_args', sa.Integer(), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_automation_scripts_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_automation_scripts')),
    sa.UniqueConstraint('name', name=op.f('uq_automation_scripts_name'))
    )
    op.create_table('security_reports',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_security_reports_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_security_reports'))
    )
    with op.batch_alter_table('security_reports', schema=None) as batch_op:
        batch_op.create_index('ix_security_reports_user_created', ['user_id', 'created_at'], unique=False)

    op.create_table('tool_executions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('call_id', sa.String(length=64), nullable=False),
    sa.Column('tool_name', sa.String(length=64), nullable=False),
    sa.Column('arguments', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('risk_level', sa.String(length=16), nullable=False),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('result_summary', sa.Text(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_tool_executions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_executions'))
    )
    with op.batch_alter_table('tool_executions', schema=None) as batch_op:
        batch_op.create_index('ix_tool_executions_user_created', ['user_id', 'created_at'], unique=False)

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tools_enabled', sa.Boolean(), server_default=sa.false(), nullable=False))

    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allowed_roots', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))
        batch_op.add_column(sa.Column('tool_policies', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('tool_policies')
        batch_op.drop_column('allowed_roots')

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_column('tools_enabled')

    with op.batch_alter_table('tool_executions', schema=None) as batch_op:
        batch_op.drop_index('ix_tool_executions_user_created')

    op.drop_table('tool_executions')
    with op.batch_alter_table('security_reports', schema=None) as batch_op:
        batch_op.drop_index('ix_security_reports_user_created')

    op.drop_table('security_reports')
    op.drop_table('automation_scripts')
