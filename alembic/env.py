"""Alembic environment configuration.

Dynamically resolves the database URL from the application settings so that
Alembic uses the same connection string as the FastAPI application.  The
``target_metadata`` is set to ``Base.metadata`` so that ``--autogenerate``
can diff the ORM models against the live schema.
"""
from __future__ import annotations

import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ---------------------------------------------------------------------------
# Make the project root importable when running ``alembic`` from the CLI.
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Alembic Config object – provides access to values in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# Set up Python logging using the ini file (if we have one).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Override sqlalchemy.url with the value from application settings so we
# never hard-code credentials in alembic.ini.
# ---------------------------------------------------------------------------
from api_layer.config import get_settings  # noqa: E402
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.DATABASE_URL)

# ---------------------------------------------------------------------------
# Import all ORM models so Alembic autogenerate can detect them.
# ---------------------------------------------------------------------------
from database.connection import Base          # noqa: E402, F401
from database.models.aqi_data import AQIData  # noqa: E402, F401
from database.models.user import User         # noqa: E402, F401

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Migration runners
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in *offline* mode.

    Configures the context with just a URL, not a live connection.
    Useful for generating SQL scripts without a live database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in *online* mode with a live database connection."""
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
