"""initial schema

Revision ID: c35577a6a52e
Revises: 
Create Date: 2026-10-24 12:52:48.881797+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from leisure.db.types import DateList

revision = 'c35577a6a52e'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm — дедупликация событий по title ~ venue (п. 7 спеки); только PostgreSQL
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('organizers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('contact', sa.String(length=300), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('profiles',
    sa.Column('user_id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('city', sa.String(length=80), nullable=False),
    sa.Column('values', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('interests', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('tz', sa.String(length=64), nullable=False),
    sa.Column('digest_day', sa.SmallInteger(), nullable=False),
    sa.Column('digest_hour', sa.SmallInteger(), nullable=False),
    sa.Column('plan', sa.Enum('free', 'pro', name='profile_plan', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('affinity', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('onboarded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('digests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('weekend_start', sa.Date(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('items', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('opened', sa.Boolean(), nullable=False),
    sa.Column('decisions_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'weekend_start', name='uq_digests_user_weekend')
    )
    op.create_index(op.f('ix_digests_user_id'), 'digests', ['user_id'], unique=False)
    op.create_table('events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('slug', sa.String(length=120), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=False),
    sa.Column('subcategory', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.Enum('событие', 'выставка', 'место', name='event_kind', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('city', sa.String(length=80), nullable=False),
    sa.Column('dates', DateList(), nullable=False),
    sa.Column('time_text', sa.String(length=200), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('end_time', sa.Time(), nullable=True),
    sa.Column('duration_min', sa.Integer(), nullable=True),
    sa.Column('venue', sa.Text(), nullable=False),
    sa.Column('address', sa.Text(), nullable=False),
    sa.Column('metro', sa.String(length=200), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('price_from', sa.Integer(), nullable=True),
    sa.Column('price_text', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('why_fit_hint', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('tags', postgresql.ARRAY(sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('aesthetics', sa.SmallInteger(), nullable=False),
    sa.Column('novelty', sa.SmallInteger(), nullable=False),
    sa.Column('crowd', sa.Enum('камерно', 'людно', name='event_crowd', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('audience_30plus', sa.Boolean(), nullable=False),
    sa.Column('audience_kids', sa.Boolean(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('sources', postgresql.ARRAY(sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('rating', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('confidence', sa.Enum('подтверждено', 'вероятно', 'нужно проверить', name='event_confidence', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('status', sa.Enum('draft', 'published', 'archived', name='event_status', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('organizer_id', sa.Uuid(), nullable=True),
    sa.Column('promoted_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organizer_id'], ['organizers.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_events_category'), 'events', ['category'], unique=False)
    op.create_index('ix_events_dates_gin', 'events', ['dates'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_events_slug'), 'events', ['slug'], unique=True)
    op.create_index(op.f('ix_events_status'), 'events', ['status'], unique=False)
    op.create_index('ix_events_status_city', 'events', ['status', 'city'], unique=False)
    op.create_table('decisions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('иду', 'может', 'интересно', 'мимо', 'пропуск', name='decision_status', native_enum=False, create_constraint=True, length=24), nullable=False),
    sa.Column('reason', sa.String(length=40), nullable=True),
    sa.Column('day', sa.Date(), nullable=True),
    sa.Column('rating', sa.SmallInteger(), nullable=True),
    sa.Column('event_slug', sa.String(length=120), nullable=False),
    sa.Column('event_category', sa.String(length=80), nullable=False),
    sa.Column('event_tags', postgresql.ARRAY(sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'event_id', name='uq_decisions_user_event')
    )
    op.create_index(op.f('ix_decisions_event_id'), 'decisions', ['event_id'], unique=False)
    op.create_index('ix_decisions_user_created', 'decisions', ['user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_decisions_user_id'), 'decisions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_decisions_user_id'), table_name='decisions')
    op.drop_index('ix_decisions_user_created', table_name='decisions')
    op.drop_index(op.f('ix_decisions_event_id'), table_name='decisions')
    op.drop_table('decisions')
    op.drop_index('ix_events_status_city', table_name='events')
    op.drop_index(op.f('ix_events_status'), table_name='events')
    op.drop_index(op.f('ix_events_slug'), table_name='events')
    op.drop_index('ix_events_dates_gin', table_name='events', postgresql_using='gin')
    op.drop_index(op.f('ix_events_category'), table_name='events')
    op.drop_table('events')
    op.drop_index(op.f('ix_digests_user_id'), table_name='digests')
    op.drop_table('digests')
    op.drop_table('profiles')
    op.drop_table('organizers')
