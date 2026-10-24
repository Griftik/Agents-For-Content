"""profiles: ручная правка «Что я узнал о тебе» (affinity_manual_at + слой правок affinity_manual)

Пользователь может поправить affinity (спека 3.5). Правка хранится отдельным слоем — прибавкой к вычисленному по решениям —
и флагом affinity_manual_at, поэтому пересчёт по решениям её не затирает, а складывает с ней.

Revision ID: 5d8e2f4a6c11
Revises: 3c9d5e7a1b20
Create Date: 2026-10-24 19:00:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '5d8e2f4a6c11'
down_revision = '3c9d5e7a1b20'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('affinity_manual', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                                        server_default=sa.text('\'{"tag": {}, "cat": {}}\'::jsonb')))
    op.add_column('profiles', sa.Column('affinity_manual_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'affinity_manual_at')
    op.drop_column('profiles', 'affinity_manual')
