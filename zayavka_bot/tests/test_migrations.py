"""Миграция alembic создаёт ту же схему, что описана в моделях."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from bot.db.migrate import upgrade_head
from bot.db.models import Base


def test_upgrade_head_matches_models(tmp_path):
    path = tmp_path / "m.db"
    upgrade_head(f"sqlite+aiosqlite:///{path}")
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert {"users", "answers", "leads", "slots", "bookings", "events", "scheduled_jobs"} <= tables
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
