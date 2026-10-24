"""рост через друзей (docs/GROWTH.md): invites, invite_accepts, growth_events, Profile.source / referred_by / show_name, Decision.invite_id

Revision ID: 6e1a9b3c7d42
Revises: 5d8e2f4a6c11
Create Date: 2026-10-24 16:38:45.370536+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '6e1a9b3c7d42'
down_revision = '5d8e2f4a6c11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('growth_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_growth_events_user_id'), 'growth_events', ['user_id'], unique=False)
    op.create_table('invites',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=8), nullable=False),
    sa.Column('inviter_id', sa.BigInteger(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=True),
    sa.Column('event_slug', sa.String(length=120), server_default='', nullable=False),
    sa.Column('day', sa.Date(), nullable=True),
    sa.Column('kind', sa.Enum('event', 'ref', name='invite_kind', native_enum=False, create_constraint=True, length=24), server_default='event', nullable=False),
    sa.Column('opened', sa.Integer(), server_default='0', nullable=False),
    sa.Column('accepted', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['inviter_id'], ['profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invites_code'), 'invites', ['code'], unique=True)
    op.create_index(op.f('ix_invites_inviter_id'), 'invites', ['inviter_id'], unique=False)
    op.create_table('invite_accepts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('invite_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Enum('opened', 'going', 'maybe', 'declined', name='invite_status', native_enum=False, create_constraint=True, length=24), server_default='opened', nullable=False),
    sa.Column('was_new', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['invite_id'], ['invites.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invite_id', 'user_id', name='uq_invite_accepts_invite_user')
    )
    op.create_index(op.f('ix_invite_accepts_invite_id'), 'invite_accepts', ['invite_id'], unique=False)
    op.create_index(op.f('ix_invite_accepts_user_id'), 'invite_accepts', ['user_id'], unique=False)
    op.add_column('decisions', sa.Column('invite_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_decisions_invite_id', 'decisions', 'invites', ['invite_id'], ['id'], ondelete='SET NULL')
    op.add_column('profiles', sa.Column('source', sa.Enum('organic', 'invite', 'ref', 'share', name='profile_source', native_enum=False, create_constraint=True, length=24), server_default='organic', nullable=False))
    op.add_column('profiles', sa.Column('referred_by', sa.BigInteger(), nullable=True))
    op.add_column('profiles', sa.Column('show_name', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('profiles', sa.Column('can_write', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('profiles', sa.Column('offer_seen', sa.SmallInteger(), server_default='0', nullable=False))
    op.create_foreign_key('fk_profiles_referred_by', 'profiles', 'profiles', ['referred_by'], ['user_id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_profiles_referred_by', 'profiles', type_='foreignkey')
    op.drop_column('profiles', 'offer_seen')
    op.drop_column('profiles', 'can_write')
    op.drop_column('profiles', 'show_name')
    op.drop_column('profiles', 'referred_by')
    op.drop_column('profiles', 'source')
    op.drop_constraint('fk_decisions_invite_id', 'decisions', type_='foreignkey')
    op.drop_column('decisions', 'invite_id')
    op.drop_index(op.f('ix_invite_accepts_user_id'), table_name='invite_accepts')
    op.drop_index(op.f('ix_invite_accepts_invite_id'), table_name='invite_accepts')
    op.drop_table('invite_accepts')
    op.drop_index(op.f('ix_invites_inviter_id'), table_name='invites')
    op.drop_index(op.f('ix_invites_code'), table_name='invites')
    op.drop_table('invites')
    op.drop_index(op.f('ix_growth_events_user_id'), table_name='growth_events')
    op.drop_table('growth_events')
