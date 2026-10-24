"""digests: отметки отправки «План на сегодня» и «Как прошло?»

Revision ID: 7b1f2c3d4e5f
Revises: c35577a6a52e
Create Date: 2026-10-24 14:10:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '7b1f2c3d4e5f'
down_revision = 'c35577a6a52e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('digests', sa.Column('plan_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('digests', sa.Column('feedback_sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('digests', 'feedback_sent_at')
    op.drop_column('digests', 'plan_sent_at')
