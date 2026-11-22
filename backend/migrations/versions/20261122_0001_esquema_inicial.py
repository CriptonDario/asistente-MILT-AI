"""Esquema inicial: usuarios, sesiones, conversaciones, mensajes, ajustes y auditoría.

Revision ID: 0001
Revises: 
Create Date: 2026-11-22 12:18:45.556422

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Esquema inicial de la Fase 2 (generado con autogenerate y revisado).
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=64), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('entry_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_log_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log')),
    sa.UniqueConstraint('entry_hash', name=op.f('uq_audit_log_entry_hash'))
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index('ix_audit_log_action_created', ['action', 'created_at'], unique=False)
        batch_op.create_index('ix_audit_log_user_created', ['user_id', 'created_at'], unique=False)

    op.create_table('conversations',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('model', sa.String(length=200), nullable=True),
    sa.Column('agent_profile', sa.String(length=32), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('pinned', sa.Boolean(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('sync_enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_hlc', sa.String(length=64), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('origin_device_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations'))
    )
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.create_index('ix_conversations_user_updated', ['user_id', 'updated_at'], unique=False)

    op.create_table('devices',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('platform', sa.String(length=16), nullable=False),
    sa.Column('remote_access_enabled', sa.Boolean(), nullable=False),
    sa.Column('public_key', sa.Text(), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_devices_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_devices'))
    )
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_devices_user_id'), ['user_id'], unique=False)

    op.create_table('user_settings',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('theme', sa.String(length=16), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('default_model', sa.String(length=200), nullable=True),
    sa.Column('generation_defaults', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings'))
    )
    op.create_table('messages',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=True),
    sa.Column('tool_calls', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_hlc', sa.String(length=64), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('origin_device_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.create_index('ix_messages_conversation_created', ['conversation_id', 'created_at'], unique=False)

    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('device_id', sa.Uuid(), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['device_id'], ['devices.id'], name=op.f('fk_refresh_tokens_device_id_devices'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.create_index('ix_refresh_tokens_family_id', ['family_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_refresh_tokens_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    # Esquema inicial de la Fase 2 (generado con autogenerate y revisado).
    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_refresh_tokens_user_id'))
        batch_op.drop_index('ix_refresh_tokens_family_id')

    op.drop_table('refresh_tokens')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_conversation_created')

    op.drop_table('messages')
    op.drop_table('user_settings')
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_devices_user_id'))

    op.drop_table('devices')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_index('ix_conversations_user_updated')

    op.drop_table('conversations')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_log_user_created')
        batch_op.drop_index('ix_audit_log_action_created')

    op.drop_table('audit_log')
    op.drop_table('users')
