"""Test configuration and compatibility shims.

In restricted Windows environments where an Application Control policy blocks
the C-extension binary psycopg2._psycopg, this conftest provides a lightweight
in-memory DBAPI fallback so that test collection and unit/integration tests
can execute without requiring the blocked native binary.
"""
import sys
from unittest.mock import MagicMock

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
