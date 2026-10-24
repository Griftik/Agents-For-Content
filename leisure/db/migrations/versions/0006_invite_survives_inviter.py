"""invites.inviter_id: приглашение переживает удаление пригласившего (статус gone), без персональных данных

Раньше приглашение удалялось каскадом вместе с профилем пригласившего, и ссылка отвечала 404. Теперь inviter_id обнуляется
(ON DELETE SET NULL): друг видит «Тебя зовут на событие» и может записаться, а связи с удалившим профиль не остаётся.

Revision ID: 8a4c1e6d2b97
Revises: 6e1a9b3c7d42
Create Date: 2026-10-24 21:00:00+00:00
"""
from __future__ import annotations

from alembic import op

revision = '8a4c1e6d2b97'
down_revision = '6e1a9b3c7d42'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('invites_inviter_id_fkey', 'invites', type_='foreignkey')
    op.alter_column('invites', 'inviter_id', nullable=True)
    op.create_foreign_key('invites_inviter_id_fkey', 'invites', 'profiles', ['inviter_id'], ['user_id'], ondelete='SET NULL')


def downgrade() -> None:
    op.execute("DELETE FROM invites WHERE inviter_id IS NULL")
    op.drop_constraint('invites_inviter_id_fkey', 'invites', type_='foreignkey')
    op.alter_column('invites', 'inviter_id', nullable=False)
    op.create_foreign_key('invites_inviter_id_fkey', 'invites', 'profiles', ['inviter_id'], ['user_id'], ondelete='CASCADE')
