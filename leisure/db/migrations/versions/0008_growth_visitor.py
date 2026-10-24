"""growth_events.visitor: псевдоним человека без согласия для одной ссылки

Метрики роста считают открывших без согласия (invite_open / invite_declined) в знаменателях «принятия» и «активации», а повторные
открытия одного человека не должны их раздувать. visitor — усечённый HMAC от кода и user_id с серверным ключом; удаляется вместе со
строкой, когда человек даёт согласие.

Revision ID: c5e9a1d7b304
Revises: b3d7f0a5c812
Create Date: 2026-10-24 23:00:00+00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'c5e9a1d7b304'
down_revision = 'b3d7f0a5c812'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('growth_events', sa.Column('visitor', sa.String(length=16), nullable=True))
    op.create_index('ix_growth_events_visitor', 'growth_events', ['visitor'])


def downgrade() -> None:
    op.drop_index('ix_growth_events_visitor', table_name='growth_events')
    op.drop_column('growth_events', 'visitor')
