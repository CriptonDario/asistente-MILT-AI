"""Fase 4: recuerdos, documentos, fragmentos, adjuntos y fuentes de contexto.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22 17:47:20.128694

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('documents',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('storage_key', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('embedding_model', sa.String(length=200), nullable=True),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('char_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_documents_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_documents_storage_key'))
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index('ix_documents_user_status', ['user_id', 'status'], unique=False)

    op.create_table('memories',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('source_conversation_id', sa.Uuid(), nullable=True),
    sa.Column('importance', sa.Float(), nullable=False),
    sa.Column('is_sensitive', sa.Boolean(), nullable=False),
    sa.Column('embedding_model', sa.String(length=200), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_hlc', sa.String(length=64), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('origin_device_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memories_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memories'))
    )
    with op.batch_alter_table('memories', schema=None) as batch_op:
        batch_op.create_index('ix_memories_user_status', ['user_id', 'status'], unique=False)

    op.create_table('document_chunks',
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('locator', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_chunks_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunks'))
    )
    with op.batch_alter_table('document_chunks', schema=None) as batch_op:
        batch_op.create_index('ix_document_chunks_document_ordinal', ['document_id', 'ordinal'], unique=False)

    op.create_table('message_attachments',
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_message_attachments_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_message_attachments_message_id_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id', 'document_id', name=op.f('pk_message_attachments'))
    )
    with op.batch_alter_table('message_attachments', schema=None) as batch_op:
        batch_op.create_index('ix_message_attachments_document_id', ['document_id'], unique=False)

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('context_sources', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))

    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('memory_enabled', sa.Boolean(), server_default=sa.true(), nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('memory_enabled')

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('context_sources')

    with op.batch_alter_table('message_attachments', schema=None) as batch_op:
        batch_op.drop_index('ix_message_attachments_document_id')

    op.drop_table('message_attachments')
    with op.batch_alter_table('document_chunks', schema=None) as batch_op:
        batch_op.drop_index('ix_document_chunks_document_ordinal')

    op.drop_table('document_chunks')
    with op.batch_alter_table('memories', schema=None) as batch_op:
        batch_op.drop_index('ix_memories_user_status')

    op.drop_table('memories')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index('ix_documents_user_status')

    op.drop_table('documents')
