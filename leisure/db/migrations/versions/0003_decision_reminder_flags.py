"""decisions: флаги напоминания и запроса оценки на самом решении

«План на сегодня» и «Как прошло?» теперь привязаны к решению «иду» и его дню, а не к дайджесту уикенда
(Digest.plan_sent_at / feedback_sent_at остаются, воркер на них не опирается).

Revision ID: 3c9d5e7a1b20
Revises: 7b1f2c3d4e5f
Create Date: 2026-10-24 18:00:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '3c9d5e7a1b20'
down_revision = '7b1f2c3d4e5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('decisions', sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('decisions', sa.Column('feedback_asked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('decisions', 'feedback_asked_at')
    op.drop_column('decisions', 'reminded_at')
