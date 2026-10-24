"""Test configuration and compatibility shims.

In restricted Windows environments where an Application Control policy blocks
the C-extension binary psycopg2._psycopg, this conftest provides a lightweight
in-memory DBAPI fallback so that test collection and unit/integration tests
can execute without requiring the blocked native binary.
"""
import sys
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

try:
    import psycopg2
except ImportError as e:
    if "blocked this file" in str(e) or "DLL load failed" in str(e):
        # Application control policy blocked the binary on this workstation
        mock_psycopg2 = MagicMock()
        mock_psycopg2.__version__ = "2.9.10"
        mock_psycopg2.extensions = MagicMock()
        mock_psycopg2.extras = MagicMock()
        sys.modules["psycopg2"] = mock_psycopg2
        sys.modules["psycopg2._psycopg"] = mock_psycopg2
        sys.modules["psycopg2.extensions"] = mock_psycopg2.extensions
        sys.modules["psycopg2.extras"] = mock_psycopg2.extras


@pytest.fixture
def in_memory_db():
    """Isolated in-memory SQLite session with safe ingestion table lifecycle.

    Guarantees:
    - Never connects to or mutates remote Neon production database.
    - Preserves existing production database rows.
    - Safely creates only ingestion tables, avoiding unsupported PostgreSQL types in SQLite.
    - Drops tables and disposes connection in finally block even if assertions fail.
    """
    from database.connection import Base
    from data_sync.ingestion.models import IngestionState, IngestionRun, IngestionLocation
    from database.models.aqi_data import AQIData

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [AQIData.__table__, IngestionLocation.__table__, IngestionRun.__table__, IngestionState.__table__]
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine, tables=tables)
        engine.dispose()


@pytest.fixture
def db_session(in_memory_db):
    """Alias for in_memory_db to ensure db_session fixtures use isolated SQLite."""
    return in_memory_db
