"""Продукт без Telegram (docs/PIVOT-PWA.md, версия 2): аккаунты и несколько профилей, вход по почте, решения «не моё» / «сходил» / «не сходил»

accounts — аккаунт веб-сессии (гость, почта по желанию); profiles.account_id и profiles.kind — несколько профилей на аккаунт
(у существующих профилей создаётся свой аккаунт с тем же id, kind = self); email_tokens — одноразовые ссылки-входы (15 минут, хеш
токена); guest_user_id_seq — последовательность id гостевых сессий и новых профилей (с 10^12: не пересекается ни с бывшими
Telegram id, ни с тестовыми); в CHECK статусов решений добавлены «не моё», «сходил», «не сходил».

Revision ID: d8f2b6a40e15
Revises: c5e9a1d7b304
Create Date: 2026-10-25 12:00:00+00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'd8f2b6a40e15'
down_revision = 'c5e9a1d7b304'
branch_labels = None
depends_on = None

OLD = ("иду", "может", "интересно", "мимо", "пропуск")
NEW = OLD + ("не моё", "сходил", "не сходил")


def _in(values) -> str:
    return "status IN (" + ", ".join("'" + v + "'" for v in values) + ")"


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS guest_user_id_seq START 1000000000000")
    op.create_table(
        'accounts',
        sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    op.execute("INSERT INTO accounts (id) SELECT user_id FROM profiles")
    op.add_column('profiles', sa.Column('account_id', sa.BigInteger(), nullable=True))
    op.execute("UPDATE profiles SET account_id = user_id")
    op.alter_column('profiles', 'account_id', nullable=False)
    op.create_foreign_key('profiles_account_id_fkey', 'profiles', 'accounts', ['account_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_profiles_account_id'), 'profiles', ['account_id'])
    op.add_column('profiles', sa.Column('kind', sa.Enum('self', 'parent', 'child', 'other', name='profile_kind', native_enum=False,
                                                         create_constraint=True, length=24), server_default='self', nullable=False))
    op.create_table(
        'email_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=254), nullable=False),
        sa.Column('account_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_email_tokens_account_id'), 'email_tokens', ['account_id'])
    op.drop_constraint('decision_status', 'decisions', type_='check')
    op.create_check_constraint('decision_status', 'decisions', _in(NEW))


def downgrade() -> None:
    op.execute("UPDATE decisions SET status = 'мимо' WHERE status = 'не моё'")
    op.execute("UPDATE decisions SET status = 'иду' WHERE status = 'сходил'")
    op.execute("UPDATE decisions SET status = 'пропуск' WHERE status = 'не сходил'")
    op.drop_constraint('decision_status', 'decisions', type_='check')
    op.create_check_constraint('decision_status', 'decisions', _in(OLD))
    op.drop_index(op.f('ix_email_tokens_account_id'), table_name='email_tokens')
    op.drop_table('email_tokens')
    op.drop_column('profiles', 'kind')
    op.drop_index(op.f('ix_profiles_account_id'), table_name='profiles')
    op.drop_constraint('profiles_account_id_fkey', 'profiles', type_='foreignkey')
    op.drop_column('profiles', 'account_id')
    op.drop_table('accounts')
    op.execute("DROP SEQUENCE IF EXISTS guest_user_id_seq")
