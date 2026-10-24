"""profiles.offer_due и открытия приглашений без профиля в growth_events

offer_due: день, когда повторить предложение онбординга приглашённому (день события + 1), вместо cookie на вебе.
growth_events.user_id становится nullable и получает invite_code: открытие приглашения человеком без согласия считается по коду,
профиль при этом не создаётся.

Revision ID: b3d7f0a5c812
Revises: 8a4c1e6d2b97
Create Date: 2026-10-24 22:00:00+00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b3d7f0a5c812'
down_revision = '8a4c1e6d2b97'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('offer_due', sa.Date(), nullable=True))
    op.alter_column('growth_events', 'user_id', existing_type=sa.BigInteger(), nullable=True)
    op.add_column('growth_events', sa.Column('invite_code', sa.String(length=8), nullable=True))
    op.create_index('ix_growth_events_invite_code', 'growth_events', ['invite_code'])


def downgrade() -> None:
    op.drop_index('ix_growth_events_invite_code', table_name='growth_events')
    op.drop_column('growth_events', 'invite_code')
    op.execute("DELETE FROM growth_events WHERE user_id IS NULL")
    op.alter_column('growth_events', 'user_id', existing_type=sa.BigInteger(), nullable=False)
    op.drop_column('profiles', 'offer_due')
