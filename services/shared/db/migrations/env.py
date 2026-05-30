"""Alembic migration environment for FixED.

Target schema is the shared SQLAlchemy metadata (services/shared/db/models.py).
The database URL is taken from POSTGRES_URL at runtime so the same migrations
run against local Postgres and managed RDS without editing alembic.ini.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the shared package (services/shared) importable regardless of cwd.
SHARED_DIR = Path(__file__).resolve().parents[2]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import pgvector.sqlalchemy  # noqa: E402,F401  — register the Vector type for autogenerate
from db.models import Base  # noqa: E402

config = context.config

# Runtime DB URL wins over anything in alembic.ini.
_db_url = os.getenv("POSTGRES_URL") or config.get_main_option("sqlalchemy.url")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # Logging config is best-effort; never block a migration on it.
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without a DB connection (alembic upgrade --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
