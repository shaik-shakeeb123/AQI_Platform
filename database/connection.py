"""SQLAlchemy database engine, session factory, and helpers.

This module provides synchronous SQLAlchemy infrastructure:

* ``engine`` – a connection-pooled :class:`~sqlalchemy.engine.Engine`.
* ``SessionLocal`` – a :class:`~sqlalchemy.orm.Session` factory.
* ``Base`` – declarative base for ORM models.
* ``get_db()`` – FastAPI dependency that yields a scoped session.
* ``init_db()`` – creates all tables registered on ``Base.metadata``.

Production notes:
    - ``pool_recycle`` is set to 1800 s (30 min) to prevent stale TCP
      connections being reused after Render's managed-Postgres idle timeout.
    - ``connect_timeout`` guards against the engine hanging during startup if
      the database is temporarily unreachable.
    - ``statement_timeout`` (30 s) is applied at the session level so a single
      runaway query can never starve the connection pool.
    - For production schema migrations, use Alembic (``alembic upgrade head``)
      rather than relying on ``init_db()``.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from api_layer.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,  # recycle connections every 30 min to avoid Render idle-TCP drops
    echo=settings.DEBUG,
    connect_args={
        "connect_timeout": 10,            # TCP connect timeout (seconds)
        "options": "-c statement_timeout=30000",  # server-side 30 s query timeout (ms)
    },
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base: Any = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session.

    Yields a :class:`~sqlalchemy.orm.Session` and guarantees it is closed
    after the request finishes, regardless of whether an exception occurred.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables defined on :data:`Base` if they do not exist yet.

    This is called once during application startup.  For production
    migrations prefer Alembic.
    """
    from database.models.aqi_data import AQIData  # noqa: F401
    from database.models.user import User  # noqa: F401

    Base.metadata.create_all(bind=engine)

