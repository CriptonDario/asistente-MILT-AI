"""Auditoría sin clave foránea: borrar un usuario no debe reescribir filas con hash.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22 15:31:31.578672

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_audit_log_user_id_users'), type_='foreignkey')



def downgrade() -> None:
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_foreign_key(batch_op.f('fk_audit_log_user_id_users'), 'users', ['user_id'], ['id'], ondelete='SET NULL')

